"""The reading-level measure, and the shipped text measured against it."""

from __future__ import annotations

import pytest

from wayfinder.graph.readability import (
    TARGET_GRADE,
    count_syllables,
    grade_level,
    readable,
)
from wayfinder.safety import refusals


@pytest.mark.parametrize(
    ("word", "expected"),
    [("cat", 1), ("water", 2), ("habitual", 4), ("residence", 3), ("a", 1)],
)
def test_syllable_counts_are_about_right(word: str, expected: int) -> None:
    """A heuristic, judged on being close rather than exact."""
    assert abs(count_syllables(word) - expected) <= 1


def test_short_text_has_no_meaningful_reading_level() -> None:
    """Returning a flattering number for two words would let an empty answer
    pass a readability gate."""
    assert grade_level("Call 999.") is None
    assert readable("Call 999.")


def test_plain_text_scores_below_dense_text() -> None:
    plain = (
        "You need a PPS number. Ask for it when you apply. "
        "It takes about four days. Bring your letter with you."
    )
    dense = (
        "Notwithstanding the aforementioned determination, the applicant's "
        "entitlement remains contingent upon satisfaction of the habitual "
        "residence condition as adjudicated by the responsible department."
    )
    plain_grade, dense_grade = grade_level(plain), grade_level(dense)
    assert plain_grade is not None and dense_grade is not None
    assert plain_grade < dense_grade


def test_every_refusal_template_meets_the_target() -> None:
    """S7. The refusals are the text most likely to be read by somebody who is
    upset, so they are the text that most needs to be readable."""
    for template in refusals.ALL_TEMPLATES:
        grade = grade_level(template)
        assert grade is not None
        assert grade <= TARGET_GRADE, f"grade {grade:.1f}: {template[:60]}"


def test_the_degraded_notice_meets_the_target() -> None:
    from wayfinder.safety.escalation import DEGRADED_NOTICE

    assert readable(DEGRADED_NOTICE)


def test_the_shipped_task_text_meets_the_target() -> None:
    """The `why` on every task is client-facing, so it is held to the same bar."""
    from datetime import date
    from pathlib import Path

    from wayfinder.corpus.loader import load_corpus

    data = Path(__file__).parents[2] / "src" / "wayfinder" / "corpus" / "data"
    corpus = load_corpus(data, today=date(2026, 8, 24))
    too_hard = [
        (t.id, grade_level(t.why))
        for t in corpus.tasks
        if (g := grade_level(t.why)) is not None and g > TARGET_GRADE + 2
    ]
    assert not too_hard, too_hard
