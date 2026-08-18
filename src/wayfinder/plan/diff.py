"""Replanning as a diff, because the diff is the output.

Somebody six months in does not want their forty-item list again. What changed
is the answer, and newly unblocked leads because it is the good news.

`no_longer_applicable` needs care at the point of wording. A task disappearing
can read as something being taken away, so this module reports it as its own
category rather than letting it vanish, and leaves the phrasing to whatever
renders it.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from wayfinder.plan.plan import ItemStatus, Plan
from wayfinder.plan.refs import TaskId


class BlockerChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: TaskId
    was: tuple[str, ...]
    now: tuple[str, ...]


class PlanDiff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    newly_unblocked: tuple[TaskId, ...] = ()
    newly_applicable: tuple[TaskId, ...] = ()
    no_longer_applicable: tuple[TaskId, ...] = ()
    newly_done: tuple[TaskId, ...] = ()
    newly_blocked: tuple[TaskId, ...] = ()
    still_blocked: tuple[TaskId, ...] = ()
    blocker_changed: tuple[BlockerChange, ...] = ()
    answered: tuple[TaskId, ...] = ()

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.newly_unblocked,
                self.newly_applicable,
                self.no_longer_applicable,
                self.newly_done,
                self.newly_blocked,
                self.blocker_changed,
                self.answered,
            )
        )


def _statuses(plan: Plan) -> Mapping[TaskId, ItemStatus]:
    return {item.task.id: item.status for item in plan.items}


def _blockers(plan: Plan) -> Mapping[TaskId, tuple[str, ...]]:
    return {
        item.task.id: tuple(sorted(" or ".join(p.any_of) for p in item.unmet))
        for item in plan.items
        if item.status is ItemStatus.BLOCKED
    }


def diff_plans(previous: Plan, current: Plan) -> PlanDiff:
    """What changed between two plans for the same person."""
    before, after = _statuses(previous), _statuses(current)
    before_blockers, after_blockers = _blockers(previous), _blockers(current)

    gone = tuple(sorted(set(before) - set(after)))
    appeared = tuple(sorted(set(after) - set(before)))
    shared = set(before) & set(after)

    newly_unblocked = tuple(
        sorted(
            t
            for t in shared
            if before[t] in {ItemStatus.BLOCKED, ItemStatus.NEEDS_INFO}
            and after[t] is ItemStatus.FRONTIER
        )
    )
    newly_blocked = tuple(
        sorted(
            t
            for t in shared
            if before[t] is not ItemStatus.BLOCKED and after[t] is ItemStatus.BLOCKED
        )
    )
    newly_done = tuple(
        sorted(
            t
            for t in shared
            if before[t] is not ItemStatus.DONE and after[t] is ItemStatus.DONE
        )
    )
    # A task that left needs_info has had its open question answered, whichever
    # partition it landed in. Worth reporting separately from being unblocked.
    answered = tuple(
        sorted(
            t
            for t in shared
            if before[t] is ItemStatus.NEEDS_INFO
            and after[t] is not ItemStatus.NEEDS_INFO
        )
    )
    still_blocked = tuple(
        sorted(
            t
            for t in shared
            if before[t] is ItemStatus.BLOCKED and after[t] is ItemStatus.BLOCKED
        )
    )
    blocker_changed = tuple(
        BlockerChange(task_id=t, was=before_blockers[t], now=after_blockers[t])
        for t in still_blocked
        if before_blockers.get(t) != after_blockers.get(t)
    )

    return PlanDiff(
        newly_unblocked=newly_unblocked,
        newly_applicable=appeared,
        no_longer_applicable=gone,
        newly_done=newly_done,
        newly_blocked=newly_blocked,
        still_blocked=still_blocked,
        blocker_changed=blocker_changed,
        answered=answered,
    )
