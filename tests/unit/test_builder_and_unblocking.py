"""Ordering, cycles, and the minimality claim.

The minimality tests are the ones that matter. A superset of the right answer is
technically correct and practically useless: "here are nine things you must do"
when three would have done it is not advice somebody with no money and no time
can act on.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from tests.personas.cases import NOTHING_YET
from wayfinder.corpus.loader import load_corpus
from wayfinder.corpus.models import Corpus
from wayfinder.plan.builder import build_plan
from wayfinder.plan.critical_path import gated_wait
from wayfinder.plan.errors import CycleError, SearchExhaustedError
from wayfinder.plan.models import Severity
from wayfinder.plan.plan import ItemStatus
from wayfinder.plan.situation import (
    Accommodation,
    Household,
    ProtectionStage,
    Situation,
)
from wayfinder.plan.unblock import solve_routes

SHELTER = Situation(
    arrival_date=date(2026, 8, 3),
    protection_stage=ProtectionStage.APPLIED,
    accommodation=Accommodation.EMERGENCY,
    household=Household(adults=1, children_ages=(7,)),
    held=frozenset({"document:identity"}),
    known_absent=NOTHING_YET,
)


def test_a_cycle_fails_loudly_and_names_itself(today: date) -> None:
    """A cycle is a corpus bug. Silently breaking it produces a plan that looks
    fine and sends somebody round in a circle."""
    broken = load_corpus(FIXTURES / "cycle_corpus", today=today)
    with pytest.raises(CycleError) as caught:
        build_plan(broken.tasks, Situation(), today=today)
    assert set(caught.value.cycle) == {"egg.get", "chicken.get"}


def test_ordering_respects_every_prerequisite(corpus: Corpus, today: date) -> None:
    """The invariant the whole engine exists for. A violation is a bug, not a
    tuning question."""
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    position = {item.task.id: i for i, item in enumerate(plan.items)}
    produced_by = {
        artefact: item.task.id for item in plan.items for artefact in item.task.yields
    }
    for item in plan.items:
        for requirement in item.task.requires:
            for ref in requirement.any_of:
                producer = produced_by.get(ref)
                if producer is not None and producer != item.task.id:
                    assert position[producer] < position[item.task.id], (
                        f"{producer} must be ordered before {item.task.id}"
                    )


def test_the_minimal_route_takes_the_shorter_branch(
    corpus: Corpus, today: date
) -> None:
    """The headline minimality assertion.

    `permit.apply` accepts either a shelter letter or a formal address proof.
    The address proof route needs two tasks, the shelter letter needs one. A
    greedy walk of ancestors reports both. The exact search reports one.
    """
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    assert plan.unblocking_route["permit.apply"] == ("shelter.letter_request",)


def test_the_minimal_route_is_smaller_than_the_ancestor_closure(
    corpus: Corpus, today: date
) -> None:
    """Stated as a comparison so the test fails if minimisation is ever removed."""
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    ancestors = {"shelter.letter_request", "address.evidence"}
    route = set(plan.unblocking_route["permit.apply"])
    assert route < ancestors


def test_a_route_is_sufficient_as_well_as_minimal(corpus: Corpus, today: date) -> None:
    """Minimal and wrong would be worse than not minimal.

    Completing the reported route, and nothing else, must actually leave the
    target startable.
    """
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    by_id = {t.id: t for t in corpus.tasks}
    for target, route in plan.unblocking_route.items():
        if plan.unroutable.get(target):
            continue
        produced = {a for t in route for a in by_id[t].produces}
        after = build_plan(
            corpus.tasks,
            SHELTER.model_validate(
                SHELTER.model_dump()
                | {
                    "tasks_completed": frozenset(route),
                    # What the route produces is now held, so it stops being
                    # known-absent. Everything else stays as it was, or the
                    # test would be checking a different situation.
                    "known_absent": SHELTER.known_absent - produced,
                }
            ),
            today=today,
        )
        item = after.item(target)
        assert item is not None
        assert item.status is ItemStatus.FRONTIER, (
            f"{target} was still {item.status.value} after doing {route}"
        )


def test_next_actions_are_the_startable_part_of_the_route(
    corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    assert plan.next_actions["bank.open"] == ("shelter.letter_request",)
    assert set(plan.unblocking_route["bank.open"]) == {
        "shelter.letter_request",
        "address.evidence",
        "permit.apply",
    }


def test_the_search_bound_raises_rather_than_guessing(
    corpus: Corpus, today: date
) -> None:
    """Breaching the bound must not silently return a possibly non-minimal answer."""
    with pytest.raises(SearchExhaustedError):
        solve_routes(
            corpus.tasks,
            SHELTER,
            today=today,
            targets=["bank.open"],
            limit=2,
        )


def test_gated_wait_is_the_longest_downstream_chain(
    corpus: Corpus, today: date
) -> None:
    """Not a count of descendants. Calendar time is what costs people weeks."""
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    # shelter letter 2d -> address proof 3d -> permit 28d -> benefit 30d
    assert plan.gated_wait["shelter.letter_request"] == timedelta(days=63)
    assert plan.gated_wait["clinic.register"] == timedelta(0)


def test_gated_wait_of_a_leaf_is_its_own_wait(corpus: Corpus, today: date) -> None:
    order = tuple(t.id for t in corpus.tasks)
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    gated = gated_wait([i.task for i in plan.items], [i.task.id for i in plan.items])
    assert gated["language.enrol"] == timedelta(days=10)
    assert set(order) >= set(gated)


def test_frontier_is_banded_by_severity_before_time(
    corpus: Corpus, today: date
) -> None:
    """Severity is the editorial judgement; gated time orders within it."""
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    severities = [
        next(i.task.blocking_severity for i in plan.items if i.task.id == task_id)
        for task_id in plan.frontier_order
    ]
    ranks = [s.rank for s in severities]
    assert ranks == sorted(ranks)
    assert Severity.CRITICAL.rank < Severity.ROUTINE.rank


def test_a_task_needing_nothing_is_startable_immediately(
    corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    assert "clinic.register" in plan.frontier_order


def test_an_inapplicable_task_is_absent_rather_than_marked(
    corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    assert plan.item("tenancy.obtain") is None


def test_elapsed_prerequisites_clear_on_their_own(corpus: Corpus, today: date) -> None:
    ready = SHELTER.model_copy(
        update={
            "arrival_date": date(2025, 1, 6),
            "held": frozenset({"document:identity", "document:permit"}),
            "known_absent": NOTHING_YET - {"document:permit"},
        }
    )
    plan = build_plan(corpus.tasks, ready, today=today)
    assert "work.apply" in plan.frontier_order


def test_an_unfinished_waiting_period_blocks_without_a_route(
    corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, SHELTER, today=today)
    assert plan.unroutable["work.apply"] == ("elapsed:arrival_date",)


def test_the_plan_is_stable_under_input_order(corpus: Corpus, today: date) -> None:
    """Corpus file ordering must not change anybody's plan."""
    forward = build_plan(corpus.tasks, SHELTER, today=today)
    backward = build_plan(tuple(reversed(corpus.tasks)), SHELTER, today=today)
    assert forward == backward


def test_the_engine_does_no_io(
    corpus: Corpus, today: date, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A behavioural echo of the import-linter contract.

    The contract checks imports; this checks the thing the contract is for, so
    the guarantee does not rest on one mechanism alone.
    """
    real_open = Path.open

    def fail(*args: object, **kwargs: object) -> object:
        msg = "the plan engine opened a file"
        raise AssertionError(msg)

    monkeypatch.setattr(Path, "open", fail)
    build_plan(corpus.tasks, SHELTER, today=today)
    monkeypatch.setattr(Path, "open", real_open)
