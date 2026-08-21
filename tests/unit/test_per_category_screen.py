"""One call per category, driven offline against a fake transport.

The claim this screen rests on is that it carries V4's words and only changes
how they are packaged. That is checkable without a network, and most of what
follows checks it.

The rest is the behaviour that matters when it does not work. Six calls means
six things that can fail, and a screen that answers on five of them is a screen
that quietly stopped checking a category.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from wayfinder.safety.escalation import ModelVerdict, ScreenOutcome, full_screen
from wayfinder.safety.llm import SYSTEM_PROMPT_V4
from wayfinder.safety.loader import load_lexicon
from wayfinder.safety.models import CrisisCategory, CrisisLexicon
from wayfinder.safety.per_category import (
    BOOLEAN_SCHEMA,
    ORDER,
    PROMPTS,
    PerCategoryScreen,
    _split_on_headings,
)


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


class _ByCategory:
    """Answers true for the categories named, false for the rest.

    Keyed on the system prompt, because that is the only thing distinguishing
    one of the six calls from another.
    """

    def __init__(self, fire_on: set[str], fail_on: str | None = None) -> None:
        self._fire = fire_on
        self._fail = fail_on
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        system = kwargs["system"]
        category = next(c.value for c in ORDER if f"\n## {c.value}\n" in system)
        if category == self._fail:
            msg = f"the {category} call failed"
            raise ValueError(msg)
        return _Response(json.dumps({"crisis": category in self._fire}))


class _Client:
    def __init__(self, messages: _ByCategory) -> None:
        self.messages = messages


def _screen(fire_on: set[str], fail_on: str | None = None) -> PerCategoryScreen:
    return PerCategoryScreen(_Client(_ByCategory(fire_on, fail_on)), model="m")


@pytest.fixture(scope="module")
def lexicon() -> CrisisLexicon:
    return load_lexicon()


# --- the words are V4's -------------------------------------------------------


def test_every_category_prompt_carries_v4s_section_unchanged() -> None:
    """The load-bearing claim. If the sections were retyped rather than lifted,
    this experiment would be comparing two different sets of words and calling
    the difference packaging."""
    sections = _split_on_headings(SYSTEM_PROMPT_V4)
    for category in CrisisCategory:
        assert sections[category.value] in PROMPTS[category]


def test_every_category_prompt_carries_v4s_negative_guidance() -> None:
    """Six independent chances to say yes is a precision risk, and the
    counter-examples are what holds it. Dropping them from the per-category
    prompts would buy recall by making the screen louder."""
    sections = _split_on_headings(SYSTEM_PROMPT_V4)
    for category in CrisisCategory:
        assert sections["What is not a crisis"] in PROMPTS[category]


def test_a_category_prompt_carries_only_its_own_section() -> None:
    """The whole point. A prompt holding two categories is not a per-category
    prompt, and the competition this is meant to remove would still be there."""
    sections = _split_on_headings(SYSTEM_PROMPT_V4)
    for category in CrisisCategory:
        others = [c for c in CrisisCategory if c is not category]
        for other in others:
            assert sections[other.value] not in PROMPTS[category]


def test_there_is_a_prompt_for_every_category_and_no_others() -> None:
    assert set(PROMPTS) == set(CrisisCategory)
    assert set(ORDER) == set(CrisisCategory)


def test_building_the_prompts_fails_loudly_if_v4_loses_a_section() -> None:
    """V4 is edited by hand. If a section is renamed, this screen must not
    quietly ship with five categories."""
    from wayfinder.safety import per_category

    original = per_category._V4_SECTIONS
    try:
        per_category._V4_SECTIONS = {  # type: ignore[misc]
            k: v for k, v in original.items() if k != "detention"
        }
        with pytest.raises(RuntimeError, match="missing sections"):
            per_category._build_prompts()
    finally:
        per_category._V4_SECTIONS = original  # type: ignore[misc]


def test_the_schema_is_a_closed_boolean() -> None:
    """No category field, because the call already fixes the category. Asking
    for one would invite an answer to a question it was not given options for."""
    assert BOOLEAN_SCHEMA["additionalProperties"] is False
    assert BOOLEAN_SCHEMA["required"] == ["crisis"]
    assert set(BOOLEAN_SCHEMA["properties"]) == {"crisis"}


# --- what it does -------------------------------------------------------------


def test_it_asks_every_category_exactly_once() -> None:
    screen = _screen(set())
    screen("what time does the office open")

    systems = [c["system"] for c in screen._client.messages.calls]
    assert len(systems) == len(CrisisCategory)
    assert len(set(systems)) == len(CrisisCategory)


def test_one_category_firing_is_enough() -> None:
    verdict, category = _screen({"detention"})("the letter says thursday")
    assert verdict is ModelVerdict.CRISIS
    assert category is CrisisCategory.DETENTION


def test_no_category_firing_is_no_opinion() -> None:
    verdict, category = _screen(set())("how do i register with a gp")
    assert verdict is ModelVerdict.NO_OPINION
    assert category is None


def test_the_reported_category_is_stable_when_several_fire() -> None:
    """A turn can be two emergencies at once. Reporting whichever call returned
    first would make the answer depend on thread scheduling, and the directory
    entry somebody sees would change between identical runs.
    """
    for _ in range(5):
        _, category = _screen({"detention", "self_harm", "medical"})("anything")
        assert category is CrisisCategory.SELF_HARM


def test_the_order_puts_the_least_recoverable_category_first() -> None:
    """When a turn is more than one thing, the category shown decides which
    number somebody is given. Self-harm leads because it is the one that may
    not be asked twice."""
    assert ORDER[0] is CrisisCategory.SELF_HARM
    assert ORDER[-1] is CrisisCategory.ROUGH_SLEEPING


# --- what it does when it breaks ---------------------------------------------


def test_one_failed_category_fails_the_whole_screen() -> None:
    """Answering on five of six would be a screen that stopped checking a
    category without saying so, which is worse than one that is visibly off."""
    with pytest.raises(ValueError, match="the self_harm call failed"):
        _screen({"detention"}, fail_on="self_harm")("anything")


def test_a_failure_surfaces_as_a_degraded_screen_rather_than_a_clearance(
    lexicon: CrisisLexicon,
) -> None:
    result = full_screen(
        "how do i apply for a ppsn",
        lexicon,
        model=_screen(set(), fail_on="medical"),
    )
    assert result.outcome is ScreenOutcome.DEGRADED
    assert not result.screening_was_complete


def test_a_failure_in_a_category_that_would_not_have_fired_still_degrades() -> None:
    """The screen cannot know what the failed call would have said, and
    assuming it would have said no is the assumption that makes a degraded
    screen dangerous."""
    with pytest.raises(ValueError, match="failed"):
        _screen(set(), fail_on="rough_sleeping")("what time does the office open")


def test_the_lexicon_still_runs_first_and_the_model_cannot_clear_it(
    lexicon: CrisisLexicon,
) -> None:
    """The property the whole design rests on, checked against this screen too.
    Six calls that can only add a detection still only add."""
    never_fires = _screen(set())
    result = full_screen("i want to kill myself", lexicon, model=never_fires)

    assert result.is_crisis
    assert result.outcome is ScreenOutcome.LEXICON
    assert never_fires._client.messages.calls == [], "the model was consulted at all"
