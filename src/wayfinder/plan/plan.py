"""The plan itself: four partitions, an ordering, and the reasons.

The list of tasks is not the useful output. What people need is which of these
can be started today, which cannot, and exactly what unblocks the ones that
cannot. `needs_info` is the fourth partition the original design did not have:
a task we cannot place at all until somebody tells us one more fact, which is
different from a task we know is blocked.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from wayfinder.plan.models import Prerequisite, Task
from wayfinder.plan.refs import ArtefactKind, TaskId, artefact_kind


class ItemStatus(Enum):
    DONE = "done"
    FRONTIER = "frontier"
    BLOCKED = "blocked"
    NEEDS_INFO = "needs_info"


class PlanItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task: Task
    status: ItemStatus

    # Requirements we know are not met. These decide that a task is blocked.
    unmet: tuple[Prerequisite, ...] = ()

    # Requirements we cannot yet decide either way. A blocked task can still
    # carry these, and they matter: a payment blocked on a missing document and
    # also gated by a determination needs both facts said out loud, or the
    # person plans around a decision nobody has made.
    unresolved: tuple[Prerequisite, ...] = ()

    unknowns: frozenset[str] = frozenset()

    @property
    def outstanding(self) -> tuple[Prerequisite, ...]:
        return (*self.unmet, *self.unresolved)

    @property
    def blocked_by_determination(self) -> bool:
        """Whether an authority, and not the person, owns every remaining blocker."""
        outstanding = self.outstanding
        return bool(outstanding) and all(
            p.blocked_on_determination for p in outstanding
        )

    @property
    def determination_refs(self) -> tuple[str, ...]:
        """Every determination standing between this task and being startable."""
        return tuple(
            sorted(
                {
                    ref
                    for requirement in self.outstanding
                    for ref in requirement.any_of
                    if artefact_kind(ref) is ArtefactKind.DETERMINATION
                }
            )
        )


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    built_on: date
    items: tuple[PlanItem, ...]

    # Frontier task ids ordered by how much calendar time they gate. This is a
    # different ordering from `items`, which is topological. Topological order
    # says what is *valid*; this says what to do first.
    frontier_order: tuple[TaskId, ...] = ()

    # For each blocked task: everything that must happen, and the subset of that
    # which can be started right now.
    unblocking_route: Mapping[TaskId, tuple[TaskId, ...]] = {}
    next_actions: Mapping[TaskId, tuple[TaskId, ...]] = {}

    # Artefacts on the route that no task in the corpus can produce: a
    # determination somebody else decides, or a waiting period. Naming these is
    # the difference between "there is no route" and "here is the route, and
    # here is the part that is not yours to do".
    unroutable: Mapping[TaskId, tuple[str, ...]] = {}

    # Longest downstream waiting time gated by each frontier task.
    gated_wait: Mapping[TaskId, timedelta] = {}

    # How many blocked tasks each frontier task appears in the route for. This
    # is the "four other things are waiting on it" line, computed here rather
    # than in whatever renders the plan, so the claim can be tested.
    waiting_on: Mapping[TaskId, int] = {}

    def of_status(self, status: ItemStatus) -> tuple[PlanItem, ...]:
        return tuple(i for i in self.items if i.status is status)

    @model_validator(mode="after")
    def _frontier_order_covers_the_frontier(self) -> Plan:
        """The ranking must name every startable task, exactly once.

        Falling back to unranked order when the two disagree would hide a
        builder bug behind a plan that still looks reasonable, and the thing it
        would hide is somebody being told to do the wrong task first. Everything
        else in this engine fails loudly on inconsistent data and so does this.
        """
        startable = {i.task.id for i in self.items if i.status is ItemStatus.FRONTIER}
        ranked = self.frontier_order
        if len(set(ranked)) != len(ranked):
            msg = f"frontier_order repeats a task: {ranked}"
            raise ValueError(msg)
        if set(ranked) != startable:
            missing = sorted(startable - set(ranked))
            extra = sorted(set(ranked) - startable)
            msg = (
                f"frontier_order does not match the frontier. "
                f"missing {missing}, unexpected {extra}"
            )
            raise ValueError(msg)
        return self

    @property
    def frontier(self) -> tuple[PlanItem, ...]:
        by_id = {i.task.id: i for i in self.items}
        return tuple(by_id[t] for t in self.frontier_order)

    @property
    def blocked(self) -> tuple[PlanItem, ...]:
        return self.of_status(ItemStatus.BLOCKED)

    @property
    def done(self) -> tuple[PlanItem, ...]:
        return self.of_status(ItemStatus.DONE)

    @property
    def needs_info(self) -> tuple[PlanItem, ...]:
        return self.of_status(ItemStatus.NEEDS_INFO)

    @property
    def open_questions(self) -> frozenset[str]:
        """Every fact which, if answered, could move a task out of `needs_info`.

        This is the candidate set intake draws from. It is already pruned to
        facts that matter, because a decided condition contributes nothing.
        """
        return frozenset().union(*(i.unknowns for i in self.items), frozenset())

    def item(self, task_id: str) -> PlanItem | None:
        for i in self.items:
            if i.task.id == task_id:
                return i
        return None

    def ids(self, statuses: Sequence[ItemStatus] | None = None) -> frozenset[TaskId]:
        wanted = set(statuses) if statuses is not None else set(ItemStatus)
        return frozenset(i.task.id for i in self.items if i.status in wanted)
