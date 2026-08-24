"""Working out where a closing window stands, and refusing to close it.

One decision drives everything in this module, so it goes first.

**This never tells anybody their window has shut.** The worst outcome the whole
plan engine can produce is somebody with a live right not exercising it because
this system told them not to bother. Three things make that a real risk rather
than a theoretical one: the start date comes from what somebody remembered or
transcribed, late applications are often accepted at the deciding body's
discretion, and the person reading this has every reason to believe a computer
about a date. So the furthest this will go is `MAY_HAVE_CLOSED`, and the
instruction attached to it is to go and ask.

The asymmetry is the argument. Saying "you may still have time" to somebody who
does not costs them a wasted phone call. Saying "you are out of time" to
somebody who is not costs them the thing itself. Those are not comparable, so
the tie does not get split down the middle.

Two consequences follow, and both are load-bearing:

- A task whose window may have closed is **never dropped and never demoted**. It
  sorts to the very top, because if there is any chance it is live then it is
  the most urgent thing on the page.
- Nothing here decides anything. Whether a late appeal is accepted is a
  judgement belonging to the body that made the decision, which is ADR-0004 in
  its ordinary place rather than a special case.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict

from wayfinder.plan.models import Deadline, Task
from wayfinder.plan.refs import ArtefactKind, TaskId, artefact_kind
from wayfinder.plan.situation import Situation

# How close to the end counts as "closing". A week is the point at which post,
# an appointment and an office being shut on Sunday all stop being absorbable.
CLOSING_SOON: Final = timedelta(days=7)


class DeadlineStatus(Enum):
    """Deliberately four values, and deliberately no `CLOSED`.

    `MAY_HAVE_CLOSED` is the strongest thing this system is allowed to say. See
    the module docstring for why the missing fifth value is missing.
    """

    # The window exists, and we do not know when its clock started. This is the
    # common case: the corpus knows the rule, the situation does not carry the
    # date. Say the rule, ask for the date, compute nothing.
    UNKNOWN_START = "unknown_start"
    OPEN = "open"
    CLOSING = "closing"
    MAY_HAVE_CLOSED = "may_have_closed"


class DeadlineState(BaseModel):
    """A window as it stands on one day, for one person."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: DeadlineStatus
    within: timedelta
    described_as: str

    # All three are None when the clock's start is unknown, which is not a
    # failure. It is the difference between "you have 60 days from the date on
    # the letter" and "you have 12 days", and the first is still worth saying.
    started_on: date | None = None
    closes_on: date | None = None
    days_remaining: int | None = None

    @property
    def running(self) -> bool:
        """Whether there is a real clock to rank by, rather than only a rule."""
        return self.days_remaining is not None

    @property
    def urgency(self) -> int:
        """Sort key within running deadlines. Smaller is more urgent.

        A window that may have closed sorts ahead of one with a day left, which
        is the whole point: if there is any chance it is still open then it is
        the most time-critical thing on the page, and if there is not then
        somebody still needs to be told to ask.
        """
        return self.days_remaining if self.days_remaining is not None else 0


def _started_on(deadline: Deadline, situation: Situation) -> date | None:
    """The day the clock started, if the situation happens to know it.

    Only determinations carry a date today. A document the person holds is a
    valid thing to hang a window off and `Deadline` allows it, but `Situation`
    records documents as held or not held with no date, so those come back
    unknown rather than guessed. Saying so here keeps the gap visible instead of
    letting it look like a bug the first time somebody writes one.
    """
    if artefact_kind(deadline.of) is not ArtefactKind.DETERMINATION:
        return None
    record = situation.determinations.get(deadline.of)
    return record.recorded_on if record else None


def state_of(deadline: Deadline, situation: Situation, *, today: date) -> DeadlineState:
    started = _started_on(deadline, situation)
    if started is None:
        return DeadlineState(
            status=DeadlineStatus.UNKNOWN_START,
            within=deadline.within,
            described_as=deadline.described_as,
        )

    closes = started + deadline.within
    remaining = (closes - today).days

    if remaining < 0:
        status = DeadlineStatus.MAY_HAVE_CLOSED
    elif timedelta(days=remaining) <= CLOSING_SOON:
        status = DeadlineStatus.CLOSING
    else:
        status = DeadlineStatus.OPEN

    return DeadlineState(
        status=status,
        within=deadline.within,
        described_as=deadline.described_as,
        started_on=started,
        closes_on=closes,
        days_remaining=remaining,
    )


def deadlines_for(
    tasks: tuple[Task, ...], situation: Situation, *, today: date
) -> Mapping[TaskId, DeadlineState]:
    return {
        task.id: state_of(task.deadline, situation, today=today)
        for task in tasks
        if task.deadline is not None
    }


__all__: Final = [
    "CLOSING_SOON",
    "DeadlineState",
    "DeadlineStatus",
    "deadlines_for",
    "state_of",
]
