"""A reading-level measure, so the plain-language target is a number.

NFR-9 and success criterion S7 both say client-facing output must meet a plain
English target and that it must be measured. Without a measure "plain language"
is an intention somebody asserts in a review and nobody checks.

Flesch-Kincaid grade level, computed here rather than pulled in as a dependency:
it is a dozen lines, the syllable heuristic is the only interesting part, and a
package would hide that behind a version pin.

What it cannot do is worth stating. It counts syllables and sentence lengths. It
does not know that "habitual residence condition" is three short words and an
enormous idea. A text can score well and still be incomprehensible to somebody
reading in a second language under stress, which is why `09` section 7 keeps
reading it aloud on the manual list.
"""

from __future__ import annotations

import re
from typing import Final

# The design's target. Grade 8 is roughly what plain-English guidance aims at
# for public information, and everything here is public information.
TARGET_GRADE: Final = 8.0

_SENTENCE = re.compile(r"[.!?]+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_VOWELS: Final = "aeiouy"


def count_syllables(word: str) -> int:
    """A vowel-group heuristic. Wrong on individual words, fine in aggregate."""
    lowered = word.lower().strip("'-")
    if not lowered:
        return 0
    groups = 0
    previous_was_vowel = False
    for char in lowered:
        is_vowel = char in _VOWELS
        if is_vowel and not previous_was_vowel:
            groups += 1
        previous_was_vowel = is_vowel
    if lowered.endswith("e") and groups > 1 and not lowered.endswith(("le", "ee")):
        groups -= 1
    return max(groups, 1)


def grade_level(text: str) -> float | None:
    """Flesch-Kincaid grade. None when there is not enough text to judge.

    None rather than zero: a two-word string has no meaningful reading level,
    and returning a flattering number for one would let an empty answer pass a
    readability gate.
    """
    words = _WORD.findall(text)
    sentences = [s for s in _SENTENCE.split(text) if _WORD.search(s)]
    if len(words) < 10 or not sentences:
        return None

    syllables = sum(count_syllables(w) for w in words)
    return (
        0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59
    )


def readable(text: str, *, target: float = TARGET_GRADE) -> bool:
    """Whether the text meets the target. Unjudgeable text passes.

    Short text is usually a phone number and a line of instruction, which is
    exactly what somebody in a hurry needs, so failing it for being short would
    push the output in the wrong direction.
    """
    grade = grade_level(text)
    return grade is None or grade <= target
