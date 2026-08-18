"""The gate itself, because a broken gate reads as a passing one.

The exit code distinction is the whole point. 0 is a pass, 1 is a verdict of
fail, and 2 is could-not-evaluate. Collapsing 1 and 2 lets an eval that never
ran look like an eval that succeeded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from wayfinder.eval.corpus import SPLITS, EvalError, load_corpus, load_split
from wayfinder.eval.gate import (
    EXIT_CANNOT_EVALUATE,
    EXIT_GATE_BREACHED,
    EXIT_OK,
    main,
)
from wayfinder.eval.metrics import hold_rate, pair_report, report_for
from wayfinder.safety.taxonomy import QuestionClass

CORPUS = Path(__file__).parents[1] / "corpus"


def test_the_shipped_corpus_loads() -> None:
    turns = load_corpus(CORPUS)
    assert len(turns) > 300
    for name in SPLITS:
        assert any(t.split == name for t in turns), name


def test_a_missing_split_is_an_error_not_an_absence(tmp_path: Path) -> None:
    """A split that quietly disappears takes its failures with it, and the gate
    goes green for the wrong reason."""
    with pytest.raises(EvalError, match="missing"):
        load_corpus(tmp_path)


def test_every_labelled_turn_has_a_class_the_system_knows() -> None:
    for turn in load_corpus(CORPUS):
        assert isinstance(turn.label, QuestionClass)


def test_boundary_items_come_in_pairs() -> None:
    """A minimal pair with one side missing is not a minimal pair."""
    items = load_split(CORPUS / "boundary.yaml").items
    counts: dict[str, int] = {}
    for item in items:
        assert item.pair, item.text
        counts[item.pair] = counts.get(item.pair, 0) + 1
    assert all(n == 2 for n in counts.values()), counts


def test_undefined_precision_is_not_a_pass() -> None:
    """A classifier that never assigns a class cannot be scored on it. Calling
    that 1.0 would hide exactly the failure the gate exists to catch."""
    report = report_for(
        QuestionClass.PROCEDURAL,
        [QuestionClass.DETERMINATION],
        [QuestionClass.DETERMINATION],
    )
    assert report.precision.undefined
    assert report.precision.value is None
    assert "undefined" in report.precision.render()


def test_hold_rate_counts_every_refusal_as_a_hold() -> None:
    """Which refusal matters much less than whether it was refused."""
    assert (
        hold_rate(
            [
                QuestionClass.DETERMINATION,
                QuestionClass.OUT_OF_SCOPE,
                QuestionClass.CRISIS,
            ]
        ).value
        == 1.0
    )
    assert hold_rate([QuestionClass.PROCEDURAL]).value == 0.0


def test_a_pair_needs_both_sides_right() -> None:
    """Escalating everything gets one side of every pair. That is not a result."""
    report = pair_report(
        ["a", "a"],
        [QuestionClass.PROCEDURAL, QuestionClass.DETERMINATION],
        [QuestionClass.DETERMINATION, QuestionClass.DETERMINATION],
    )
    assert report.total == 1
    assert report.both_correct == 0


def test_the_gate_reports_the_design_targets_as_unmet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0008. The held-out crisis recall does not meet the design gate, and
    the gate says so rather than scoring only the split it was tuned on."""
    code = main(["--corpus", str(CORPUS), "--show-failures", "0"])
    assert code in {EXIT_GATE_BREACHED, EXIT_CANNOT_EVALUATE}
    out = capsys.readouterr().out
    assert "Held out" in out
    assert "measure the tuning" in out


def test_the_baseline_mode_is_green_and_still_says_the_gates_are_unmet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CI gates on no-regression. A permanently red build gets ignored, and a
    build that goes green by scoring its training set is how this went wrong."""
    code = main(["--corpus", str(CORPUS), "--baseline", "--show-failures", "0"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "No regression" in out
    assert "not all met" in out


def test_a_regression_against_the_baseline_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in SPLITS:
        (tmp_path / f"{name}.yaml").write_text(
            (CORPUS / f"{name}.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
    baseline = json.loads((CORPUS / "baseline.json").read_text(encoding="utf-8"))
    baseline["dev/CRISIS recall"] = 1.0
    baseline["holdout/CRISIS recall"] = 0.99
    (tmp_path / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")

    code = main(["--corpus", str(tmp_path), "--baseline", "--show-failures", "0"])
    assert code == EXIT_GATE_BREACHED
    assert "REGRESSION" in capsys.readouterr().out


def test_a_missing_baseline_is_could_not_evaluate(tmp_path: Path) -> None:
    for name in SPLITS:
        (tmp_path / f"{name}.yaml").write_text(
            (CORPUS / f"{name}.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )
    assert main(["--corpus", str(tmp_path), "--baseline"]) == EXIT_CANNOT_EVALUATE


def test_a_missing_corpus_is_could_not_evaluate_not_a_failure(tmp_path: Path) -> None:
    assert main(["--corpus", str(tmp_path / "nope")]) == EXIT_CANNOT_EVALUATE


def test_a_malformed_split_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("- not a mapping", encoding="utf-8")
    with pytest.raises(EvalError, match="expected a mapping"):
        load_split(path)


def test_a_split_with_no_items_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("split: x\nitems: []", encoding="utf-8")
    with pytest.raises(EvalError, match="non-empty"):
        load_split(path)


def test_fixtures_directory_is_untouched_by_the_eval() -> None:
    """The eval corpus and the plan fixtures are separate on purpose."""
    assert not (FIXTURES / "corpus" / "boundary.yaml").exists()
