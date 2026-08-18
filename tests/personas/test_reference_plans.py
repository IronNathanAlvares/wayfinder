"""Every reference persona, asserted exactly.

Exactly, not approximately. A test that asserts a frontier *contains* the right
task passes when the ordering is wrong, and the ordering is the part of this
engine worth having.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.personas.cases import PERSONAS, Persona
from wayfinder.corpus.models import Corpus
from wayfinder.plan.builder import build_plan
from wayfinder.plan.plan import ItemStatus


@pytest.fixture(params=PERSONAS, ids=lambda p: p.name)
def persona(request: pytest.FixtureRequest) -> Persona:
    result: Persona = request.param
    return result


def test_frontier_is_exact_and_ordered(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    assert plan.frontier_order == persona.frontier, persona.pins_down


def test_partitions_are_exact(persona: Persona, corpus: Corpus, today: date) -> None:
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    assert plan.ids([ItemStatus.BLOCKED]) == persona.blocked, persona.pins_down
    assert plan.ids([ItemStatus.NEEDS_INFO]) == persona.needs_info, persona.pins_down
    assert plan.ids([ItemStatus.DONE]) == persona.done, persona.pins_down


def test_inapplicable_tasks_are_absent(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    """A task whose applies_when is FALSE is not in the plan at all.

    Not present and marked skipped: absent. A person reading a plan should not
    be shown forty things that do not apply to them.
    """
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    present = plan.ids()
    assert present.isdisjoint(persona.absent), persona.pins_down
    all_ids = {t.id for t in corpus.tasks}
    assert present | persona.absent == all_ids


def test_partitions_cover_the_plan_exactly_once(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    counted = (
        len(plan.frontier) + len(plan.blocked) + len(plan.done) + len(plan.needs_info)
    )
    assert counted == len(plan.items)


def test_declared_routes_are_exact(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    for task_id, expected in persona.routes.items():
        assert plan.unblocking_route[task_id] == expected, (
            f"{persona.name}: route for {task_id} is not the minimal one"
        )


def test_declared_unroutable_blockers_are_exact(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    for task_id, expected in persona.unroutable.items():
        assert plan.unroutable.get(task_id, ()) == expected, (
            f"{persona.name}: {task_id} should be gated by exactly {expected}"
        )


def test_open_questions_are_exact_where_declared(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    if persona.open_questions is None:
        return
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    assert plan.open_questions == persona.open_questions, persona.pins_down


def test_next_actions_are_a_subset_of_the_frontier(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    """Telling somebody to start a task they cannot start would be worse than silence."""
    plan = build_plan(corpus.tasks, persona.situation, today=today)
    startable = set(plan.frontier_order)
    for task_id, actions in plan.next_actions.items():
        assert set(actions) <= startable, task_id


def test_building_twice_gives_the_same_plan(
    persona: Persona, corpus: Corpus, today: date
) -> None:
    """The engine is pure, so this is the cheapest possible check that it stays so."""
    first = build_plan(corpus.tasks, persona.situation, today=today)
    second = build_plan(corpus.tasks, persona.situation, today=today)
    assert first == second
