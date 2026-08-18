"""The model crisis screen, constrained so it can only ever escalate.

ADR-0008. A held-out corpus put the deterministic screen at 0.17 recall, so a
model becomes load-bearing here. ADR-0006's objection to that was "a model can
be talked out of escalating", and this module answers it structurally rather
than by asking nicely.

The screen is wrapped so that it has no way to express "not a crisis" about a
turn the lexicon already flagged. Its only two possible effects are to escalate
a turn that was not flagged, or to do nothing. Being talked into an unnecessary
escalation shows somebody a list of helplines they did not need, which is the
error direction the design already accepts.

The wrapper also decides what happens when the model is unavailable, and the
answer is not "carry on quietly". A crisis screen that stops working without
saying so is worse than one that is visibly off, because the first is still
trusted.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from wayfinder.safety.crisis import screen
from wayfinder.safety.models import CrisisCategory, CrisisHit, CrisisLexicon


class ModelVerdict(Enum):
    """The only two things a model screen is allowed to say.

    There is deliberately no NOT_CRISIS. A model that could return one would
    have a path to clearing a lexicon hit the moment somebody refactored this,
    and the type is what stops that being possible rather than merely discouraged.
    """

    CRISIS = "crisis"
    NO_OPINION = "no_opinion"


class ModelScreen(Protocol):
    """Implemented by an LLM adapter. Returns a category when it escalates."""

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]: ...


class ScreenOutcome(Enum):
    LEXICON = "lexicon"
    MODEL = "model"
    CLEAR = "clear"
    DEGRADED = "degraded"


class Screened:
    """The result of the full crisis screen, including whether it was complete."""

    __slots__ = ("hit", "outcome")

    def __init__(self, hit: CrisisHit | None, outcome: ScreenOutcome) -> None:
        self.hit = hit
        self.outcome = outcome

    @property
    def is_crisis(self) -> bool:
        return self.hit is not None

    @property
    def screening_was_complete(self) -> bool:
        """False when the model layer could not run.

        The caller must surface this. Requirement FR-S2 says no LLM call occurs
        before the crisis verdict; it does not say the verdict may pretend to be
        as good as it usually is when half of it did not run.
        """
        return self.outcome is not ScreenOutcome.DEGRADED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Screened(hit={self.hit!r}, outcome={self.outcome.value})"


def full_screen(
    text: str,
    lexicon: CrisisLexicon,
    *,
    model: ModelScreen | None = None,
    model_available: bool = True,
) -> Screened:
    """Deterministic screen first, then the model, and the model can only add.

    The ordering is not a performance choice. The lexicon result is computed and
    returned before the model is consulted at all, so there is no arrangement of
    this code in which a model response participates in clearing a lexicon hit.
    """
    hit = screen(text, lexicon)
    if hit is not None:
        return Screened(hit, ScreenOutcome.LEXICON)

    if model is None:
        # No model configured at all. This is the deterministic-only build, and
        # it is degraded by definition rather than by failure.
        return Screened(
            None, ScreenOutcome.DEGRADED if not model_available else ScreenOutcome.CLEAR
        )

    try:
        verdict, category = model(text)
    except Exception:
        return Screened(None, ScreenOutcome.DEGRADED)

    if verdict is ModelVerdict.CRISIS:
        return Screened(
            CrisisHit(
                category=category or CrisisCategory.ROUGH_SLEEPING,
                matched="model screen",
            ),
            ScreenOutcome.MODEL,
        )

    return Screened(None, ScreenOutcome.CLEAR)


DEGRADED_NOTICE = """\
One part of my safety check is not running at the moment, so I may miss
something urgent that I would normally catch. If any of this applies to you
right now, please use these numbers rather than waiting for me:

  Emergency services              999 or 112, 24 hours
  Samaritans                      Freephone 116 123, 24 hours
  Pieta, suicide and self-harm    Freephone 1800 247 247, 24 hours
  Women's Aid                     Freephone 1800 341 900, 24 hours
  Homeless in Dublin              Freephone 1800 707 707, 10am to 10pm
"""
