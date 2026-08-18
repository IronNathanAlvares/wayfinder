"""The minimal unblocking set, and the next actions drawn from it.

The design originally gave this as

    unblock(t) = { u in frontier : u is an ancestor of t }

which is the set of *all* frontier ancestors. That is precisely the
non-minimal superset the same section rejects, and it is also incomplete:
completing the frontier ancestors does not unblock `t`, because the
intermediate tasks between them and `t` still have to happen.

There are two distinct outputs and this module produces both.

`unblocking_route(t)` is the smallest set of tasks, at any status, whose
completion makes `t` startable, minimised over alternative routes.
`next_actions(t)` is the part of that route which can be started today, and it
is the sentence a person actually reads.

On minimality. Requirements form an AND of ORs, so this is minimum-cost solving
over an AND/OR graph, which is NP-hard in general. The search here is exact
rather than greedy: it keeps every Pareto-minimal candidate route and picks the
smallest, because a greedy choice per alternative is not globally optimal when
two alternatives share a sub-task. That is affordable because the corpus is
small and alternatives are shallow. A hard bound guards the assumption, and
breaching it raises rather than quietly returning a possibly non-minimal answer.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import NamedTuple

from wayfinder.plan.errors import SearchExhaustedError
from wayfinder.plan.models import Task
from wayfinder.plan.refs import ArtefactKind, TaskId, artefact_kind
from wayfinder.plan.situation import Situation
from wayfinder.plan.truth import Truth

# Guards the assumption that alternatives stay shallow. Breaching it is a signal
# that the corpus grew a shape the exact search was not sized for.
DEFAULT_SEARCH_LIMIT = 50_000

RouteSet = frozenset[TaskId]


def _prune(candidates: Iterable[RouteSet]) -> list[RouteSet]:
    """Drop any candidate that is a superset of another. Order is not significant."""
    unique = set(candidates)
    minimal: list[RouteSet] = []
    for candidate in sorted(unique, key=lambda s: (len(s), sorted(s))):
        if not any(existing <= candidate for existing in minimal):
            minimal.append(candidate)
    return minimal


class Route(NamedTuple):
    """What has to happen for a target, and what nothing can make happen.

    A route is reported even when it cannot complete the task. Somebody blocked
    on a determination still needs to know which of the other prerequisites they
    can be getting on with, and telling them "there is no route" when three of
    the four steps are available would be both wrong and demoralising.
    """

    tasks: RouteSet
    unroutable: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Whether finishing `tasks` is enough on its own."""
        return not self.unroutable


