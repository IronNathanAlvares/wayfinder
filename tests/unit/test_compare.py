"""The comparison runner, driven with a fake screen and no key.

The important assertions are the two ways it must refuse to produce a number:
when there is no key, and when the screen degraded partway through. Both are
could-not-evaluate rather than a result, because a partial measurement reported
as a measurement is how a safety number becomes fiction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wayfinder.eval.compare import EXIT_CANNOT_EVALUATE, EXIT_OK, main, measure
from wayfinder.eval.corpus import LabelledTurn, load_corpus
from wayfinder.safety.escalation import ModelVerdict
from wayfinder.safety.loader import load_lexicon
from wayfinder.safety.models import CrisisCategory, CrisisLexicon

CORPUS = Path(__file__).parents[1] / "corpus"


@pytest.fixture(scope="module")
def lexicon() -> CrisisLexicon:
    return load_lexicon()


def _holdout() -> list[LabelledTurn]:
    return [t for t in load_corpus(CORPUS) if t.split == "holdout"]


def test_the_deterministic_baseline_reproduces_the_adr_number(
    lexicon: CrisisLexicon,
) -> None:
    """ADR-0008's headline figure, recomputed rather than quoted."""
    result = measure(_holdout(), lexicon, label="deterministic")
    assert result.recall.value is not None
    assert result.recall.value < 0.3
    assert result.degraded == 0


def test_a_perfect_model_lifts_recall_to_one(lexicon: CrisisLexicon) -> None:
    """Bounds the plumbing: if a screen says crisis to everything, recall is 1.0
    and the false-positive count is every non-crisis item. That is the shape of
    the tradeoff the gate deliberately accepts."""

    def always(text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        return (ModelVerdict.CRISIS, CrisisCategory.ROUGH_SLEEPING)

    result = measure(_holdout(), lexicon, label="always", model=always)
    assert result.recall.value == 1.0
    assert result.false_positives


def test_a_silent_model_changes_nothing(lexicon: CrisisLexicon) -> None:
    """A model with no opinion must not move the number in either direction."""

    def quiet(text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        return (ModelVerdict.NO_OPINION, None)

    baseline = measure(_holdout(), lexicon, label="none")
    with_model = measure(_holdout(), lexicon, label="quiet", model=quiet)
    assert with_model.recall.value == baseline.recall.value


def test_a_failing_model_is_counted_as_degraded(lexicon: CrisisLexicon) -> None:
    def broken(text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        msg = "down"
        raise RuntimeError(msg)

    turns = _holdout()
    result = measure(turns, lexicon, label="broken", model=broken)

    # Not every turn: the ones the lexicon already caught never reach the model,
    # so they are still screened. That is the monotonic design showing up in the
    # numbers, and it is the reason a model outage degrades the screen rather
    # than disabling it.
    caught_by_lexicon = measure(turns, lexicon, label="none")
    assert 0 < result.degraded < len(turns)
    assert result.degraded == len(turns) - int(caught_by_lexicon.recall.numerator)


def test_no_key_is_could_not_evaluate_rather_than_a_silent_baseline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Asking for a model measurement and getting the deterministic one back
    without a word would be the most misleading outcome available."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["--corpus", str(CORPUS), "--model", "claude-opus-5"])
    assert code == EXIT_CANNOT_EVALUATE
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_the_baseline_runs_without_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The deterministic half needs no key, so a run with no key is still a
    measurement rather than nothing."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--corpus", str(CORPUS)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "deterministic only" in out
    # The denominator rather than the score. The score belongs to
    # `baseline.json`, which fails a build when it moves; asserting it here as
    # well would mean two places to update and one of them forgotten.
    assert "/320)" in out, "the default run measured the wrong split, or nothing"
    assert "crisis-holdout-v4" in out


def test_the_default_split_is_the_one_sized_to_certify_the_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defaulting to the twelve-item split would make every run of this tool
    produce a number too weak to mean anything, which is the mistake ADR-0008
    exists to record."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["--corpus", str(CORPUS)])
    out = capsys.readouterr().out
    assert "crisis-holdout-v4 split" in out
    assert "/320)" in out, "the default split cannot certify the gate"


def test_the_smaller_mixed_split_can_still_be_asked_for(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--corpus", str(CORPUS), "--split", "holdout"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "holdout split" in out
    assert "/12)" in out


def test_an_unknown_arm_is_could_not_evaluate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Arms are named on the command line, and a typo that silently measured
    the default would report one configuration under another's name."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["--corpus", str(CORPUS), "--model", "m", "--prompt", "v9"])
    assert code == EXIT_CANNOT_EVALUATE
    assert "no such arm" in capsys.readouterr().err


def test_per_category_is_offered_as_an_arm_alongside_the_prompts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It belongs on the same flag as the prompts, because that is what makes
    it comparable: one run, the same items, arms named in one place."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["--corpus", str(CORPUS), "--model", "m", "--prompt", "nope"])
    assert "per-category" in capsys.readouterr().err


def test_a_dev_split_cannot_be_measured_by_this_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measuring a split the screen was tuned against reports the tuning. The
    argument parser refuses rather than leaving it to a reader to notice."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["--corpus", str(CORPUS), "--split", "crisis"])


def test_the_run_reports_a_confidence_bound_next_to_the_recall(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A recall printed without its bound is how 1.000 over twelve items gets
    quoted as if it settled something."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["--corpus", str(CORPUS)])
    out = capsys.readouterr().out
    assert "95% bound" in out
    assert "299" in out, "the run did not say how many successes the gate needs"


def test_a_missing_corpus_is_could_not_evaluate(tmp_path: Path) -> None:
    assert main(["--corpus", str(tmp_path / "nope")]) == EXIT_CANNOT_EVALUATE
