"""Replanning diffs, and the properties that must hold for any situation.

The property tests generate situations rather than enumerating them. Acyclicity
in particular has to hold for every reachable situation, not just the twelve
somebody thought of, because a cycle that only appears for one combination of
facts is exactly the one that reaches a person rather than a test.
"""

from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.personas.cases import NOTHING_YET
from wayfinder.corpus.models import Corpus
from wayfinder.plan.builder import build_plan
from wayfinder.plan.diff import diff_plans
from wayfinder.plan.plan import ItemStatus
from wayfinder.plan.situation import (
    Accommodation,
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)

HOLDABLE = sorted(NOTHING_YET | {"document:identity"})

situations = st.builds(
    Situation,
    arrival_date=st.one_of(
        st.none(),
        st.dates(min_value=date(2024, 1, 1), max_value=date(2026, 8, 17)),
    ),
    protection_stage=st.one_of(st.none(), st.sampled_from(ProtectionStage)),
    accommodation=st.one_of(st.none(), st.sampled_from(Accommodation)),
    household=st.one_of(
        st.none(),
        st.builds(
            Household,
            adults=st.integers(min_value=0, max_value=4),
            children_ages=st.tuples()
            | st.tuples(st.integers(min_value=0, max_value=25)),
        ),
    ),
    held=st.sets(st.sampled_from(HOLDABLE)).map(frozenset),
)


@settings(max_examples=200, deadline=None)
@given(situation=situations)
def test_any_situation_produces_an_acyclic_ordered_plan(
    situation: Situation, corpus: Corpus, today: date
) -> None:
    """No generated situation may produce a cycle or an out-of-order plan."""
    plan = build_plan(corpus.tasks, situation, today=today)
    position = {item.task.id: i for i, item in enumerate(plan.items)}
    produced_by = {
        artefact: item.task.id for item in plan.items for artefact in item.task.yields
    }
    for item in plan.items:
        for requirement in item.task.requires:
            for ref in requirement.any_of:
                producer = produced_by.get(ref)
                if producer is not None and producer != item.task.id:
                    assert position[producer] < position[item.task.id]


@settings(max_examples=200, deadline=None)
@given(situation=situations)
def test_every_task_lands_in_exactly_one_partition(
    situation: Situation, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, situation, today=today)
    total = (
        len(plan.frontier) + len(plan.blocked) + len(plan.done) + len(plan.needs_info)
    )
    assert total == len(plan.items)


@settings(max_examples=200, deadline=None)
@given(situation=situations)
def test_a_frontier_task_never_has_an_outstanding_requirement(
    situation: Situation, corpus: Corpus, today: date
) -> None:
    """Telling somebody to start something they cannot start is the worst
    failure this engine has available to it."""
    plan = build_plan(corpus.tasks, situation, today=today)
    for item in plan.frontier:
        assert item.unmet == ()
        assert item.unresolved == ()


@settings(max_examples=200, deadline=None)
@given(situation=situations)
def test_a_determination_is_never_an_open_question(
    situation: Situation, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, situation, today=today)
    assert not any(q.startswith("determination:") for q in plan.open_questions)


@settings(max_examples=100, deadline=None)
@given(situation=situations)
def test_next_actions_are_always_startable(
    situation: Situation, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, situation, today=today)
    startable = plan.ids([ItemStatus.FRONTIER])
    for actions in plan.next_actions.values():
        assert set(actions) <= startable


BASE = Situation(
    arrival_date=date(2026, 8, 3),
    protection_stage=ProtectionStage.APPLIED,
    accommodation=Accommodation.EMERGENCY,
    household=Household(adults=1, children_ages=(7,)),
    held=frozenset({"document:identity"}),
    known_absent=NOTHING_YET,
)


def _with(**changes: object) -> Situation:
    return Situation.model_validate(BASE.model_dump() | changes)


def test_a_diff_against_itself_is_empty(corpus: Corpus, today: date) -> None:
    plan = build_plan(corpus.tasks, BASE, today=today)
    assert diff_plans(plan, plan).empty


def test_getting_a_document_leads_with_what_is_newly_startable(
    corpus: Corpus, today: date
) -> None:
    before = build_plan(corpus.tasks, BASE, today=today)
    after = build_plan(
        corpus.tasks,
        _with(
            held=frozenset({"document:identity", "document:shelter_letter"}),
            known_absent=NOTHING_YET - {"document:shelter_letter"},
        ),
        today=today,
    )
    changes = diff_plans(before, after)
    assert "permit.apply" in changes.newly_unblocked
    assert "address.evidence" in changes.newly_unblocked


def test_moving_house_removes_tasks_and_says_so(corpus: Corpus, today: date) -> None:
    """A task disappearing can read as something being taken away, so it is
    reported as its own category rather than silently vanishing."""
    before = build_plan(corpus.tasks, BASE, today=today)
    after = build_plan(
        corpus.tasks, _with(accommodation=Accommodation.PRIVATE), today=today
    )
    changes = diff_plans(before, after)
    assert "shelter.letter_request" in changes.no_longer_applicable
    assert "tenancy.obtain" in changes.newly_applicable


def test_answering_a_question_is_reported_separately(
    corpus: Corpus, today: date
) -> None:
    unknown_identity = _with(held=frozenset())
    before = build_plan(corpus.tasks, unknown_identity, today=today)
    after = build_plan(corpus.tasks, BASE, today=today)
    changes = diff_plans(before, after)
    assert "id.replace" in changes.no_longer_applicable or "id.replace" in (
        changes.answered
    )


def test_time_passing_alone_changes_the_plan(corpus: Corpus, today: date) -> None:
    """Nothing the person did, and the plan still moves. This is the case a
    static checklist cannot express."""
    situation = _with(
        held=frozenset({"document:identity", "document:permit"}),
        known_absent=NOTHING_YET - {"document:permit"},
    )
    before = build_plan(corpus.tasks, situation, today=today)
    later = build_plan(corpus.tasks, situation, today=today + timedelta(days=200))
    changes = diff_plans(before, later)
    assert "work.apply" in changes.newly_unblocked


def test_a_determination_arriving_unblocks_and_is_reported(
    corpus: Corpus, today: date
) -> None:
    situation = _with(
        held=frozenset({"document:identity", "document:permit"}),
        known_absent=NOTHING_YET - {"document:permit"},
    )
    before = build_plan(corpus.tasks, situation, today=today)
    after = build_plan(
        corpus.tasks,
        Situation.model_validate(
            situation.model_dump()
            | {
                "determinations": {
                    "determination:residence_test": DeterminationRecord(
                        outcome=DeterminationOutcome.GRANTED,
                        authority="the Fictional Benefits Office",
                        recorded_on=date(2026, 8, 14),
                    )
                }
            }
        ),
        today=today,
    )
    changes = diff_plans(before, after)
    assert changes.newly_unblocked == ("benefit.apply",)
