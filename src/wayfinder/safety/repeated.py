"""Ask the same screen more than once and take the union.

The model screen is not deterministic. The same prompt over the same 320 items
scored 288 one run and 287 the next. Repeated sampling turns that variance into
recall: ask N times, escalate if any sample says crisis.

**What this is worth depends entirely on why the misses happen, and that is the
measurement.** If a miss is a coin landing badly, N samples cut the miss rate to
its Nth power and a screen at 0.884 would reach 0.998 at N=3, clearing the gate.
If a miss is the model reliably reading a turn as not-a-crisis, N samples return
the same answer N times and this buys nothing at N times the cost.

The evidence already points at the second. Two runs of an identical
configuration differed by one item in 320, so roughly 99.7 percent of verdicts
were stable. **The prediction, written before the run: union at N=3 gains a
handful of turns, not thirty-seven.** It is recorded here so the result means
something whichever way it goes.

**It trades precision for recall and cannot avoid doing so.** The union is over
the whole screen, not over the crisis items, so a false positive in any sample
becomes a false positive overall. If the per-sample rate is p, the union rate
approaches 1-(1-p)^N. That is the cost side and it is measured alongside.

**The safety property is unchanged.** `full_screen` runs the lexicon first, so
nothing here can clear a lexicon hit, and a union of screens that can only add a
detection still only adds.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Final

from wayfinder.safety.escalation import ModelScreen, ModelVerdict
from wayfinder.safety.models import CrisisCategory

# Three, chosen from cost rather than from any result: it is the smallest N
# where a union can differ from a majority vote, and enough to see whether the
# misses move at all. Fixed before the measurement so it cannot be tuned to it.
DEFAULT_SAMPLES: Final = 3


class RepeatedScreen:
    """Runs several screens over the same turn and escalates if any of them do.

    The screens are passed in rather than constructed, because in an evaluation
    each sample needs its own cache entry and only the caller knows how those
    are keyed. In a live system they would be the same adapter N times.

    A failure in any sample fails the whole screen. Taking the union of the ones
    that answered would let a network blip quietly reduce N, and the number of
    samples is the only thing this class is for.
    """

    __slots__ = ("_screens",)

    def __init__(self, screens: Sequence[ModelScreen]) -> None:
        if not screens:
            msg = "a repeated screen needs at least one screen to repeat"
            raise ValueError(msg)
        self._screens = tuple(screens)

    @property
    def samples(self) -> int:
        return len(self._screens)

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        # Concurrent for the same reason the per-category screen is: N sequential
        # calls would multiply this screen's latency by N, and latency here is
        # part of the safety story.
        with ThreadPoolExecutor(max_workers=len(self._screens)) as pool:
            results = list(pool.map(lambda s: s(text), self._screens))

        # The first sample that escalated, in the order the screens were given,
        # so the category a person sees does not depend on thread scheduling.
        for verdict, category in results:
            if verdict is ModelVerdict.CRISIS:
                return verdict, category
        return ModelVerdict.NO_OPINION, None
