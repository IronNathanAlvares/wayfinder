"""A deterministic layer 3, used when no model classifier is configured.

The design assumed layer 3 would always be an LLM. That leaves two problems.

The eval gate cannot run without an API key, and a gate that skips in CI is not
a gate. Worse, with layers 1, 2 and 4 alone the system can never say PROCEDURAL,
so it escalates everything, which the design itself names as the useless
outcome. Measuring precision on a class the system never assigns is a division
by zero, and reporting that as a pass would be exactly the broken-eval-reads-as-
passing failure the exit code convention exists to prevent.

So layer 3 became pluggable rather than necessarily a model. This is the default
implementation. An LLM implementation satisfies the same protocol and is used
when one is configured, and the committed eval baseline records which was
measured.

It is also a useful floor in its own right. When the model is unavailable the
system degrades to something predictable rather than to something silent.
"""

from __future__ import annotations

import re
from typing import Final

from wayfinder.safety.normalise import normalise
from wayfinder.safety.taxonomy import QuestionClass

# "What do I do now" rather than "how does X work". Somebody orienting rather
# than asking about one process.
_PLANNING: Final[tuple[str, ...]] = (
    r"^what (do|should) i do",
    r"^what (do|should) we do",
    r"what (do|should) i do (now|first|next)",
    r"^where (do|should) i (start|begin)",
    r"^what now",
    r"^what next",
    r"^what are my next steps",
    r"^what happens next",
    r"just arrived",
    r"^i (have )?just (arrived|got here|landed)",
    r"(help|helping) me (plan|get started|work out what)",
    r"in what order",
    r"^what is the first thing",
    r"^what comes first",
    r"^where should i begin",
)

# Advice this system is not qualified to give, and prediction nobody can make.
# Kept narrow: anything with a determination shape has already been taken by
# layer 2, so what lands here is the genuinely out of scope remainder.
_OUT_OF_SCOPE: Final[tuple[str, ...]] = (
    r"\b(should i|shall i) (appeal|sue|take legal action|go to court)",
    r"what should i say (in|at) (my|the) (interview|hearing|appeal)",
    r"(write|draft) (my|the|a) (appeal|letter|statement|submission)",
    r"\b(pretend|act as if|roleplay|role play|act) (as|as if|you are|to be)? ?(a|an|my|the)? ?(solicitor|lawyer|barrister|doctor|judge)",
    r"be my (solicitor|lawyer|barrister|doctor)",
    r"\b(what|which) (medicine|medication|tablets|drug|drugs)\b",
    r"should i (see|go to) (a|the) (doctor|gp|hospital)",
    r"\bdiagnos(e|is|ed)\b",
    r"is (this|that)( \w+)? (normal|serious|dangerous|infected|broken)",
    r"give me legal advice",
    r"\bwhat is the weather\b",
)

# Process questions. Deliberately last, so anything matching an earlier list
# wins, and deliberately broad, because this is the class the system is allowed
# to answer and a missed one only costs a caseworker thirty seconds.
_PROCEDURAL: Final[tuple[str, ...]] = (
    r"^(what|which|where|when|who|how)\b",
    r"^(is|are|does|do|can) (there|it|the|a|an)\b",
    r"^tell me about",
    r"^explain",
    r"\bwhat is the (process|procedure|difference)",
    r"\bhow (do|does) .* work",
    r"\bwhat documents\b",
    r"\bhow long does\b",
    r"\bwhere (is|are)\b",
    r"\bwho (decides|assesses|issues|runs)\b",
    r"\bopening hours\b",
    r"\bwhat happens (if|when)\b",
)

_PLANNING_RE: Final = tuple(re.compile(p) for p in _PLANNING)
_OUT_OF_SCOPE_RE: Final = tuple(re.compile(p) for p in _OUT_OF_SCOPE)
_PROCEDURAL_RE: Final = tuple(re.compile(p) for p in _PROCEDURAL)


def classify_remainder(text: str) -> QuestionClass | None:
    """Classify what survived the crisis screen and the determination markers.

    Returns None when nothing matches, which hands the turn to the tie-break
    rather than guessing. Guessing here would be a guess about somebody's
    entitlements, and the tie-break is the whole reason it is safe to say "I do
    not know" at this point.
    """
    haystack = normalise(text)

    for pattern in _PLANNING_RE:
        if pattern.search(haystack):
            return QuestionClass.PLANNING

    for pattern in _OUT_OF_SCOPE_RE:
        if pattern.search(haystack):
            return QuestionClass.OUT_OF_SCOPE

    for pattern in _PROCEDURAL_RE:
        if pattern.search(haystack):
            return QuestionClass.PROCEDURAL

    return None
