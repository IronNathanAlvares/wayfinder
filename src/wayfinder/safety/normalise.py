"""Turning a raw turn into something the deterministic layers can match on.

Predictable, not clever. NFR-3 requires identical output for identical input,
always, so there is nothing here that could behave differently on a second run.

Deliberately *not* done: stemming, spell correction, transliteration. Each would
make matching fuzzier and the failure mode of a fuzzy crisis lexicon is a phrase
that used to match and silently stops.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# Curly quotes and dashes arrive from phone keyboards and copy-paste constantly.
# Left unhandled, "I can't" and "I can’t" are different strings to a matcher.
_PUNCTUATION: Final = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2015": "-",
        "\u00a0": " ",
    }
)  # fmt: skip

# Expanded before matching so a lexicon phrase only has to be written one way.
_CONTRACTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("can't", "cannot"),
    ("won't", "will not"),
    ("don't", "do not"),
    ("doesn't", "does not"),
    ("didn't", "did not"),
    ("haven't", "have not"),
    ("hasn't", "has not"),
    ("isn't", "is not"),
    ("aren't", "are not"),
    ("wasn't", "was not"),
    ("i'm", "i am"),
    ("i've", "i have"),
    ("i'll", "i will"),
    ("i'd", "i would"),
    ("they're", "they are"),
    ("we're", "we are"),
    ("there's", "there is"),
    ("it's", "it is"),
    ("that's", "that is"),
    ("what's", "what is"),
    ("who's", "who is"),
    ("let's", "let us"),
)

_WHITESPACE: Final = re.compile(r"\s+")
_ZERO_WIDTH: Final = re.compile(r"[\u200b-\u200f\u2060\ufeff]")


def normalise(text: str) -> str:
    """Lowercase, unify punctuation, expand contractions, collapse whitespace."""
    out = unicodedata.normalize("NFKC", text)
    out = _ZERO_WIDTH.sub("", out)
    out = out.translate(_PUNCTUATION)
    out = out.lower()
    for contraction, expansion in _CONTRACTIONS:
        out = out.replace(contraction, expansion)
    return _WHITESPACE.sub(" ", out).strip()
