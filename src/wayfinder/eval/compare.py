"""Measure the crisis screen with and without a model, on the held-out split.

This answers the question ADR-0008 left open: the deterministic screen measures
0.167 recall held out, and a model is supposed to close that gap. Whether it
actually does is a measurement, not an assumption, and until it is run the
project should say so rather than imply the fix worked.

Run it with a key set in the environment:

    uv sync --extra llm
    uv run wayfinder-compare --model claude-opus-5

It calls the API once per held-out item per model, so a run is roughly fifty
requests. `--limit` bounds that while you are checking the plumbing.

Only the crisis split is measured. The other classes are the reference layer's
job, and mixing them in would price a model call for every turn to fix a
problem that only exists on one of them.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wayfinder.eval.corpus import EvalError, LabelledTurn, load_corpus
from wayfinder.eval.gate import EXIT_CANNOT_EVALUATE, EXIT_OK
from wayfinder.eval.metrics import Score, score
from wayfinder.safety.escalation import full_screen
from wayfinder.safety.loader import SafetyDataError, load_lexicon
from wayfinder.safety.models import CrisisLexicon
from wayfinder.safety.taxonomy import QuestionClass

CORPUS = Path(__file__).resolve().parents[3] / "tests" / "corpus"

# Re-exported so callers of this module do not have to know the gate defines
# them. Same convention: 0 pass, 1 verdict of fail, 2 could not evaluate.
__all__ = ["EXIT_CANNOT_EVALUATE", "EXIT_OK", "main", "measure"]


class Measurement:
    __slots__ = ("degraded", "false_positives", "label", "misses", "recall")

    def __init__(
        self,
        label: str,
        recall: Score,
        misses: list[str],
        false_positives: list[str],
        degraded: int,
    ) -> None:
        self.label = label
        self.recall = recall
        self.misses = misses
        self.false_positives = false_positives
        self.degraded = degraded


def measure(
    turns: Sequence[LabelledTurn],
    lexicon: CrisisLexicon,
    *,
    label: str,
    model: Any = None,
) -> Measurement:
    """Recall on the crisis items, plus what it fired on that was not a crisis."""
    expected_crisis = [t for t in turns if t.label is QuestionClass.CRISIS]
    others = [t for t in turns if t.label is not QuestionClass.CRISIS]

    caught, misses, degraded = 0, [], 0
    for turn in expected_crisis:
        result = full_screen(turn.text, lexicon, model=model)
        if result.is_crisis:
            caught += 1
        else:
            misses.append(turn.text)
        if not result.screening_was_complete:
            degraded += 1

    false_positives = []
    for turn in others:
        result = full_screen(turn.text, lexicon, model=model)
        if result.is_crisis:
            false_positives.append(turn.text)
        if not result.screening_was_complete:
            degraded += 1

    return Measurement(
        label=label,
        recall=score(caught, len(expected_crisis)),
        misses=misses,
        false_positives=false_positives,
        degraded=degraded,
    )


def _render(results: Sequence[Measurement], total_others: int) -> str:
    lines = [
        "Crisis screen, held-out split",
        "",
        f"{'configuration':<34} {'recall':<22} {'fired on non-crisis':<22} degraded",
    ]
    for r in results:
        lines.append(
            f"{r.label:<34} {r.recall.render():<22} "
            f"{f'{len(r.false_positives)}/{total_others}':<22} {r.degraded}"
        )
    lines += [
        "",
        "The gate is 0.99 recall with no precision gate. Firing on a turn that "
        "was not a crisis costs somebody a list of helplines they did not need.",
    ]
    for r in results:
        if r.misses:
            lines += ["", f"Missed by {r.label} ({len(r.misses)}):"]
            lines += [f"  {m}" for m in r.misses]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wayfinder-compare",
        description="Measure the crisis screen with and without a model.",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="model id to measure; repeat to compare several",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="only measure the first N items"
    )
    parser.add_argument(
        "--effort",
        default="low",
        help="effort level, or 'none' for models that reject the parameter",
    )
    args = parser.parse_args(argv)

    try:
        corpus = load_corpus(args.corpus)
        lexicon = load_lexicon()
    except (EvalError, SafetyDataError, OSError) as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE

    turns = [t for t in corpus if t.split == "holdout"]
    if args.limit:
        turns = turns[: args.limit]
    others = len([t for t in turns if t.label is not QuestionClass.CRISIS])

    results = [measure(turns, lexicon, label="deterministic only")]

    models = args.model or []
    if models and not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "could not evaluate: ANTHROPIC_API_KEY is not set, so the model "
            "configurations cannot be measured. The deterministic result below "
            "stands on its own.",
            file=sys.stderr,
        )
        print(_render(results, others))
        return EXIT_CANNOT_EVALUATE

    for model_id in models:
        try:
            from wayfinder.safety.llm import AnthropicCrisisScreen

            effort = None if args.effort == "none" else args.effort
            screen = AnthropicCrisisScreen(model=model_id, effort=effort)
        except RuntimeError as exc:
            print(f"could not evaluate: {exc}", file=sys.stderr)
            return EXIT_CANNOT_EVALUATE
        results.append(
            measure(turns, lexicon, label=f"lexicon + {model_id}", model=screen)
        )

    print(_render(results, others))

    # A degraded screen means the measurement itself is incomplete, which is a
    # could-not-evaluate rather than a result.
    if any(r.degraded for r in results[1:]):
        print(
            "\ncould not evaluate: some turns degraded, so the model numbers "
            "above are a floor rather than a measurement.",
            file=sys.stderr,
        )
        return EXIT_CANNOT_EVALUATE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
