"""Failures the plan engine refuses to paper over."""

from __future__ import annotations

from collections.abc import Sequence


class PlanError(Exception):
    """Base for anything the plan engine cannot proceed through."""


class CycleError(PlanError):
    """The task graph contains a cycle, which is always a corpus bug.

    Silently breaking the cycle would produce a plan that looks fine and sends
    somebody in a circle, so this fails loudly instead.
    """

    def __init__(self, cycle: Sequence[str]) -> None:
        self.cycle = tuple(cycle)
        joined = " -> ".join([*self.cycle, self.cycle[0]] if self.cycle else [])
        super().__init__(f"prerequisite cycle in the task graph: {joined}")


class SearchExhaustedError(PlanError):
    """The unblocking search hit its bound before proving a minimum.

    Minimum-cost solving over an AND/OR graph is NP-hard in general. At corpus
    scale the exact search finishes easily, so hitting this bound means the
    corpus grew a shape nobody designed for. Reporting a possibly non-minimal
    answer silently would break the guarantee the output claims to make.
    """

    def __init__(self, target: str, limit: int) -> None:
        self.target = target
        self.limit = limit
        super().__init__(
            f"unblocking search for {target!r} exceeded {limit} states without "
            "proving a minimum"
        )
