"""Turning a situation and a task corpus into a plan.

    1. select      tasks whose applies_when is not FALSE for this situation
    2. close       pull in prerequisite-producing tasks transitively
    3. resolve     link requires to produces across the selected set
    4. validate    assert acyclic. a cycle is a corpus bug and must fail loudly
    5. sort        topological, tie-broken by severity then waiting time
    6. partition   done / frontier / blocked / needs_info
    7. explain     minimal unblocking route and next actions per blocked task

No model is involved at any point, which is the part of the design worth
defending: ordering here is derived from structure, so it is the same every
time and it can be tested exactly.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable, Sequence
from datetime import date

from wayfinder.plan.critical_path import gated_wait, rank_frontier
from wayfinder.plan.errors import CycleError
from wayfinder.plan.models import Task
from wayfinder.plan.plan import ItemStatus, Plan, PlanItem
from wayfinder.plan.refs import TaskId
from wayfinder.plan.situation import Situation
from wayfinder.plan.truth import Truth
from wayfinder.plan.unblock import (
    DEFAULT_SEARCH_LIMIT,
    count_waiting_on,
    next_actions,
    solve_routes,
)


def build_plan(
    tasks: Sequence[Task],
    situation: Situation,
    *,
    today: date,
    search_limit: int = DEFAULT_SEARCH_LIMIT,
) -> Plan:
    """Build a plan. Pure: same inputs, same plan, no I/O, no clock read."""
    situation = _apply_completions(tasks, situation)
    included = _select_and_close(tasks, situation)
    edges = _resolve(included)
    order = _topological_order(included, edges)

    by_id = {t.id: t for t in included}
    items = tuple(
        _classify(by_id[task_id], situation, today=today) for task_id in order
    )

    blocked = tuple(i.task.id for i in items if i.status is ItemStatus.BLOCKED)
    routes = solve_routes(
        included, situation, today=today, targets=blocked, limit=search_limit
    )

    startable = frozenset(i.task.id for i in items if i.status is ItemStatus.FRONTIER)
    gated = gated_wait(included, order)
    frontier_tasks = [i.task for i in items if i.status is ItemStatus.FRONTIER]

    return Plan(
        built_on=today,
        items=items,
        frontier_order=rank_frontier(frontier_tasks, gated),
        unblocking_route={t: tuple(sorted(r.tasks)) for t, r in routes.items()},
        next_actions={t: next_actions(r, startable) for t, r in routes.items()},
        unroutable={t: r.unroutable for t, r in routes.items() if r.unroutable},
        gated_wait={t: gated[t] for t in startable},
        waiting_on=count_waiting_on(routes, startable),
    )


def _apply_completions(tasks: Sequence[Task], situation: Situation) -> Situation:
    """Completing a task means holding what it produces.

    `Situation` deliberately knows nothing about the corpus, so it cannot work
    out that finishing `permit.apply` is the same fact as holding the permit.
    The builder can, and it has to: otherwise somebody who reports what they
    have done gets a plan that does not move, which is the least forgivable
    thing this could do to a person keeping track of forty tasks.

    `tasks_completed` therefore means finished, with the output in hand. There
    is no in-progress state in v1. Adding one means modelling the gap between
    applying and receiving, which is a real thing in this domain and a larger
    change than it looks.

    Re-validating through the model rather than mutating in place is deliberate:
    a situation claiming both a completed task and the absence of what it
    produces is a contradiction, and it should surface here rather than becoming
    a quietly strange plan.
    """
    if not situation.tasks_completed:
        return situation
    produced = {
        artefact
        for task in tasks
        if task.id in situation.tasks_completed
        for artefact in task.produces
    }
    if produced <= situation.held:
        return situation
    return Situation.model_validate(
        situation.model_dump() | {"held": situation.held | produced}
    )


def _select_and_close(tasks: Sequence[Task], situation: Situation) -> tuple[Task, ...]:
    """Steps 1 and 2. A task whose applies_when is UNKNOWN stays in.

    Dropping an UNKNOWN task would silently decide the question the planner is
    supposed to ask about, so it stays and lands in `needs_info` instead.
    """
    by_id = {t.id: t for t in tasks}
    eligible = [t for t in tasks if t.applies(situation) is not Truth.FALSE]

    producers: dict[str, list[TaskId]] = {}
    for task in eligible:
        for artefact in task.yields:
            producers.setdefault(artefact, []).append(task.id)

    selected: dict[TaskId, Task] = {t.id: t for t in eligible}
    queue = list(selected)
    while queue:
        current = by_id[queue.pop()]
        for requirement in current.requires:
            for ref in requirement.any_of:
                for producer_id in producers.get(ref, ()):
                    if producer_id not in selected:
                        selected[producer_id] = by_id[producer_id]
                        queue.append(producer_id)

    return tuple(sorted(selected.values(), key=lambda t: t.id))


def _resolve(tasks: Sequence[Task]) -> dict[TaskId, set[TaskId]]:
    """Step 3. Edges run producer -> consumer."""
    produced_by: dict[str, list[TaskId]] = {}
    for task in tasks:
        for artefact in task.yields:
            produced_by.setdefault(artefact, []).append(task.id)

    edges: dict[TaskId, set[TaskId]] = {t.id: set() for t in tasks}
    for task in tasks:
        for requirement in task.requires:
            for ref in requirement.any_of:
                for producer in produced_by.get(ref, ()):
                    if producer != task.id:
                        edges[producer].add(task.id)
    return edges


def _topological_order(
    tasks: Sequence[Task], edges: dict[TaskId, set[TaskId]]
) -> tuple[TaskId, ...]:
    """Steps 4 and 5, with a stable tie-break.

    Ties are broken by severity, then by longer typical waits first, then by id.
    Starting the four-week task before the one-day task when nothing else
    separates them is free, and it is the difference between a plan that reads
    as considered and one that reads as arbitrary.

    Cycle detection here is deliberately conservative: a cycle that exists only
    through one branch of an alternative is still reported. In a hand-curated
    corpus that shape is far more likely to be a modelling error than a
    deliberate design, and a plan that sends somebody in a circle is the exact
    failure this validation exists to prevent.
    """
    by_id = {t.id: t for t in tasks}
    indegree = dict.fromkeys(by_id, 0)
    for targets in edges.values():
        for target in targets:
            indegree[target] += 1

    def sort_key(task_id: TaskId) -> tuple[int, float, str]:
        task = by_id[task_id]
        wait = task.typical_wait.total_seconds() if task.typical_wait else 0.0
        return (task.blocking_severity.rank, -wait, task_id)

    ready = [sort_key(t) for t, d in indegree.items() if d == 0]
    heapq.heapify(ready)

    order: list[TaskId] = []
    while ready:
        _, _, task_id = heapq.heappop(ready)
        order.append(task_id)
        for target in sorted(edges[task_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, sort_key(target))

    if len(order) != len(by_id):
        raise CycleError(_find_cycle(edges, set(order)))
    return tuple(order)


def _find_cycle(edges: dict[TaskId, set[TaskId]], settled: set[TaskId]) -> list[TaskId]:
    """Name the actual cycle, because a maintainer has to go and fix the corpus."""
    remaining = {k: v - settled for k, v in edges.items() if k not in settled}
    path: list[TaskId] = []
    on_path: set[TaskId] = set()
    seen: set[TaskId] = set()

    def walk(node: TaskId) -> list[TaskId] | None:
        path.append(node)
        on_path.add(node)
        seen.add(node)
        for target in sorted(remaining.get(node, ())):
            if target in on_path:
                return path[path.index(target) :]
            if target not in seen:
                found = walk(target)
                if found is not None:
                    return found
        path.pop()
        on_path.discard(node)
        return None

    for start in sorted(remaining):
        if start not in seen:
            found = walk(start)
            if found is not None:
                return found
    return sorted(remaining)


def _classify(task: Task, situation: Situation, *, today: date) -> PlanItem:
    """Step 6.

    A FALSE prerequisite outranks an UNKNOWN one: if we already know something
    is missing, saying so is more useful than asking a question whose answer
    cannot change the verdict.
    """
    if _already_done(task, situation):
        return PlanItem(task=task, status=ItemStatus.DONE)

    applicability = task.applies(situation)
    if applicability is Truth.UNKNOWN:
        return PlanItem(
            task=task,
            status=ItemStatus.NEEDS_INFO,
            unknowns=task.applies_when.unknowns(situation),
        )

    verdicts = [(p, p.satisfied(situation, today=today)) for p in task.requires]
    unmet = tuple(p for p, v in verdicts if v is Truth.FALSE)
    unresolved = tuple(p for p, v in verdicts if v is Truth.UNKNOWN)

    if unmet:
        # Blocked, but still report what is undecided. A task held up by both a
        # missing document and a determination is a different sentence from one
        # held up by the document alone.
        return PlanItem(
            task=task,
            status=ItemStatus.BLOCKED,
            unmet=unmet,
            unresolved=unresolved,
        )

    unknown = _union(p.unknowns(situation, today=today) for p in unresolved)
    if unknown:
        return PlanItem(
            task=task,
            status=ItemStatus.NEEDS_INFO,
            unresolved=unresolved,
            unknowns=unknown,
        )

    # Nothing is FALSE and every UNKNOWN is one nobody can resolve by answering
    # a question, which means a determination or a waiting period. The task is
    # blocked on something outside the person's control rather than startable.
    if unresolved:
        return PlanItem(task=task, status=ItemStatus.BLOCKED, unresolved=unresolved)

    return PlanItem(task=task, status=ItemStatus.FRONTIER)


def _already_done(task: Task, situation: Situation) -> bool:
    """Completed, or every artefact it exists to produce is already in hand.

    The second clause matters because "I already have a PPS number" and "I have
    done the PPSN task" are the same fact stated two ways, and a plan that lists
    both would look careless to the one person who most needs to trust it.
    """
    if task.id in situation.tasks_completed:
        return True
    return bool(task.produces) and all(
        situation.holds(ref) is Truth.TRUE for ref in task.produces
    )


def _union(sets: Iterable[frozenset[str]]) -> frozenset[str]:
    out: set[str] = set()
    for s in sets:
        out |= s
    return frozenset(out)
