"""Which frontier task to start first, computed rather than asserted.

The design said to rank by how many blocked tasks a frontier task unblocks,
weighted somehow by severity and waiting time. Left there, the headline claim of
the demo would rest on invented weights.

The metric here is the longest downstream waiting time a task gates: a standard
longest-path computation over the dependency DAG with `typical_wait` as the
node weight. That is what "this one costs the most calendar time if you leave
it" actually means, and it agrees with the worked example in the design, which
says a task unblocking two things over four weeks should beat one unblocking
three things in a day. A count of descendants does not agree with that; the
longest path does.

A language model has no reliable way to work this out from prose, which is the
argument for computing the plan rather than generating it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta

from wayfinder.plan.models import Task
from wayfinder.plan.refs import TaskId

ZERO = timedelta(0)


def gated_wait(
    tasks: Sequence[Task], order: Sequence[TaskId]
) -> dict[TaskId, timedelta]:
    """Longest chain of waiting time starting at each task, inclusive of its own.

    `order` must be a topological ordering of `tasks`, which the builder has
    already computed and validated.
    """
    by_id = {t.id: t for t in tasks}
    dependents: dict[TaskId, list[TaskId]] = {t.id: [] for t in tasks}

    produced_by: dict[str, list[TaskId]] = {}
    for task in tasks:
        for artefact in task.yields:
            produced_by.setdefault(artefact, []).append(task.id)

    for task in tasks:
        upstream: set[TaskId] = set()
        for requirement in task.requires:
            for ref in requirement.any_of:
                upstream.update(produced_by.get(ref, ()))
        for producer in upstream:
            if producer != task.id:
                dependents[producer].append(task.id)

    longest: dict[TaskId, timedelta] = {}
    # Reverse topological order guarantees dependents are solved first.
    for task_id in reversed(list(order)):
        own = by_id[task_id].typical_wait or ZERO
        downstream = [longest.get(d, ZERO) for d in dependents.get(task_id, ())]
        longest[task_id] = own + (max(downstream) if downstream else ZERO)
    return longest


def rank_frontier(
    frontier: Sequence[Task],
    gated: Mapping[TaskId, timedelta],
) -> tuple[TaskId, ...]:
    """Frontier order: severity band first, then gated calendar time within it.

    Ranking on gated time alone puts a ten-day language class above a seven-day
    application for the card somebody needs to see a doctor. Both gate the same
    amount of downstream work, which is none, so the computation has nothing to
    say and the ordering falls to an accident of duration.

    Severity is an editorial judgement about what it costs to be blocked, and
    gated time is computed. Using the judgement as the coarse band and the
    computation as the ordering inside it keeps the two separable, and avoids
    the invented numeric weights that combining them would need.
    """
    return tuple(
        task.id
        for task in sorted(
            frontier,
            key=lambda t: (
                t.blocking_severity.rank,
                -gated.get(t.id, ZERO).total_seconds(),
                t.id,
            ),
        )
    )
