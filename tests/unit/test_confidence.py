"""The confidence arithmetic, and the crisis holdouts that depend on it.

ADR-0008 did this by hand in prose, and a number that lives only in a paragraph
is a number nobody recomputes when the corpus changes. These pin the two claims
the whole crisis eval rests on: what twelve successes are worth, and how many it
takes to certify the gate.

The corpus checks run over both crisis splits. A second split written to a
weaker protocol than the first would be a way of quietly lowering the bar while
appearing to raise it.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
import yaml

from wayfinder.eval.corpus import CRISIS_HOLDOUT_SPLITS, load_split
from wayfinder.eval.metrics import lower_bound, trials_needed
from wayfinder.safety.taxonomy import QuestionClass

CORPUS = Path(__file__).parents[1] / "corpus"
SPLITS = [CORPUS / f"{name}.yaml" for name in CRISIS_HOLDOUT_SPLITS]

CATEGORIES = {
    "rough_sleeping",
    "violence",
    "child_protection",
    "medical",
    "self_harm",
    "detention",
}


def by_name(path: Path) -> str:
    return path.stem


# --- the arithmetic ----------------------------------------------------------


def test_twelve_out_of_twelve_is_worth_what_the_adr_says() -> None:
    """The number that made these corpora necessary. ADR-0008 quotes 0.78."""
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
    """Sizing a split at 320 buys nothing if a single failure is waved through,
    and 299/300 is genuinely below 0.99 at this confidence."""
    assert lower_bound(299, 300) < 0.99
    assert lower_bound(320, 320) >= 0.99


def test_the_bound_is_below_the_observed_rate() -> None:
    for successes, trials in ((44, 320), (287, 320), (150, 200), (1, 10)):
        assert lower_bound(successes, trials) < successes / trials


def test_no_trials_claims_nothing() -> None:
    assert lower_bound(0, 0) == 0.0


def test_an_impossible_target_is_rejected_rather_than_returned() -> None:
    """A gate of 1.0 cannot be certified by any finite number of trials, and
    returning a large integer would imply it could."""
    for target in (0.0, 1.0, 1.5):
        with pytest.raises(ValueError, match="strictly between"):
            trials_needed(target)


# --- the corpora it justifies ------------------------------------------------


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_the_crisis_holdout_is_large_enough_to_certify_the_gate(split: Path) -> None:
    """The reason each file is the size it is. If somebody trims one below this,
    the gate becomes uncertifiable, and that should break a build rather than
    quietly weaken a claim."""
    crisis = [t for t in load_split(split).items if t.label is QuestionClass.CRISIS]
    assert len(crisis) >= trials_needed(0.99)


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_every_crisis_item_names_its_category(split: Path) -> None:
    """Per-category recall is the diagnostic that matters. An aggregate hides a
    screen that catches every eviction and no trafficking."""
    for turn in load_split(split).items:
        if turn.label is QuestionClass.CRISIS:
            assert turn.category, turn.text


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_all_six_categories_are_represented_at_a_useful_size(split: Path) -> None:
    counts: dict[str, int] = {}
    for turn in load_split(split).items:
        if turn.label is QuestionClass.CRISIS:
            counts[turn.category] = counts.get(turn.category, 0) + 1

    assert set(counts) == CATEGORIES
    # Fifty per category puts each one's own bound near 0.94, which is worth
    # reporting. Twenty would not be.
    assert min(counts.values()) >= 50


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_the_split_holds_enough_non_crisis_turns_to_catch_over_triggering(
    split: Path,
) -> None:
    """Recall alone is achieved perfectly by a screen that fires on everything.
    Without these items the headline number would mean nothing."""
    others = [t for t in load_split(split).items if t.label is not QuestionClass.CRISIS]
    assert len(others) >= 150


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_no_turn_appears_in_two_splits(split: Path) -> None:
    """Leakage is how a holdout stops being one, silently.

    It matters most between the two crisis splits. v2 exists precisely because
    v1's failures have been read, so a shared item would carry that
    contamination straight across and make the second measurement worthless in
    the same way as the first.
    """
    here = {t.text.strip().lower() for t in load_split(split).items}
    for path in sorted(CORPUS.glob("*.yaml")):
        if path.name == split.name:
            continue
        other = {t.text.strip().lower() for t in load_split(path).items}
        assert not (here & other), f"{path.name}: {sorted(here & other)[:3]}"


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_no_turn_is_duplicated_inside_the_split(split: Path) -> None:
    """A duplicate counts twice toward a confidence bound while adding no
    evidence, which inflates the claim rather than the corpus."""
    texts = [t.text.strip().lower() for t in load_split(split).items]
    assert len(texts) == len(set(texts))


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_the_split_declares_the_name_the_loader_expects(split: Path) -> None:
    assert load_split(split).split == split.stem


@pytest.mark.parametrize("split", SPLITS, ids=by_name)
def test_the_stated_counts_in_the_header_match_the_file(split: Path) -> None:
    """Each header claims a size, and the protocol it describes depends on that
    size having been fixed before the file was run. A header that drifts from
    the contents turns the protocol into a story."""
    raw = split.read_text(encoding="utf-8")
    items = yaml.safe_load(raw)["items"]
    crisis = [i for i in items if i["label"] == "crisis"]
    others = [i for i in items if i["label"] != "crisis"]

    assert f"{len(crisis)} crisis turns" in raw
    assert f"{len(others)} near misses" in raw


def test_no_later_split_is_easier_than_the_one_before_it() -> None:
    """Each split judges a fix written by somebody who saw the previous one fail.

    If a later split were easier, the fix would look better for reasons that
    have nothing to do with the fix. Near-miss count is the specific guard,
    because the cheap way to buy recall is to fire on everything, and it must
    not fall as the series goes on.
    """
    splits = [load_split(path).items for path in SPLITS]
    crisis = [sum(1 for t in s if t.label is QuestionClass.CRISIS) for s in splits]
    others = [sum(1 for t in s if t.label is not QuestionClass.CRISIS) for s in splits]

    assert crisis == [320] * len(SPLITS), crisis
    assert others == sorted(others), others


SIMILARITY_CEILING = 0.75


def _similarity(left: str, right: str) -> float:
    """Symmetric, because `SequenceMatcher` is not.

    Its junk heuristics index the second sequence, so `ratio(a, b)` and
    `ratio(b, a)` can differ. Taking one of them missed a pair at 0.83 that the
    other found, which is a quiet way for a leakage check to pass while leaking.
    """
    return max(
        difflib.SequenceMatcher(None, left, right).ratio(),
        difflib.SequenceMatcher(None, right, left).ratio(),
    )


def test_no_two_crisis_splits_share_a_near_duplicate() -> None:
    """Exact-match leakage is checked above. This catches the softer kind.

    Two items differing by one word contaminate a holdout exactly as much as
    two identical ones and pass every equality check. Four such pairs were
    found before v2 was first run and twenty-six before v3 was, in both cases
    while no result existed yet, which is the only point at which fixing them
    is honest.

    The word-overlap gate is a speed optimisation, not part of the claim: two
    sentences sharing under a quarter of their words cannot reach the ceiling.
    """
    texts = {path.stem: [t.text for t in load_split(path).items] for path in SPLITS}
    too_close = []
    for i, (name, items) in enumerate(texts.items()):
        for other_name, others in list(texts.items())[i + 1 :]:
            indexed = [(o, set(o.split())) for o in others]
            for item in items:
                words = set(item.split())
                for other, other_words in indexed:
                    if len(words & other_words) / len(words | other_words) < 0.25:
                        continue
                    ratio = _similarity(item, other)
                    if ratio >= SIMILARITY_CEILING:
                        too_close.append(
                            (round(ratio, 2), name, item, other_name, other)
                        )
    assert not too_close, too_close[:5]


# --- comparing two configurations --------------------------------------------


def test_a_configuration_compared_with_itself_shows_no_difference() -> None:
    from wayfinder.eval.metrics import mcnemar

    missed = ["a", "b", "c"]
    result = mcnemar(missed, missed)
    assert result.only_left_missed == 0
    assert result.p_value == 1.0
    assert not result.significant


def test_only_the_disagreements_count() -> None:
    """Turns both configurations got right, and turns both got wrong, say
    nothing about which is better. Including them would dilute the test toward
    finding no difference."""
    from wayfinder.eval.metrics import mcnemar

    shared = [str(i) for i in range(500)]
    lean = mcnemar([*shared, "x"], [*shared])
    bare = mcnemar(["x"], [])
    assert lean.p_value == bare.p_value


def test_a_lopsided_disagreement_is_significant() -> None:
    """Eleven turns caught by one and not the other, one the other way. This is
    the detention regression, and it has to come out significant or the test is
    not doing its job."""
    from wayfinder.eval.metrics import mcnemar

    result = mcnemar([f"lost{i}" for i in range(11)], ["gained"])
    assert result.p_value == pytest.approx(0.0063, abs=0.0005)
    assert result.significant


def test_an_even_disagreement_is_not_significant() -> None:
    """Seventeen against eighteen. The overall V1-to-V2 comparison, which looks
    like a change and is not."""
    from wayfinder.eval.metrics import mcnemar

    result = mcnemar([f"a{i}" for i in range(17)], [f"b{i}" for i in range(18)])
    assert result.p_value == 1.0
    assert not result.significant


def test_the_test_is_two_sided() -> None:
    """Which configuration is better is not known in advance, and a one-sided
    test would report a regression as significant only in the direction
    somebody hoped for."""
    from wayfinder.eval.metrics import mcnemar

    forwards = mcnemar([f"x{i}" for i in range(11)], ["y"])
    backwards = mcnemar(["y"], [f"x{i}" for i in range(11)])
    assert forwards.p_value == backwards.p_value


def test_a_difference_of_one_turn_proves_nothing() -> None:
    """Detention 0.778 against 0.759 is one turn in fifty-four, which is what
    the failed revert amounted to."""
    from wayfinder.eval.metrics import mcnemar

    assert not mcnemar(["a"], []).significant
