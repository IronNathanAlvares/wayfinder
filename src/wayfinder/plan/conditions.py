"""Situation predicates, evaluated three-valued.

`applies_when` is why the plan cannot be a static checklist: somebody with
status granted has a materially different plan from somebody awaiting a
decision. The original design sketched this as a flat equality map, which
cannot express membership, negation, or anything about a household, and had no
answer at all for a situation field we have not asked about yet.

Every condition therefore answers two questions:

- `evaluate` gives TRUE, FALSE or UNKNOWN.
- `unknowns` gives the facts which, if we learned them, could move the result
  off UNKNOWN. It returns nothing when the result is already decided, and that
  pruning is what makes "ask only what changes the plan" a computation rather
  than a guess.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Annotated, Any, Final, Literal, Union, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator

from wayfinder.plan.refs import ArtefactRef
from wayfinder.plan.situation import Situation
from wayfinder.plan.truth import Truth, conjunction, disjunction

# Situation facts a condition may compare directly. Artefacts are reached through
# `holds` and household shape through `child_aged`, so this list stays small.
COMPARABLE_FIELDS: Final = frozenset(
    {
        "protection_stage",
        "accommodation",
        "arrival_date",
        "protection_application_date",
    }
)


class ConditionBase(BaseModel, abc.ABC):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @abc.abstractmethod
    def _evaluate(self, situation: Situation) -> Truth: ...

    @abc.abstractmethod
    def _raw_unknowns(self, situation: Situation) -> frozenset[str]: ...

    def evaluate(self, situation: Situation) -> Truth:
        return self._evaluate(situation)

    def unknowns(self, situation: Situation) -> frozenset[str]:
        """Facts which could still change this result.

        Empty once the result is decided, because no answer to any question
        would move a TRUE or a FALSE.
        """
        if self._evaluate(situation) is not Truth.UNKNOWN:
            return frozenset()
        return self._raw_unknowns(situation)


class Always(ConditionBase):
    kind: Literal["always"] = "always"

    def _evaluate(self, situation: Situation) -> Truth:
        return Truth.TRUE

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset()


class AllOf(ConditionBase):
    kind: Literal["all"] = "all"
    operands: tuple[Condition, ...]

    def _evaluate(self, situation: Situation) -> Truth:
        return conjunction(o.evaluate(situation) for o in self.operands)

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset().union(*(o.unknowns(situation) for o in self.operands))


class AnyOf(ConditionBase):
    kind: Literal["any"] = "any"
    operands: tuple[Condition, ...]

    def _evaluate(self, situation: Situation) -> Truth:
        return disjunction(o.evaluate(situation) for o in self.operands)

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset().union(*(o.unknowns(situation) for o in self.operands))


class Negation(ConditionBase):
    kind: Literal["not"] = "not"
    operand: Condition

    def _evaluate(self, situation: Situation) -> Truth:
        return self.operand.evaluate(situation).negate()

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return self.operand.unknowns(situation)


def _field_value(situation: Situation, field: str) -> object | None:
    """The comparable form of a situation field. Enums compare by their value."""
    value: object = getattr(situation, field)
    if isinstance(value, Enum):
        return cast("object", value.value)
    return value


class FieldEquals(ConditionBase):
    kind: Literal["field_eq"] = "field_eq"
    field: str
    value: str | bool | int

    def _evaluate(self, situation: Situation) -> Truth:
        actual = _field_value(situation, self.field)
        if actual is None:
            return Truth.UNKNOWN
        return Truth.TRUE if actual == self.value else Truth.FALSE

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset({self.field})


class FieldIn(ConditionBase):
    kind: Literal["field_in"] = "field_in"
    field: str
    options: tuple[str | bool | int, ...]

    def _evaluate(self, situation: Situation) -> Truth:
        actual = _field_value(situation, self.field)
        if actual is None:
            return Truth.UNKNOWN
        return Truth.TRUE if actual in self.options else Truth.FALSE

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset({self.field})


class Holds(ConditionBase):
    """Whether the person has an artefact. `expected: false` inverts it."""

    kind: Literal["holds"] = "holds"
    ref: ArtefactRef
    expected: bool = True

    def _evaluate(self, situation: Situation) -> Truth:
        actual = situation.holds(self.ref)
        return actual if self.expected else actual.negate()

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset({self.ref})


class ChildAged(ConditionBase):
    """Whether the household contains a child in an age range, inclusive."""

    kind: Literal["child_aged"] = "child_aged"
    min_age: int = 0
    max_age: int = 200

    def _evaluate(self, situation: Situation) -> Truth:
        if situation.household is None:
            return Truth.UNKNOWN
        ages = situation.household.children_ages
        return (
            Truth.TRUE
            if any(self.min_age <= age <= self.max_age for age in ages)
            else Truth.FALSE
        )

    def _raw_unknowns(self, situation: Situation) -> frozenset[str]:
        return frozenset({"household"})


_SUGAR_KEYS: Final = frozenset(
    {"always", "all", "any", "not", "field", "holds", "child_aged"}
)


def _tag(raw: object) -> object:
    """Rewrite the YAML sugar into a tagged dict the discriminated union can read.

    The corpus is written by hand, so it uses `{field: x, in: [...]}` rather
    than `{kind: field_in, ...}`. Already-tagged input passes through, which
    keeps `model_dump` round-tripping.
    """
    if not isinstance(raw, Mapping):
        return raw
    if "kind" in raw:
        return raw

    keys = set(raw)
    unknown = keys - _SUGAR_KEYS - {"eq", "in", "is"}
    if unknown:
        msg = f"unrecognised keys in condition: {sorted(unknown)}"
        raise ValueError(msg)

    if "always" in keys:
        return {"kind": "always"}
    if "all" in keys:
        return {"kind": "all", "operands": raw["all"]}
    if "any" in keys:
        return {"kind": "any", "operands": raw["any"]}
    if "not" in keys:
        return {"kind": "not", "operand": raw["not"]}
    if "child_aged" in keys:
        spec = raw["child_aged"]
        if not isinstance(spec, Mapping):
            msg = "child_aged expects a mapping with min and max"
            raise ValueError(msg)
        out: dict[str, Any] = {"kind": "child_aged"}
        if "min" in spec:
            out["min_age"] = spec["min"]
        if "max" in spec:
            out["max_age"] = spec["max"]
        return out
    if "holds" in keys:
        return {
            "kind": "holds",
            "ref": raw["holds"],
            "expected": raw.get("is", True),
        }
    if "field" in keys:
        field = raw["field"]
        if not isinstance(field, str) or field not in COMPARABLE_FIELDS:
            msg = (
                f"condition references {field!r}, which is not comparable. "
                f"Comparable fields are {sorted(COMPARABLE_FIELDS)}."
            )
            raise ValueError(msg)
        if "eq" in keys:
            return {"kind": "field_eq", "field": field, "value": raw["eq"]}
        if "in" in keys:
            options = raw["in"]
            if not isinstance(options, Sequence) or isinstance(options, str):
                msg = "`in` expects a list of values"
                raise ValueError(msg)
            return {"kind": "field_in", "field": field, "options": tuple(options)}
        msg = f"condition on {field!r} needs either `eq` or `in`"
        raise ValueError(msg)

    msg = f"could not interpret condition: {dict(raw)!r}"
    raise ValueError(msg)


Condition = Annotated[
    Union[  # noqa: UP007 - pydantic needs the explicit Union for discrimination
        Always, AllOf, AnyOf, Negation, FieldEquals, FieldIn, Holds, ChildAged
    ],
    Discriminator("kind"),
    BeforeValidator(_tag),
]


class _ConditionHolder(BaseModel):
    """Adapter so a bare condition mapping can be parsed outside a Task."""

    model_config = ConfigDict(frozen=True)

    condition: Condition


def parse_condition(raw: object) -> Condition:
    return _ConditionHolder(condition=raw).condition  # type: ignore[arg-type]


AllOf.model_rebuild()
AnyOf.model_rebuild()
Negation.model_rebuild()
_ConditionHolder.model_rebuild()

ALWAYS: Final[Always] = Always()

__all__ = [
    "ALWAYS",
    "COMPARABLE_FIELDS",
    "AllOf",
    "Always",
    "AnyOf",
    "ChildAged",
    "Condition",
    "ConditionBase",
    "FieldEquals",
    "FieldIn",
    "Holds",
    "Negation",
    "parse_condition",
]
