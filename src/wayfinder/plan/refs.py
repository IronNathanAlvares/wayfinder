"""Identifiers for tasks and for the artefacts tasks produce and consume.

An artefact reference is a prefixed URI such as `document:ppsn` or
`determination:habitual_residence`. The prefix *is* the kind. An earlier draft
of the design carried the kind twice, once as a `kind:` field and once as the
prefix on `ref:`, which meant a corpus contributor could eventually make the two
disagree. One fact, one place.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Final

from pydantic import StringConstraints

TASK_ID_PATTERN: Final = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"

TaskId = Annotated[str, StringConstraints(pattern=TASK_ID_PATTERN)]


class ArtefactKind(Enum):
    """What sort of thing a prerequisite is waiting on, and who can clear it.

    The kinds are not interchangeable. `DETERMINATION` is the boundary the
    system must not cross: it is cleared by a named authority, never by the
    person and never by this system. See ADR-0004.
    """

    TASK = "task"
    DOCUMENT = "document"
    STATUS = "status"
    DETERMINATION = "determination"
    ELAPSED = "elapsed"

    @property
    def clearable_by_the_person(self) -> bool:
        """Whether doing something can clear this, as opposed to waiting or being decided about."""
        return self in {ArtefactKind.TASK, ArtefactKind.DOCUMENT}


ARTEFACT_REF_PATTERN: Final = (
    r"^(task|document|status|determination|elapsed):[a-z0-9_]+(\.[a-z0-9_]+)*$"
)

ArtefactRef = Annotated[str, StringConstraints(pattern=ARTEFACT_REF_PATTERN)]

_REF_RE: Final = re.compile(ARTEFACT_REF_PATTERN)


def artefact_kind(ref: str) -> ArtefactKind:
    """The kind carried by the prefix. Raises if the reference is malformed."""
    match = _REF_RE.match(ref)
    if match is None:
        msg = f"malformed artefact reference: {ref!r}"
        raise ValueError(msg)
    return ArtefactKind(match.group(1))


def artefact_name(ref: str) -> str:
    """The part after the prefix, for display."""
    return ref.split(":", 1)[1]


def task_artefact(task_id: str) -> str:
    """The artefact reference a task satisfies simply by being completed."""
    return f"task:{task_id}"
