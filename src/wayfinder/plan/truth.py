"""Three-valued logic.

Every field on a `Situation` is nullable on purpose, because intake asks a
question only when the answer changes the plan. That makes two-valued logic
wrong: if an unknown answer silently reads as false, the plan quietly invents
facts about somebody, and if it reads as no-match, tasks disappear without
explanation.

So conditions evaluate to TRUE, FALSE or UNKNOWN under Kleene K3, and UNKNOWN is
a first-class outcome that puts a task into the `needs_info` partition rather
than guessing which way it would have gone.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class Truth(Enum):
    """A Kleene truth value."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def negate(self) -> Truth:
        if self is Truth.TRUE:
            return Truth.FALSE
        if self is Truth.FALSE:
            return Truth.TRUE
        return Truth.UNKNOWN


def conjunction(values: Iterable[Truth]) -> Truth:
    """Kleene AND. A single FALSE decides it; otherwise UNKNOWN is contagious.

    Empty conjunction is TRUE, which is what makes a task with no prerequisites
    startable without a special case.
    """
    saw_unknown = False
    for value in values:
        if value is Truth.FALSE:
            return Truth.FALSE
        if value is Truth.UNKNOWN:
            saw_unknown = True
    return Truth.UNKNOWN if saw_unknown else Truth.TRUE


def disjunction(values: Iterable[Truth]) -> Truth:
    """Kleene OR. A single TRUE decides it; otherwise UNKNOWN is contagious.

    Empty disjunction is FALSE.
    """
    saw_unknown = False
    for value in values:
        if value is Truth.TRUE:
            return Truth.TRUE
        if value is Truth.UNKNOWN:
            saw_unknown = True
    return Truth.UNKNOWN if saw_unknown else Truth.FALSE
