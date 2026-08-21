"""Loading the labelled eval splits.

The classifier is treated as a model rather than as code: a labelled corpus, a
committed baseline, and a gate that blocks a merge on regression.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from wayfinder.safety.taxonomy import QuestionClass

# The splits the classifier was tuned against.
DEV_SPLITS: tuple[str, ...] = (
    "crisis",
    "determination",
    "procedural",
    "planning",
    "boundary",
    "adversarial",
    "regression",
)

# Written before the classifier was run against it, evaluated once, never tuned
# against. The dev splits report near-perfect numbers because the classifier was
# fixed against the items it failed on them, which measures the tuning rather
# than the classifier. This is the split that measures anything.
HOLDOUT_SPLIT = "holdout"

# The crisis screen measured on its own, at the size the gate actually needs.
#
# Separate from `holdout` for two reasons. A 0.99 gate at 95 percent confidence
# needs 299 consecutive successes, so a split that can certify it is six times
# the size of the mixed one, and folding it in would drown the forty-seven items
# that measure the other four classes. And the crisis screen is the only layer
# that a model is allowed to touch, so it is the only one worth paying per-turn
# model calls to measure.
CRISIS_HOLDOUT_SPLIT = "crisis-holdout"

# A second one, for the prompt rewrite. `crisis-holdout` found that the V1
# prompt missed 33 turns and those turns were then read, so a prompt written
# afterwards cannot be validated on it: whoever has seen a split's failures
# cannot use it to judge their own fix. This project already burned one holdout
# that way and does not get to do it twice.
#
# So the two have different jobs. `crisis-holdout` is the measurement that found
# the problem and stays as the regression check. `crisis-holdout-v2` is the one
# that says whether a fix worked, and it stays clean until it is spent the same
# way.
CRISIS_HOLDOUT_V2_SPLIT = "crisis-holdout-v2"

# Splits whose whole purpose is the crisis screen. Reported one at a time,
# never pooled: averaging a split a prompt has seen with one it has not is how
# a burned number gets laundered into a clean one.
# A third, for the emphasis hypothesis. v2 has been measured twice and its
# per-category numbers are known, so a prompt written now is written by somebody
# who knows where that split hurts. Each split is spent the same way: it answers
# one question and then it is a regression check.
CRISIS_HOLDOUT_V3_SPLIT = "crisis-holdout-v3"

# A fourth, for per-category screening. Its near-miss half is larger than any
# of the others because the arm under test asks six independent questions per
# turn, so it has six independent chances to say yes wrongly. Precision is the
# number to read first on this one.
CRISIS_HOLDOUT_V4_SPLIT = "crisis-holdout-v4"

CRISIS_HOLDOUT_SPLITS: tuple[str, ...] = (
    CRISIS_HOLDOUT_SPLIT,
    CRISIS_HOLDOUT_V2_SPLIT,
    CRISIS_HOLDOUT_V3_SPLIT,
    CRISIS_HOLDOUT_V4_SPLIT,
)

HOLDOUT_SPLITS: tuple[str, ...] = (HOLDOUT_SPLIT, *CRISIS_HOLDOUT_SPLITS)

SPLITS: tuple[str, ...] = (*DEV_SPLITS, *HOLDOUT_SPLITS)


class EvalError(Exception):
    """The eval corpus could not be read. Reported as could-not-evaluate."""


class LabelledTurn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    label: QuestionClass
    split: str = ""
    # Minimal pairs share a `pair` key. The boundary report uses it to say how
    # many pairs were split correctly on both sides, which is the only number
    # that means anything on that split: getting one side right by escalating
    # everything is not a result.
    pair: str = ""
    # Which of the six crisis categories, on crisis items. Carried so recall can
    # be reported per category: three hundred items with one aggregate number
    # hides a screen that catches every eviction and no trafficking, and those
    # are not the same system.
    category: str = ""


class Split(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    split: str = Field(min_length=1)
    items: tuple[LabelledTurn, ...] = Field(min_length=1)


def load_split(path: Path) -> Split:
    if not path.is_file():
        msg = f"eval split not found: {path}"
        raise EvalError(msg)
    loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"{path.name}: expected a mapping at the top level"
        raise EvalError(msg)
    name = loaded.get("split", path.stem)
    items = loaded.get("items")
    if not isinstance(items, list) or not items:
        msg = f"{path.name}: expected a non-empty `items` list"
        raise EvalError(msg)
    return Split(
        split=name,
        items=tuple(
            LabelledTurn.model_validate({**item, "split": name}) for item in items
        ),
    )


def load_corpus(root: Path) -> tuple[LabelledTurn, ...]:
    """Every split, concatenated. Missing splits are an error, not an absence.

    A split that quietly disappears takes its failures with it, and the gate
    would go green for the wrong reason.
    """
    turns: list[LabelledTurn] = []
    missing = [name for name in SPLITS if not (root / f"{name}.yaml").is_file()]
    if missing:
        msg = f"eval splits missing: {missing}"
        raise EvalError(msg)
    for name in SPLITS:
        turns.extend(load_split(root / f"{name}.yaml").items)
    return tuple(turns)


def by_split(turns: Sequence[LabelledTurn], name: str) -> tuple[LabelledTurn, ...]:
    return tuple(t for t in turns if t.split == name)
