"""Deterministic determination markers. Layer 2, and no model runs before it.

The boundary this encodes: **describing a rule is procedural; applying a rule to
this person is a determination.**

Markers live in code rather than in YAML because they are logic, not content.
The crisis lexicon is a list of phrases anybody can extend; this is a set of
interacting rules where the order matters, and hiding that in a data file would
make it look editable when it is not.

Three passes, in order, and the order is the whole design.

1. **Strong shapes.** Phrasings that are a determination whatever surrounds
   them: "am I entitled", "do I qualify", "will mine be refused".
2. **Procedural overrides.** Phrasings that are about a process even though they
   contain first-person words. "What do I bring to the appointment?" is
   procedural, and a naive first-person rule gets it wrong.
3. **Co-occurrence.** A first-person word near an entitlement word. Deliberately
   broad, and it only runs on what survived pass 2.

Pass 2 exists because without it this layer routes everything to a human, and a
classifier that escalates every question scores perfectly on determination
recall while being useless. That failure is called out explicitly in the design.
"""

from __future__ import annotations

import re
from typing import Final

from wayfinder.safety.normalise import normalise

# Pass 1. Each of these is a determination on its own.
_STRONG: Final[tuple[str, ...]] = (
    r"am i (entitled|eligible|qualified|allowed|permitted|covered)",
    r"are we (entitled|eligible|qualified|allowed|permitted|covered)",
    r"do i (qualify|meet|satisfy|have a right|have the right)",
    r"do we (qualify|meet|satisfy|have a right|have the right)",
    r"does my \w+ (qualify|count|meet|satisfy)",
    r"what am i entitled to",
    r"what are my (rights|entitlements|chances)",
    r"am i habitually resident",
    # "will I be sent", "will I be housed", "will I be moved" are all
    # predictions about this person's case, so the verb list stays open.
    r"will (i|we) (get|receive|succeed|qualify|keep|lose|be \w+)",
    r"will (mine|my \w+) (get|receive|be granted|be refused|be approved|be rejected|be accepted|succeed|work)",
    # "When can I apply" is asking whether they are allowed yet, which is an
    # eligibility question wearing a timing question's clothes. Contrast with
    # "when can somebody apply", which is procedural.
    r"when (can|will|am) i (apply|get|start|claim|be allowed|allowed)",
    r"how long will (mine|my \w+) take",
    r"(is|are) (my|our) \w+ (enough|sufficient|acceptable|valid|ok|okay)",
    r"(is|are) (my|our) \w+ \w+ (enough|sufficient|acceptable|valid)",
    r"can i (claim|get) (the|a|an|my) ",
    r"in my (case|situation|circumstances)",
    r"for my (case|situation|circumstances)",
    r"my chances",
    r"would i (qualify|be entitled|be eligible|get)",
    r"should i (be|have been) (entitled|eligible|getting|receiving)",
    r"do i still (qualify|get|receive)",
)

# Pass 2. Process questions, even when they say "I".
_PROCEDURAL_OVERRIDE: Final[tuple[str, ...]] = (
    r"^what documents",
    r"^which documents",
    r"^what papers",
    r"what documents (do|does|is|are)",
    r"what do i (bring|take|need to bring)",
    r"what should i bring",
    r"^where (do|can|should) i",
    r"^how (do|can|should) i",
    r"^when (do|can|should) i",
    r"^who (do|can|should) i",
    r"^what is the (process|procedure)",
    r"how (does|do) .* work",
    r"how long does .* (take|usually take)",
    r"^what happens if",
    r"^what happens when",
    r"^what are the (conditions|requirements|rules|criteria)",
    r"how is .* (assessed|decided|calculated|worked out)",
    r"who (decides|assesses)",
    r"^where is",
    r"^what is a ",
    r"^what is the difference",
)

# Pass 3, part one: first-person scoping.
_FIRST_PERSON: Final = r"\b(i|me|my|mine|myself|we|us|our|ours)\b"

# Pass 3, part two: the vocabulary of entitlement and outcome.
#
# "need" is deliberately absent. "What documents do I need?" is procedural, and
# putting need here would swallow a large share of the answerable questions.
_ENTITLEMENT: Final = (
    r"\b(entitled|entitlement|entitlements|eligible|eligibility|qualify|qualifies"
    r"|qualified|approved|granted|refused|rejected|succeed|chances|enough"
    r"|sufficient|acceptable|allowed|permitted|deserve|owed)\b"
)

_STRONG_RE: Final = tuple(re.compile(p) for p in _STRONG)
_OVERRIDE_RE: Final = tuple(re.compile(p) for p in _PROCEDURAL_OVERRIDE)
_FIRST_PERSON_RE: Final = re.compile(_FIRST_PERSON)
_ENTITLEMENT_RE: Final = re.compile(_ENTITLEMENT)

# How close a first-person word and an entitlement word have to be before the
# co-occurrence rule treats them as one claim. Wide enough for "am I, in this
# situation, eligible", narrow enough that two unrelated sentences do not fuse.
CO_OCCURRENCE_WINDOW: Final = 60


def determination_marker(text: str) -> str | None:
    """The marker that fires, or None. Deterministic and total.

    Returning the marker rather than a boolean is what makes a wrong escalation
    debuggable: somebody reviewing a bad refusal can see which rule caused it.
    """
    haystack = normalise(text)

    for pattern in _STRONG_RE:
        if pattern.search(haystack):
            return f"strong:{pattern.pattern}"

    for pattern in _OVERRIDE_RE:
        if pattern.search(haystack):
            return None

    window = _co_occurrence(haystack)
    if window is not None:
        return f"co_occurrence:{window}"

    return None


def _co_occurrence(haystack: str) -> str | None:
    """A first-person word within the window of an entitlement word."""
    people = [m.span() for m in _FIRST_PERSON_RE.finditer(haystack)]
    if not people:
        return None
    for entitlement in _ENTITLEMENT_RE.finditer(haystack):
        estart, eend = entitlement.span()
        for pstart, pend in people:
            gap = estart - pend if pstart < estart else pstart - eend
            if gap <= CO_OCCURRENCE_WINDOW:
                return f"{haystack[min(pstart, estart) : max(pend, eend)]}"
    return None