class _RouteSolver:
    def __init__(
        self,
        tasks: Sequence[Task],
        situation: Situation,
        *,
        today: date,
        limit: int,
    ) -> None:
        self._by_id = {t.id: t for t in tasks}
        self._situation = situation
        self._today = today
        self._limit = limit
        self._states = 0
        self._memo: dict[TaskId, list[RouteSet]] = {}
        self._own_unroutable: dict[TaskId, frozenset[str]] = {}
        self._visiting: set[TaskId] = set()

        producers: dict[str, list[TaskId]] = {}
        for task in tasks:
            for artefact in task.yields:
                producers.setdefault(artefact, []).append(task.id)
        self._producers = producers

    def _charge(self, target: str) -> None:
        self._states += 1
        if self._states > self._limit:
            raise SearchExhaustedError(target, self._limit)

    def routes_for_task(self, task_id: TaskId) -> list[RouteSet]:
        """Every Pareto-minimal set of tasks whose completion leaves `task_id` startable.

        Each returned set includes `task_id` itself.
        """
        if task_id in self._memo:
            return self._memo[task_id]
        if task_id in self._visiting:
            # The builder validates acyclicity before this runs, so reaching here
            # means an alternative route re-entered a task mid-solve.
            msg = f"unexpected recursion through {task_id!r} while solving routes"
            raise RuntimeError(msg)

        self._charge(task_id)
        task = self._by_id[task_id]

        if task_id in self._situation.tasks_completed:
            self._memo[task_id] = [frozenset()]
            return self._memo[task_id]

        self._visiting.add(task_id)
        try:
            per_requirement: list[list[RouteSet]] = []
            unroutable: set[str] = set()
            for requirement in task.requires:
                options, blocked = self._routes_for_requirement(
                    requirement.any_of, task_id
                )
                unroutable.update(blocked)
                per_requirement.append(options)
            self._own_unroutable[task_id] = frozenset(unroutable)

            base: RouteSet = frozenset({task_id})
            if not per_requirement:
                self._memo[task_id] = [base]
                return self._memo[task_id]

            combined: list[RouteSet] = []
            for combination in itertools.product(*per_requirement):
                self._charge(task_id)
                union: RouteSet = base.union(*combination)
                combined.append(union)
            self._memo[task_id] = _prune(combined)
            return self._memo[task_id]
        finally:
            self._visiting.discard(task_id)

    def _routes_for_requirement(
        self, any_of: Sequence[str], target: TaskId
    ) -> tuple[list[RouteSet], tuple[str, ...]]:
        """Routes through one requirement, and the refs no task can ever satisfy.

        An option already held costs nothing. An option that is UNKNOWN still
        gets routed, because planning around a fact we have not confirmed would
        be assuming it.

        When nothing is routable the requirement contributes the empty route and
        names what is in the way, so the rest of the task can still be planned
        around it.
        """
        candidates: list[RouteSet] = []
        unroutable: list[str] = []
        for ref in any_of:
            kind = artefact_kind(ref)
            if kind in {ArtefactKind.ELAPSED, ArtefactKind.DETERMINATION}:
                # Nobody can do a task that makes time pass or that makes an
                # authority decide. These are named in the output, never routed.
                unroutable.append(ref)
                continue
            if self._situation.holds(ref) is Truth.TRUE:
                return ([frozenset()], ())
            producers = self._producers.get(ref, ())
            if not producers:
                unroutable.append(ref)
                continue
            for producer in producers:
                self._charge(target)
                candidates.extend(self.routes_for_task(producer))
        if candidates:
            return (_prune(candidates), ())
        return ([frozenset()], tuple(unroutable))

    def own_unroutable(self, task_id: TaskId) -> frozenset[str]:
        return self._own_unroutable.get(task_id, frozenset())


def solve_routes(
    tasks: Sequence[Task],
    situation: Situation,
    *,
    today: date,
    targets: Iterable[TaskId],
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> dict[TaskId, Route]:
    """Minimal unblocking route per target, with whatever nothing can clear named.

    The returned task set excludes the target itself and anything already
    completed, so it reads as "these are the things that have to happen".
    """
    solver = _RouteSolver(tasks, situation, today=today, limit=limit)
    out: dict[TaskId, Route] = {}
    for target in targets:
        routes = solver.routes_for_task(target)
        best = min(routes, key=lambda s: (len(s), sorted(s))) if routes else frozenset()
        chain = frozenset(best) - {target} - situation.tasks_completed
        unroutable = solver.own_unroutable(target).union(
            *(solver.own_unroutable(u) for u in chain), frozenset()
        )
        out[target] = Route(tasks=chain, unroutable=tuple(sorted(unroutable)))
    return out


def next_actions(route: Route, startable: frozenset[TaskId]) -> tuple[TaskId, ...]:
    """The part of a route that can be started today, in a stable order."""
    return tuple(sorted(route.tasks & startable))


def rank_by_gating(
    routes: Mapping[TaskId, Route], frontier: Iterable[TaskId]
) -> dict[TaskId, int]:
    """How many blocked tasks each frontier task appears in the route for.

    A count, not the ordering. Calendar time is what actually costs people
    weeks, so `critical_path` ranks on that instead and this is used for the
    explanatory line: "four other things are waiting on it".
    """
    counts = dict.fromkeys(frontier, 0)
    for route in routes.values():
        for task_id in route.tasks:
            if task_id in counts:
                counts[task_id] += 1
    return counts
