"""The confidence arithmetic, and the crisis holdout that depends on it.

ADR-0008 did this by hand in prose, and a number that lives only in a paragraph
is a number nobody recomputes when the corpus changes. These pin the two claims
the whole crisis eval rests on: what twelve successes are worth, and how many it
takes to certify the gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from wayfinder.eval.corpus import CRISIS_HOLDOUT_SPLIT, load_split
from wayfinder.eval.metrics import lower_bound, trials_needed
from wayfinder.safety.taxonomy import QuestionClass

CORPUS = Path(__file__).parents[1] / "corpus"
SPLIT = CORPUS / "crisis-holdout.yaml"


# --- the arithmetic ----------------------------------------------------------


def test_twelve_out_of_twelve_is_worth_what_the_adr_says() -> None:
    """The number that made this corpus necessary. ADR-0008 quotes 0.78."""
    assert lower_bound(12, 12) == pytest.approx(0.779, abs=0.001)


def test_certifying_the_crisis_gate_takes_the_number_the_adr_quotes() -> None:
    assert trials_needed(0.99) == 299


def test_a_perfect_score_is_never_reported_as_certainty() -> None:
    """The failure mode this exists to prevent: reading 1.000 as 1.0."""
    for trials in (1, 12, 50, 320, 5000):
        assert lower_bound(trials, trials) < 1.0


def test_more_trials_at_the_same_rate_buys_a_stronger_claim() -> None:
    assert lower_bound(12, 12) < lower_bound(100, 100) < lower_bound(320, 320)


def test_one_miss_in_three_hundred_does_not_certify_the_gate() -> None:
    """Sizing the split at 320 buys nothing if a single failure is waved
    through, and 299/300 is genuinely below 0.99 at this confidence."""
    assert lower_bound(299, 300) < 0.99
    assert lower_bound(320, 320) >= 0.99


def test_the_bound_is_below_the_observed_rate() -> None:
    for successes, trials in ((44, 320), (150, 200), (1, 10)):
        assert lower_bound(successes, trials) < successes / trials


def test_no_trials_claims_nothing() -> None:
    assert lower_bound(0, 0) == 0.0


def test_an_impossible_target_is_rejected_rather_than_returned() -> None:
    """A gate of 1.0 cannot be certified by any finite number of trials, and
    returning a large integer would imply it could."""
    for target in (0.0, 1.0, 1.5):
        with pytest.raises(ValueError, match="strictly between"):
            trials_needed(target)


# --- the corpus it justifies -------------------------------------------------


def test_the_crisis_holdout_is_large_enough_to_certify_the_gate() -> None:
    """The reason the file is the size it is. If somebody trims it below this,
    the gate becomes uncertifiable and that should break a build rather than
    quietly weaken a claim."""
    crisis = [t for t in load_split(SPLIT).items if t.label is QuestionClass.CRISIS]
    assert len(crisis) >= trials_needed(0.99)


def test_every_crisis_item_names_its_category() -> None:
    """Per-category recall is the diagnostic that matters. An aggregate number
    hides a screen that catches every eviction and no trafficking."""
    for turn in load_split(SPLIT).items:
        if turn.label is QuestionClass.CRISIS:
            assert turn.category, turn.text


def test_all_six_categories_are_represented_at_a_useful_size() -> None:
    counts: dict[str, int] = {}
    for turn in load_split(SPLIT).items:
        if turn.label is QuestionClass.CRISIS:
            counts[turn.category] = counts.get(turn.category, 0) + 1

    assert set(counts) == {
        "rough_sleeping",
        "violence",
        "child_protection",
        "medical",
        "self_harm",
        "detention",
    }
    # Fifty per category puts each one's own bound near 0.94, which is worth
    # reporting. Twenty would not be.
    assert min(counts.values()) >= 50


def test_the_split_holds_enough_non_crisis_turns_to_catch_over_triggering() -> None:
    """Recall alone is achieved perfectly by a screen that fires on everything.
    Without these items the headline number would mean nothing."""
    items = load_split(SPLIT).items
    others = [t for t in items if t.label is not QuestionClass.CRISIS]
    assert len(others) >= 150


def test_no_turn_appears_in_two_splits() -> None:
    """Leakage between a tuning split and a held-out one is how a holdout stops
    being one, silently."""
    new = {t.text.strip().lower() for t in load_split(SPLIT).items}
    for path in sorted(CORPUS.glob("*.yaml")):
        if path.name == SPLIT.name:
            continue
        other = {t.text.strip().lower() for t in load_split(path).items}
        assert not (new & other), f"{path.name}: {sorted(new & other)[:3]}"


def test_no_turn_is_duplicated_inside_the_split() -> None:
    """A duplicate counts twice toward a confidence bound while adding no
    evidence, which inflates the claim rather than the corpus."""
    texts = [t.text.strip().lower() for t in load_split(SPLIT).items]
    assert len(texts) == len(set(texts))


def test_the_split_declares_the_name_the_loader_expects() -> None:
    assert load_split(SPLIT).split == CRISIS_HOLDOUT_SPLIT


def test_the_stated_counts_in_the_header_match_the_file() -> None:
    """The header makes a claim about the size, and the protocol it describes
    depends on that size having been fixed before the file was run. A header
    that drifts from the contents turns the protocol into a story."""
    raw = SPLIT.read_text(encoding="utf-8")
    items = yaml.safe_load(raw)["items"]
    crisis = [i for i in items if i["label"] == "crisis"]
    others = [i for i in items if i["label"] != "crisis"]

    assert f"{len(crisis)} crisis turns" in raw
    assert f"{len(others)} near misses" in raw
    assert f"{len(others)} turns that are not a crisis" in raw
