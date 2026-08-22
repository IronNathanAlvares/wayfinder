"""Measure the crisis screen with and without a model, on a held-out split.

This is the tool that answers ADR-0008. The deterministic screen measures 0.138
on the 320-item crisis holdout, and a model is supposed to close that gap.
Whether it does, and by how much, is a measurement rather than an assumption.

Run it with a key set in the environment:

    uv sync --extra llm
    uv run wayfinder-compare --model claude-haiku-4-5 --effort none --save out.json

`--save` is not optional in spirit. A full run costs money and the terminal
scrolls, and the misses are the half of the result worth having.

It calls the API once per item per model, minus the turns the deterministic
lexicon already resolves. The default split is `crisis-holdout-v3`, 500 turns of
which 458 reach the model. `--limit` bounds that while you are checking the
plumbing.

**All three crisis splits have been spent.** v1 and v2 answered two questions
each and v3 answered one, and their per-category numbers are known. A prompt
change measured on any of them now is measured by somebody who knows where they
hurt. The next real question needs a fourth split written to the same protocol.

Bounding it is not free. A limited run measures fewer items, so the confidence
bound it prints is weaker, and the runner prints the bound rather than the bare
recall precisely so that a cheap run cannot be quoted as if it were a full
one.

Only the crisis split is measured. The other classes are the reference layer's
job, and mixing them in would price a model call for every turn to fix a
problem that only exists on one of them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from wayfinder.eval.cache import CachedScreen
from wayfinder.eval.corpus import (
    CRISIS_HOLDOUT_V4_SPLIT,
    HOLDOUT_SPLITS,
    EvalError,
    LabelledTurn,
    load_corpus,
)
from wayfinder.eval.gate import EXIT_CANNOT_EVALUATE, EXIT_OK
from wayfinder.eval.metrics import (
    Score,
    lower_bound,
    mcnemar,
    score,
    trials_needed,
)
from wayfinder.safety.escalation import full_screen
from wayfinder.safety.loader import SafetyDataError, load_lexicon
from wayfinder.safety.models import CrisisLexicon
from wayfinder.safety.repeated import RepeatedScreen
from wayfinder.safety.taxonomy import QuestionClass

CORPUS = Path(__file__).resolve().parents[3] / "tests" / "corpus"

# Re-exported so callers of this module do not have to know the gate defines
# them. Same convention: 0 pass, 1 verdict of fail, 2 could not evaluate.
__all__ = ["EXIT_CANNOT_EVALUATE", "EXIT_OK", "main", "measure"]


class Measurement:
    __slots__ = (
        "by_category",
        "degraded",
        "false_positives",
        "label",
        "misses",
        "recall",
    )

    def __init__(
        self,
        label: str,
        recall: Score,
        misses: list[LabelledTurn],
        false_positives: list[LabelledTurn],
        degraded: int,
        by_category: dict[str, Score],
    ) -> None:
        self.label = label
        self.recall = recall
        self.misses = misses
        self.false_positives = false_positives
        self.degraded = degraded
        self.by_category = by_category

    def as_dict(self) -> dict[str, Any]:
        """The whole result, for `--save`.

        A model run costs real money, and printing the diagnostic to a terminal
        that then scrolls away means paying for it twice. This writes the misses
        to a file so they survive the run.
        """
        return {
            "configuration": self.label,
            "recall": self.recall.value,
            "caught": self.recall.numerator,
            "crisis_items": self.recall.denominator,
            "lower_bound_95": lower_bound(
                self.recall.numerator, self.recall.denominator
            ),
            "degraded": self.degraded,
            "by_category": {
                name: {
                    "recall": s.value,
                    "caught": s.numerator,
                    "of": s.denominator,
                    "lower_bound_95": lower_bound(s.numerator, s.denominator),
                }
                for name, s in sorted(self.by_category.items())
            },
            "missed": [{"text": t.text, "category": t.category} for t in self.misses],
            "fired_on_non_crisis": [
                {"text": t.text, "label": t.label.value} for t in self.false_positives
            ],
        }


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

    caught: list[LabelledTurn] = []
    misses: list[LabelledTurn] = []
    degraded = 0
    for turn in expected_crisis:
        result = full_screen(turn.text, lexicon, model=model)
        (caught if result.is_crisis else misses).append(turn)
        if not result.screening_was_complete:
            degraded += 1

    false_positives = []
    for turn in others:
        result = full_screen(turn.text, lexicon, model=model)
        if result.is_crisis:
            false_positives.append(turn)
        if not result.screening_was_complete:
            degraded += 1

    # Per category, because one aggregate number hides the shape of the failure
    # and the shape is the part that says what to do next.
    hit = {t.text for t in caught}
    by_category = {
        name: score(
            sum(1 for t in expected_crisis if t.category == name and t.text in hit),
            sum(1 for t in expected_crisis if t.category == name),
        )
        for name in sorted({t.category for t in expected_crisis if t.category})
    }

    return Measurement(
        label=label,
        recall=score(len(caught), len(expected_crisis)),
        misses=misses,
        false_positives=false_positives,
        degraded=degraded,
        by_category=by_category,
    )


GATE = 0.99

# The prompt the adapter ships with. Named here so a run with no --prompt says
# which one it measured rather than leaving a reader to guess.
DEFAULT_PROMPT = "v5"

# Not a prompt but an arm, and it belongs on the same flag because that is what
# makes it comparable: one run, the same items, arms named in the same place.
# It carries V4's sections one per call rather than six in one.
PER_CATEGORY = "per-category"

# Repeated sampling of a named prompt, written `union-3:v4`. Not a prompt
# either, and on the same flag for the same reason.
UNION_PREFIX = "union-"


def _is_union(name: str, prompts: Mapping[str, str]) -> tuple[int, str] | None:
    """Parse `union-3:v4` into (3, "v4"), or None if it is not a union arm."""
    if not name.startswith(UNION_PREFIX) or ":" not in name:
        return None
    count, _, base = name[len(UNION_PREFIX) :].partition(":")
    if not count.isdigit() or int(count) < 1 or base not in prompts:
        return None
    return int(count), base


def _render(results: Sequence[Measurement], total_others: int, split: str) -> str:
    lines = [
        f"Crisis screen, {split} split",
        "",
        f"{'configuration':<30} {'recall':<20} {'95% bound':<12} "
        f"{'fired on non-crisis':<21} degraded",
    ]
    for r in results:
        bound = lower_bound(r.recall.numerator, r.recall.denominator)
        lines.append(
            f"{r.label:<30} {r.recall.render():<20} {bound:<12.4f} "
            f"{f'{len(r.false_positives)}/{total_others}':<21} {r.degraded}"
        )
    needed = trials_needed(GATE)
    measured = results[0].recall.denominator
    lines += [
        "",
        f"The gate is {GATE} recall with no precision gate. Firing on a turn "
        "that was not a crisis costs",
        "somebody a list of helplines they did not need.",
        "",
        "Read the bound, not the recall. A recall of 1.000 over twelve items and "
        "over three",
        f"hundred are not the same claim. Certifying {GATE} at 95 percent "
        f"confidence takes {needed}",
        f"consecutive successes, and this run measured {measured}.",
    ]
    # Paired, because they saw the same items. Comparing totals throws the
    # pairing away, and a rewrite whose gains and losses cancel reads as no
    # change unless somebody looks underneath the average.
    if len(results) > 1:
        lines += ["", "Head to head, on the turns where they disagreed:"]
        for i, left in enumerate(results):
            for right in results[i + 1 :]:
                lines.append(
                    "  "
                    + mcnemar(
                        [m.text for m in left.misses],
                        [m.text for m in right.misses],
                        left=left.label,
                        right=right.label,
                    ).render()
                )
        categories = sorted(
            {c for r in results for c in r.by_category if r.by_category}
        )
        for category in categories:
            rows = []
            for i, left in enumerate(results):
                for right in results[i + 1 :]:
                    paired = mcnemar(
                        [m.text for m in left.misses if m.category == category],
                        [m.text for m in right.misses if m.category == category],
                        left=left.label,
                        right=right.label,
                    )
                    if paired.significant:
                        rows.append(f"    {paired.render()}")
            if rows:
                lines += [f"  {category}:", *rows]

    for r in results:
        if not r.by_category:
            continue
        lines += ["", f"{r.label}, by category:"]
        lines += [
            f"  {name:<18} {s.render():<16} "
            f"bound {lower_bound(s.numerator, s.denominator):.3f}"
            for name, s in sorted(r.by_category.items())
        ]

    for r in results:
        if r.misses:
            lines += ["", f"Missed by {r.label} ({len(r.misses)}):"]
            lines += [f"  [{m.category}] {m.text}" for m in r.misses]
        if r.false_positives:
            lines += ["", f"Fired wrongly, {r.label} ({len(r.false_positives)}):"]
            lines += [f"  [{t.label.value}] {t.text}" for t in r.false_positives]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wayfinder-compare",
        description="Measure the crisis screen with and without a model.",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument(
        "--split",
        default=CRISIS_HOLDOUT_V4_SPLIT,
        choices=HOLDOUT_SPLITS,
        help="which held-out split to measure. Only held-out splits are "
        "offered: measuring the dev splits would report the tuning",
    )
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
        "--cache",
        type=Path,
        default=None,
        help="reuse verdicts already recorded here and add new ones as they "
        "arrive, so an interrupted run resumes for the price of what is left. "
        "Keyed on model, prompt and turn together",
    )
    parser.add_argument(
        "--save",
        type=Path,
        default=None,
        help="write the full result, including every miss, to this JSON file. "
        "A model run costs money and a terminal scrolls away",
    )
    parser.add_argument(
        "--effort",
        default="low",
        help="effort level, or 'none' for models that reject the parameter",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=None,
        help="which arm to measure: a system prompt by name, or "
        f"'{PER_CATEGORY}' for one call per category. Repeat to compare arms on "
        "the same items in one run, which is the only way to attribute a "
        "difference to the arm rather than to the day",
    )
    args = parser.parse_args(argv)

    try:
        corpus = load_corpus(args.corpus)
        lexicon = load_lexicon()
    except (EvalError, SafetyDataError, OSError) as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE

    turns = [t for t in corpus if t.split == args.split]
    if args.limit:
        turns = turns[: args.limit]
    others = len([t for t in turns if t.label is not QuestionClass.CRISIS])

    results = [measure(turns, lexicon, label="deterministic only")]

    models = args.model or []

    try:
        from wayfinder.safety.llm import PROMPTS, AnthropicCrisisScreen
    except RuntimeError as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE

    # Before the key check, because a mistyped arm name is wrong whether or not
    # a key is present, and reporting the missing key first sends somebody to
    # fix their environment when the problem is their command line.
    prompts = args.prompt or [DEFAULT_PROMPT]
    available = [*sorted(PROMPTS), PER_CATEGORY, f"{UNION_PREFIX}N:<prompt>"]
    unknown = [
        name
        for name in prompts
        if name not in {*PROMPTS, PER_CATEGORY} and not _is_union(name, PROMPTS)
    ]
    if unknown:
        print(
            f"could not evaluate: no such arm {unknown}. Available: {available}",
            file=sys.stderr,
        )
        return EXIT_CANNOT_EVALUATE

    if models and not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "could not evaluate: ANTHROPIC_API_KEY is not set, so the model "
            "configurations cannot be measured. The deterministic result below "
            "stands on its own.",
            file=sys.stderr,
        )
        print(_render(results, others, args.split))
        return EXIT_CANNOT_EVALUATE

    for model_id in models:
        for prompt_name in prompts:
            try:
                screen: Any
                union = _is_union(prompt_name, PROMPTS)
                if union is not None:
                    samples, base = union
                    inner: list[Any] = [
                        AnthropicCrisisScreen(
                            model=model_id,
                            effort=None if args.effort == "none" else args.effort,
                            system_prompt=PROMPTS[base],
                        )
                        for _ in range(samples)
                    ]
                    if args.cache:
                        # One cache entry per sample. The first uses the empty
                        # salt, so it reuses whatever a single-sample run of the
                        # same prompt already paid for.
                        inner = [
                            CachedScreen(
                                s,
                                path=args.cache,
                                model=model_id,
                                prompt=PROMPTS[base],
                                salt="" if i == 0 else str(i),
                            )
                            for i, s in enumerate(inner)
                        ]
                    # Cached per sample already. Wrapping the union as well
                    # would store the union verdict under a key that hides how
                    # many samples produced it.
                    screen = RepeatedScreen(inner)
                    results.append(
                        measure(
                            turns,
                            lexicon,
                            label=f"{model_id} + {prompt_name}",
                            model=screen,
                        )
                    )
                    for s in inner:
                        if isinstance(s, CachedScreen):
                            s.flush()
                    continue
                if prompt_name == PER_CATEGORY:
                    from wayfinder.safety.per_category import (
                        PROMPTS as CATEGORY_PROMPTS,
                    )
                    from wayfinder.safety.per_category import PerCategoryScreen

                    screen = PerCategoryScreen(model=model_id)
                    # All six, so editing any one of them invalidates the cache.
                    # Keying on the arm's name would let a changed section read
                    # last week's verdicts.
                    cache_key = "".join(
                        CATEGORY_PROMPTS[c] for c in sorted(CATEGORY_PROMPTS, key=str)
                    )
                else:
                    effort = None if args.effort == "none" else args.effort
                    screen = AnthropicCrisisScreen(
                        model=model_id,
                        effort=effort,
                        system_prompt=PROMPTS[prompt_name],
                    )
                    cache_key = PROMPTS[prompt_name]
            except RuntimeError as exc:
                print(f"could not evaluate: {exc}", file=sys.stderr)
                return EXIT_CANNOT_EVALUATE

            cached: CachedScreen | None = None
            if args.cache:
                cached = CachedScreen(
                    screen, path=args.cache, model=model_id, prompt=cache_key
                )
                screen = cached
            try:
                results.append(
                    measure(
                        turns,
                        lexicon,
                        label=f"{model_id} + prompt {prompt_name}",
                        model=screen,
                    )
                )
            finally:
                # Even on the way out of a failure. What was paid for is kept.
                if cached is not None:
                    cached.flush()
            if cached is not None:
                print(
                    f"  {prompt_name}: {cached.calls_made} calls, "
                    f"{cached.hits} reused from cache",
                    file=sys.stderr,
                )

    print(_render(results, others, args.split))
    if args.save:
        args.save.write_text(
            json.dumps(
                {
                    "split": args.split,
                    "crisis_items": len(
                        [t for t in turns if t.label is QuestionClass.CRISIS]
                    ),
                    "non_crisis_items": others,
                    "gate": GATE,
                    "successes_needed_to_certify": trials_needed(GATE),
                    "results": [r.as_dict() for r in results],
                },
                indent=2,
            )
            + chr(10),
            encoding="utf-8",
        )
        print(f"{chr(10)}Full result written to {args.save}")

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
