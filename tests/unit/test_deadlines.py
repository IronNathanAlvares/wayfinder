"""Closing windows.

The arithmetic here is trivial and is not what these tests are about. What they
guard is the wording and the ordering, because both encode a decision that is
easy to undo by accident: **this system never tells anybody their window has
shut, and never demotes a task because it looks past.**

The asymmetry is the argument. Telling somebody they may still have time when
they do not costs a phone call. Telling somebody they are out of time when they
are not costs them the thing itself. A future contributor tidying
`MAY_HAVE_CLOSED` into `CLOSED`, or filtering expired tasks out of the frontier
to keep it clean, would be making a reasonable-looking change with that second
cost, so the tests say so out loud.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from wayfinder.cli.render import _deadline_line
from wayfinder.corpus.loader import load_corpus
from wayfinder.plan.builder import build_plan
from wayfinder.plan.deadlines import (
    CLOSING_SOON,
    DeadlineStatus,
    deadlines_for,
    state_of,
)
from wayfinder.plan.models import Deadline
from wayfinder.plan.plan import Plan
from wayfinder.plan.situation import (
    Accommodation,
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)

TODAY = date(2026, 8, 24)
HRC = "determination:habitual_residence"

APPEAL = Deadline(
    within=timedelta(days=60), of=HRC, described_as="the date on the decision letter"
)


def refused_on(day: date) -> Situation:
    return Situation(
        determinations={
            HRC: DeterminationRecord(
                outcome=DeterminationOutcome.REFUSED,
                authority="Deciding Officer, Department of Social Protection",
                recorded_on=day,
            )
        }
    )


# --- the model ----------------------------------------------------------------


def test_a_window_must_run_from_something_a_situation_can_date() -> None:
    """A window hung off an `elapsed:` or `task:` ref could never be computed,
    so it would render as "we do not know when this started" forever and look
    like a bug rather than a modelling mistake."""
    for ref in ("elapsed:since_application", "task:ppsn.apply"):
        with pytest.raises(ValidationError, match="has to start from something"):
            Deadline(within=timedelta(days=60), of=ref, described_as="a letter")


def test_a_window_must_be_positive() -> None:
    for bad in (timedelta(0), timedelta(days=-1)):
        with pytest.raises(ValidationError, match="must be positive"):
            Deadline(within=bad, of=HRC, described_as="a letter")


def test_a_document_is_allowed_to_start_a_clock() -> None:
    """Allowed by the model even though no situation carries a document date
    yet. `_started_on` returns unknown rather than guessing, so this degrades to
    stating the rule instead of inventing a date."""
    deadline = Deadline(
        within=timedelta(days=30), of="document:ppsn", described_as="the date issued"
    )
    state = state_of(deadline, Situation(), today=TODAY)
    assert state.status is DeadlineStatus.UNKNOWN_START


# --- what the clock says ------------------------------------------------------


def test_an_unrecorded_determination_leaves_the_start_unknown() -> None:
    """The common case: the corpus knows the rule, nobody has told us the date.
    That is still worth saying, so it is a status rather than an absence."""
    state = state_of(APPEAL, Situation(), today=TODAY)

    assert state.status is DeadlineStatus.UNKNOWN_START
    assert state.days_remaining is None
    assert not state.running
    assert state.within == timedelta(days=60)


def test_a_window_with_room_left_is_open() -> None:
    state = state_of(APPEAL, refused_on(date(2026, 8, 1)), today=TODAY)

    assert state.status is DeadlineStatus.OPEN
    assert state.started_on == date(2026, 8, 1)
    assert state.closes_on == date(2026, 9, 30)
    assert state.days_remaining == 37
    assert state.running


@pytest.mark.parametrize("days_left", [7, 3, 1, 0])
def test_a_window_inside_the_last_week_is_closing(days_left: int) -> None:
    """A week is where post, an appointment and an office shut on Sunday stop
    being absorbable."""
    started = TODAY - timedelta(days=60) + timedelta(days=days_left)
    state = state_of(APPEAL, refused_on(started), today=TODAY)

    assert state.status is DeadlineStatus.CLOSING
    assert state.days_remaining == days_left


def test_the_boundary_of_closing_is_where_it_says_it_is() -> None:
    just_outside = TODAY - timedelta(days=60) + CLOSING_SOON + timedelta(days=1)
    assert state_of(APPEAL, refused_on(just_outside), today=TODAY).status is (
        DeadlineStatus.OPEN
    )


def test_a_window_past_its_end_only_ever_may_have_closed() -> None:
    """The single most important assertion in this file.

    The start date came from somebody's memory of a letter and late
    applications are often accepted, so the strongest honest statement is that
    it may have run out.
    """
    state = state_of(APPEAL, refused_on(date(2026, 3, 1)), today=TODAY)

    assert state.status is DeadlineStatus.MAY_HAVE_CLOSED
    assert state.days_remaining is not None
    assert state.days_remaining < 0


def test_there_is_no_status_that_says_a_window_is_shut() -> None:
    """Guards the enum itself. Adding `CLOSED` would be a natural-looking tidy
    up, and it is the one value this must not have."""
    names = {member.name for member in DeadlineStatus}
    assert "CLOSED" not in names
    assert "EXPIRED" not in names
    assert "MAY_HAVE_CLOSED" in names


# --- how it is said -----------------------------------------------------------


def test_a_deadline_is_never_approximated() -> None:
    """`_humanise` renders 60 days as "about 9 weeks", which is right for a wait
    and wrong for a statute. Somebody rounding that down loses days they had.
    """
    line = _deadline_line(state_of(APPEAL, Situation(), today=TODAY))

    assert "60 days" in line
    assert "week" not in line


def test_a_window_that_may_have_closed_tells_the_person_to_ask() -> None:
    """Rather than telling them it is over. This is the wording the whole
    module exists to protect."""
    line = _deadline_line(state_of(APPEAL, refused_on(date(2026, 3, 1)), today=TODAY))

    assert "may be wrong" in line
    assert "often still accepted" in line
    assert "Ask a caseworker" in line

    # The last clause is what somebody skimming takes away, so it has to be the
    # instruction rather than the bad news. An earlier draft ended on "it is
    # too late" and this assertion is why it does not.
    assert line.rstrip().endswith("Ask a caseworker to check it.")
    for verdict in ("too late", "has closed", "expired", "no longer"):
        assert verdict not in line


def test_the_last_day_is_said_as_the_last_day() -> None:
    started = TODAY - timedelta(days=60)
    line = _deadline_line(state_of(APPEAL, refused_on(started), today=TODAY))

    assert "today is the last day" in line
    assert "0 days" not in line, "counting down to zero reads as already gone"


def test_one_day_left_is_singular() -> None:
    started = TODAY - timedelta(days=59)
    assert "1 day left" in _deadline_line(
        state_of(APPEAL, refused_on(started), today=TODAY)
    )


def test_an_unknown_start_asks_for_the_date_rather_than_going_quiet() -> None:
    line = _deadline_line(state_of(APPEAL, Situation(), today=TODAY))

    assert "the date on the decision letter" in line
    assert "caseworker" in line


# --- over a whole task list ---------------------------------------------------


def test_deadlines_for_covers_only_tasks_that_have_one() -> None:
    corpus = load_corpus(Path("src/wayfinder/corpus/data"), today=TODAY)
    states = deadlines_for(corpus.tasks, refused_on(date(2026, 8, 1)), today=TODAY)

    assert set(states) == {t.id for t in corpus.tasks if t.deadline is not None}
    assert "appeal.social_welfare" in states


# --- where a closing window sorts ---------------------------------------------


def built(situation: Situation) -> Plan:
    corpus = load_corpus(Path("src/wayfinder/corpus/data"), today=TODAY)
    return build_plan(corpus.tasks, situation, today=TODAY)


def eligible_to_appeal(refused: date) -> Situation:
    """Somebody refused, holding what the appeal needs, so it is startable."""
    return Situation(
        arrival_date=date(2026, 1, 10),
        protection_application_date=date(2026, 1, 12),
        protection_stage=ProtectionStage.GRANTED,
        accommodation=Accommodation.PRIVATE,
        household=Household(adults=1, children_ages=(7,)),
        held=frozenset(
            {"document:ppsn", "document:national_id", "document:proof_of_address"}
        ),
        determinations={
            HRC: DeterminationRecord(
                outcome=DeterminationOutcome.REFUSED,
                authority="Deciding Officer, Department of Social Protection",
                recorded_on=refused,
            )
        },
    )


def test_a_running_clock_outranks_a_critical_task() -> None:
    """Severity assumes the thing is still there to do later. A deadline breaks
    that assumption, so it is a band above rather than a tiebreak inside."""
    plan = built(eligible_to_appeal(date(2026, 7, 1)))

    assert plan.frontier_order[0] == "appeal.social_welfare"
    criticals = [
        i.task.id
        for i in plan.frontier
        if i.task.blocking_severity.rank == 0 and i.task.id != "appeal.social_welfare"
    ]
    assert criticals, "no critical task in the frontier, so this proves nothing"


def test_a_window_that_may_have_closed_is_not_demoted_or_dropped() -> None:
    """The other half of never saying "closed".

    Filtering an apparently expired task out of the frontier, or sinking it to
    the bottom, would be a reasonable-looking tidy up that silently does the
    discouraging thing the wording refuses to do.
    """
    plan = built(eligible_to_appeal(date(2026, 3, 1)))

    assert "appeal.social_welfare" in plan.frontier_order
    assert plan.frontier_order[0] == "appeal.social_welfare"
    assert (
        plan.deadlines["appeal.social_welfare"].status is DeadlineStatus.MAY_HAVE_CLOSED
    )


def test_the_sooner_window_sorts_first_among_running_clocks() -> None:
    from wayfinder.plan.critical_path import rank_frontier

    tasks = built(eligible_to_appeal(date(2026, 7, 1))).frontier
    appeal = next(i.task for i in tasks if i.task.id == "appeal.social_welfare")
    other = next(i.task for i in tasks if i.task.id != "appeal.social_welfare")

    urgent = state_of(APPEAL, refused_on(TODAY - timedelta(days=58)), today=TODAY)
    relaxed = state_of(APPEAL, refused_on(TODAY - timedelta(days=2)), today=TODAY)

    assert rank_frontier([appeal, other], {}, {appeal.id: urgent})[0] == appeal.id
    assert rank_frontier([other, appeal], {}, {appeal.id: relaxed})[0] == appeal.id


def test_a_window_with_no_known_start_does_not_jump_the_queue() -> None:
    """There is a real window and no way to say how much is left. Ranking it
    first on a number nobody has would push a critical task down for nothing.
    """
    plan = built(
        Situation(
            arrival_date=date(2026, 1, 10),
            protection_stage=ProtectionStage.GRANTED,
            accommodation=Accommodation.PRIVATE,
            held=frozenset({"document:ppsn", "document:proof_of_address"}),
        )
    )

    state = plan.deadlines.get("appeal.social_welfare")
    if state is not None and "appeal.social_welfare" in plan.frontier_order:
        assert state.status is DeadlineStatus.UNKNOWN_START
        assert plan.frontier_order[0] != "appeal.social_welfare"
