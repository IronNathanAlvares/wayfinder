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

SPLITS: tuple[str, ...] = (*DEV_SPLITS, HOLDOUT_SPLIT)


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
