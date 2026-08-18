"""The plan engine's share of ADR-0004, asserted rather than described.

The full structural claim lives in the graph topology test, which is M4. What
can be proved at this layer is narrower and still worth pinning down: the
planner has no way to satisfy a determination by itself, no way to invite
somebody else to supply one, and no way to let a corpus author imply otherwise.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest
from pydantic import ValidationError

from tests.personas.cases import NOTHING_YET
from wayfinder.corpus.models import Artefact, Corpus
from wayfinder.plan import builder, unblock
from wayfinder.plan import plan as plan_module
from wayfinder.plan.builder import build_plan
from wayfinder.plan.models import Domain, Prerequisite, Severity, SourceSpan, Task
from wayfinder.plan.plan import ItemStatus
from wayfinder.plan.refs import ArtefactKind, artefact_kind
from wayfinder.plan.situation import (
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)
from wayfinder.plan.truth import Truth


def _situation(**kwargs: object) -> Situation:
    base: dict[str, object] = {
        "arrival_date": date(2026, 8, 3),
        "protection_stage": ProtectionStage.APPLIED,
        "household": Household(adults=1, children_ages=()),
        "known_absent": NOTHING_YET,
    }
    base.update(kwargs)
    return Situation.model_validate(base)


def test_a_task_cannot_claim_to_produce_a_determination() -> None:
    """FR-S9 at the corpus layer.

    Without this, a contributor could write a task that marks a legal
    determination satisfied by somebody filling in a form.
    """
    with pytest.raises(ValidationError, match="Determinations are made by authorities"):
        Task(
            id="bad.task",
            title="Decide a legal question",
            domain=Domain.INCOME,
            why="Fixture.",
            produces=("determination:anything",),
            blocking_severity=Severity.ROUTINE,
            where=(SourceSpan(source_id="s", span="x"),),
        )


def test_a_determination_cannot_be_recorded_without_naming_who_decided() -> None:
    with pytest.raises(ValidationError):
        DeterminationRecord(
            outcome=DeterminationOutcome.GRANTED,
            authority="",
            recorded_on=date(2026, 8, 1),
        )


def test_a_determination_artefact_must_name_its_authority() -> None:
    """The output has to be able to say who decides. That sentence needs the name."""
    with pytest.raises(ValidationError, match="must name `decided_by`"):
        Artefact(ref="determination:something", title="something")


def test_only_determinations_carry_a_decider() -> None:
    with pytest.raises(ValidationError, match="does not apply"):
        Artefact(ref="document:thing", title="a thing", decided_by="Somebody")


def test_a_determination_is_never_offered_as_an_intake_question(
    corpus: Corpus, today: date
) -> None:
    """The question "do you satisfy the residence test?" must never be asked.

    Listing an undecided determination as an open question would invite an
    answer from the person, or later from a model, standing in for a decision
    only an authority can make.
    """
    plan = build_plan(corpus.tasks, _situation(), today=today)
    # Open questions are either a situation field name or an artefact reference.
    for question in plan.open_questions:
        if ":" not in question:
            continue
        assert artefact_kind(question) is not ArtefactKind.DETERMINATION, question


def test_an_undecided_determination_blocks_rather_than_asks(
    corpus: Corpus, today: date
) -> None:
    plan = build_plan(
        corpus.tasks,
        _situation(
            held=frozenset({"document:identity", "document:permit"}),
            known_absent=NOTHING_YET - {"document:permit"},
        ),
        today=today,
    )
    item = plan.item("benefit.apply")
    assert item is not None
    assert item.status is ItemStatus.BLOCKED
    assert item.determination_refs == ("determination:residence_test",)


def test_a_determination_blocker_is_named_with_no_route_offered(
    corpus: Corpus, today: date
) -> None:
    """Named, and explicitly not routed. Nothing the person does clears it."""
    plan = build_plan(corpus.tasks, _situation(), today=today)
    assert plan.unroutable["benefit.apply"] == ("determination:residence_test",)
    assert "benefit.apply" not in {
        t for route in plan.unblocking_route.values() for t in route
    }


def test_the_planner_never_writes_a_determination(corpus: Corpus, today: date) -> None:
    """A structural check rather than a behavioural one.

    No module in the plan engine constructs a `DeterminationRecord`. If one ever
    does, the engine has grown the ability to decide something that is not its
    to decide, and this fails before anybody has to notice it in output.
    """
    for module in (builder, unblock, plan_module):
        source = inspect.getsource(module)
        assert "DeterminationRecord(" not in source, module.__name__


def test_a_granted_determination_is_the_only_way_through(
    corpus: Corpus, today: date
) -> None:
    held = frozenset({"document:identity", "document:permit"})
    absent = NOTHING_YET - {"document:permit"}

    without = build_plan(
        corpus.tasks, _situation(held=held, known_absent=absent), today=today
    )
    assert without.ids([ItemStatus.FRONTIER]).isdisjoint({"benefit.apply"})

    with_record = build_plan(
        corpus.tasks,
        _situation(
            held=held,
            known_absent=absent,
            determinations={
                "determination:residence_test": DeterminationRecord(
                    outcome=DeterminationOutcome.GRANTED,
                    authority="the Fictional Benefits Office",
                    recorded_on=date(2026, 8, 14),
                )
            },
        ),
        today=today,
    )
    assert "benefit.apply" in with_record.ids([ItemStatus.FRONTIER])


def test_a_refused_determination_is_a_block_and_not_a_question() -> None:
    situation = Situation(
        determinations={
            "determination:thing": DeterminationRecord(
                outcome=DeterminationOutcome.REFUSED,
                authority="An Authority",
                recorded_on=date(2026, 8, 1),
            )
        }
    )
    requirement = Prerequisite(any_of=("determination:thing",))
    assert requirement.satisfied(situation, today=date(2026, 8, 17)) is Truth.FALSE
    assert requirement.unknowns(situation, today=date(2026, 8, 17)) == frozenset()


def test_determinations_cannot_be_smuggled_into_the_held_sets() -> None:
    """The only door into `determinations` is a record naming an authority."""
    with pytest.raises(ValidationError, match="may only contain"):
        Situation(held=frozenset({"determination:thing"}))
    with pytest.raises(ValidationError, match="may only contain"):
        Situation(known_absent=frozenset({"determination:thing"}))


def test_a_thing_cannot_be_both_held_and_absent() -> None:
    with pytest.raises(ValidationError, match="both held and known absent"):
        Situation(
            held=frozenset({"document:x"}), known_absent=frozenset({"document:x"})
        )
