"""Kleene logic and the condition language.

The truth tables are asserted exhaustively rather than sampled. There are nine
cases per operator and getting one wrong means a plan that quietly asserts
something nobody said.
"""

from __future__ import annotations

from datetime import date

import pytest

from wayfinder.plan.conditions import (
    AllOf,
    Always,
    AnyOf,
    ChildAged,
    FieldEquals,
    FieldIn,
    Holds,
    Negation,
    parse_condition,
)
from wayfinder.plan.situation import (
    Accommodation,
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)
from wayfinder.plan.truth import Truth, conjunction, disjunction

T, F, U = Truth.TRUE, Truth.FALSE, Truth.UNKNOWN


def test_conjunction_truth_table_is_exhaustive() -> None:
    expected = {
        (T, T): T, (T, F): F, (T, U): U,
        (F, T): F, (F, F): F, (F, U): F,
        (U, T): U, (U, F): F, (U, U): U,
    }  # fmt: skip
    for left in (T, F, U):
        for right in (T, F, U):
            assert conjunction((left, right)) == expected[left, right], (left, right)


def test_disjunction_truth_table_is_exhaustive() -> None:
    expected = {
        (T, T): T, (T, F): T, (T, U): T,
        (F, T): T, (F, F): F, (F, U): U,
        (U, T): T, (U, F): U, (U, U): U,
    }  # fmt: skip
    for left in (T, F, U):
        for right in (T, F, U):
            assert disjunction((left, right)) == expected[left, right], (left, right)


def test_negation_leaves_unknown_alone() -> None:
    assert T.negate() is F
    assert F.negate() is T
    assert U.negate() is U


def test_empty_conjunction_is_true_and_empty_disjunction_is_false() -> None:
    """A task with no prerequisites is startable without needing a special case."""
    assert conjunction([]) is T
    assert disjunction([]) is F


def test_unknown_field_is_unknown_not_false() -> None:
    """The failure this three-valued design exists to prevent.

    Under two-valued logic an unasked question reads as a negative answer, and
    the plan silently asserts something about somebody that nobody told it.
    """
    condition = FieldEquals(field="protection_stage", value="applied")
    assert condition.evaluate(Situation()) is U
    assert condition.unknowns(Situation()) == frozenset({"protection_stage"})


def test_decided_conditions_ask_nothing() -> None:
    situation = Situation(protection_stage=ProtectionStage.GRANTED)
    condition = FieldEquals(field="protection_stage", value="applied")
    assert condition.evaluate(situation) is F
    assert condition.unknowns(situation) == frozenset()


def test_disjunction_short_circuits_the_question() -> None:
    """If one branch is already true, the other branch is not worth asking about."""
    situation = Situation(protection_stage=ProtectionStage.APPLIED)
    condition = AnyOf(
        operands=(
            FieldEquals(field="protection_stage", value="applied"),
            Holds(ref="document:anything"),
        )
    )
    assert condition.evaluate(situation) is T
    assert condition.unknowns(situation) == frozenset()


def test_conjunction_asks_about_every_undecided_branch() -> None:
    condition = AllOf(
        operands=(
            Holds(ref="document:one"),
            Holds(ref="document:two"),
        )
    )
    assert condition.unknowns(Situation()) == frozenset(
        {"document:one", "document:two"}
    )


def test_field_in_membership() -> None:
    condition = FieldIn(field="protection_stage", options=("applied", "appeal"))
    assert condition.evaluate(Situation(protection_stage=ProtectionStage.APPEAL)) is T
    assert condition.evaluate(Situation(protection_stage=ProtectionStage.GRANTED)) is F


def test_negation_of_unknown_still_asks() -> None:
    condition = Negation(operand=Holds(ref="document:thing"))
    assert condition.evaluate(Situation()) is U
    assert condition.unknowns(Situation()) == frozenset({"document:thing"})


def test_holds_with_expected_false() -> None:
    situation = Situation(held=frozenset({"document:thing"}))
    assert Holds(ref="document:thing", expected=False).evaluate(situation) is F
    assert Holds(ref="document:thing", expected=True).evaluate(situation) is T


def test_child_aged_is_inclusive_at_both_ends() -> None:
    at_min = Situation(household=Household(adults=1, children_ages=(4,)))
    at_max = Situation(household=Household(adults=1, children_ages=(18,)))
    outside = Situation(household=Household(adults=1, children_ages=(19,)))
    condition = ChildAged(min_age=4, max_age=18)
    assert condition.evaluate(at_min) is T
    assert condition.evaluate(at_max) is T
    assert condition.evaluate(outside) is F


def test_a_household_with_no_children_is_a_known_no() -> None:
    """Not unknown. Somebody who told us their household told us this too."""
    situation = Situation(household=Household(adults=2, children_ages=()))
    assert ChildAged(min_age=4, max_age=18).evaluate(situation) is F


def test_always_is_always() -> None:
    assert Always().evaluate(Situation()) is T


@pytest.mark.parametrize(
    ("raw", "expected_kind"),
    [
        ({"always": True}, "always"),
        ({"field": "accommodation", "eq": "ipas"}, "field_eq"),
        ({"field": "accommodation", "in": ["ipas", "private"]}, "field_in"),
        ({"holds": "document:x"}, "holds"),
        ({"holds": "document:x", "is": False}, "holds"),
        ({"child_aged": {"min": 4, "max": 18}}, "child_aged"),
        ({"not": {"holds": "document:x"}}, "not"),
        ({"all": [{"holds": "document:x"}]}, "all"),
        ({"any": [{"holds": "document:x"}]}, "any"),
    ],
)
def test_yaml_sugar_parses(raw: dict[str, object], expected_kind: str) -> None:
    assert parse_condition(raw).kind == expected_kind


def test_nested_sugar_parses_recursively() -> None:
    condition = parse_condition(
        {
            "all": [
                {"field": "accommodation", "in": ["ipas", "emergency"]},
                {"not": {"holds": "document:permit"}},
            ]
        }
    )
    situation = Situation(
        accommodation=Accommodation.IPAS,
        known_absent=frozenset({"document:permit"}),
    )
    assert condition.evaluate(situation) is T


def test_a_condition_on_an_uncomparable_field_is_rejected_at_load() -> None:
    """Corpus typos become load failures rather than conditions that never fire."""
    with pytest.raises(ValueError, match="not comparable"):
        parse_condition({"field": "favourite_colour", "eq": "blue"})


def test_unrecognised_condition_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="unrecognised keys"):
        parse_condition({"holds": "document:x", "unless": "something"})


def test_a_field_condition_needs_an_operator() -> None:
    with pytest.raises(ValueError, match="needs either"):
        parse_condition({"field": "accommodation"})


def test_conditions_round_trip_through_a_dump() -> None:
    original = parse_condition({"all": [{"holds": "document:x", "is": False}]})
    assert parse_condition(original.model_dump()) == original


def test_a_determination_is_unknown_until_somebody_records_it() -> None:
    assert Situation().holds("determination:thing") is U


def test_a_pending_determination_is_still_unknown() -> None:
    situation = Situation(
        determinations={
            "determination:thing": DeterminationRecord(
                outcome=DeterminationOutcome.PENDING,
                authority="An Authority",
                recorded_on=date(2026, 1, 1),
            )
        }
    )
    assert situation.holds("determination:thing") is U
