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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--corpus", str(CORPUS)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "deterministic only" in out
    assert "0.167" in out


def test_a_missing_corpus_is_could_not_evaluate(tmp_path: Path) -> None:
    assert main(["--corpus", str(tmp_path / "nope")]) == EXIT_CANNOT_EVALUATE
