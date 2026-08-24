"""The checkpoint deserialisation allowlist, checked against a real full state.

The allowlist in `checkpoint.py` is hand-written, so it can drift: somebody adds
a field to `WayfinderState`, the type it carries is not on the list, and the
checkpoint that a caseworker's paused question lives in stops loading. That
failure would appear days later, in the one path this design cannot afford to
lose.

So these run a turn that populates every branch of the state, checkpoint it, and
assert that what comes back is intact and that nothing was blocked or warned
about on the way.
"""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wayfinder.graph.build import compile_graph
from wayfinder.graph.checkpoint import (
    CHECKPOINTED_TYPES,
    serializer,
    sqlite_checkpointer,
    thread,
)
from wayfinder.graph.nodes import Deps
from wayfinder.graph.state import WayfinderState
from wayfinder.plan.situation import (
    Accommodation,
    Household,
    ProtectionStage,
    Situation,
)

TODAY = date(2026, 8, 24)

# Everything set. A sparse situation would checkpoint fine while leaving half
# the types on the allowlist unexercised, which is exactly the drift this file
# is here to catch.
FULL = Situation(
    arrival_date=date(2026, 8, 1),
    protection_application_date=date(2026, 8, 4),
    protection_stage=ProtectionStage.APPLIED,
    accommodation=Accommodation.HOMELESS,
    household=Household(adults=1, children_ages=(7,)),
    held=frozenset({"document:national_id"}),
    known_absent=frozenset({"document:ppsn"}),
)


def _round_trip(deps: Deps, tmp_path: Path, question: str) -> dict[str, Any]:
    """Write a turn to disk, then read it back through a second saver.

    A second saver rather than the same one, because reusing the first would
    keep whatever it had in memory and prove nothing about deserialisation.
    """
    db = tmp_path / "allowlist.sqlite"
    with sqlite_checkpointer(db) as saver:
        compile_graph(deps, checkpointer=saver).invoke(
            WayfinderState(current_question=question, situation=FULL, today=TODAY),
            thread("t"),
        )
    with sqlite_checkpointer(db) as reopened:
        return dict(
            compile_graph(deps, checkpointer=reopened).get_state(thread("t")).values
        )


def test_a_planning_turn_survives_the_allowlist(deps: Deps, tmp_path: Path) -> None:
    """The widest state this system produces. A plan, its tasks, their
    prerequisites, the conditions on them, and the retrieval spans."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        values = _round_trip(deps, tmp_path, "I have just arrived, what do I do?")

    assert values["plan"] is not None
    assert values["plan"].frontier_order
    assert values["situation"].household.children_ages == (7,)
    assert values["situation"].protection_stage is ProtectionStage.APPLIED
    assert values["answer"] is not None
    assert values["trace"]


def test_a_paused_determination_survives_the_allowlist(
    deps: Deps, tmp_path: Path
) -> None:
    """The one that matters. This is the state a caseworker comes back to."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        values = _round_trip(deps, tmp_path, "Am I entitled to child benefit?")

    assert values["current_question"] == "Am I entitled to child benefit?"
    assert values["classification"] is not None


def test_a_crisis_turn_survives_the_allowlist(deps: Deps, tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        values = _round_trip(deps, tmp_path, "i have nowhere to sleep tonight")

    assert values["crisis"] is not None
    assert values["crisis"].category


def test_the_allowlist_is_explicit_rather_than_permissive() -> None:
    """A permissive serialiser would make every test above pass while the
    security posture the docstring claims was absent."""
    allowed = serializer()._allowed_msgpack_modules
    assert allowed is not True, "the serialiser accepts any type in a checkpoint"
    assert allowed
    assert ("wayfinder.plan.plan", "Plan") in allowed


def test_every_listed_type_is_a_real_class() -> None:
    """Guards the list against a stale entry left behind by a rename, which
    would otherwise sit there looking like coverage it no longer provides."""
    for kind in CHECKPOINTED_TYPES:
        assert isinstance(kind, type)
        assert kind.__module__.startswith("wayfinder.")


@pytest.mark.parametrize("field", ["plan", "situation", "answer", "trace"])
def test_the_state_fields_that_carry_models_are_all_exercised(
    field: str, deps: Deps, tmp_path: Path
) -> None:
    """Named one by one so a new model-carrying field is a visible omission
    rather than a silent one."""
    values = _round_trip(deps, tmp_path, "I have just arrived, what do I do?")
    assert values.get(field) is not None


def test_an_unopenable_database_says_which_one(tmp_path: Path) -> None:
    """SQLite's own message names no path, and this file is what a paused
    caseworker queue lives in."""
    import sqlite3

    missing = tmp_path / "no-such-directory" / "x.sqlite"
    with (
        pytest.raises(sqlite3.OperationalError, match="could not open"),
        sqlite_checkpointer(missing),
    ):
        pass
