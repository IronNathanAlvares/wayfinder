"""The model crisis screen, driven end to end against a fake transport.

No network and no key. The client is injected, so every path through the
adapter is reachable offline: the schema it sends, the responses it accepts,
and every way it can fail.

The failure paths matter more than the happy one. This screen runs before
anything else on every turn, and the question that decides whether it is safe
to depend on a model here is not "what does it do when it works" but "what
happens when it does not".
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from wayfinder.safety.escalation import ModelVerdict, ScreenOutcome, full_screen
from wayfinder.safety.llm import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    AnthropicCrisisScreen,
)
from wayfinder.safety.loader import load_lexicon
from wayfinder.safety.models import CrisisCategory, CrisisLexicon


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.messages = _FakeMessages(outcome)


def _replying(payload: dict[str, Any]) -> _FakeClient:
    return _FakeClient(_Response(json.dumps(payload)))


@pytest.fixture(scope="module")
def lexicon() -> CrisisLexicon:
    return load_lexicon()


# --- the request it builds --------------------------------------------------


def test_the_response_schema_is_closed() -> None:
    """A model that invents a category produces a validation failure, not a guess."""
    assert RESPONSE_SCHEMA["additionalProperties"] is False
    assert set(RESPONSE_SCHEMA["required"]) == {"crisis", "category"}
    allowed = set(RESPONSE_SCHEMA["properties"]["category"]["enum"])
    assert allowed == {c.value for c in CrisisCategory} | {"none"}


def test_every_crisis_category_is_reachable_through_the_schema() -> None:
    """A category the lexicon can fire but the model cannot name would be a
    silent hole in the half of the screen that catches novel phrasing."""
    allowed = set(RESPONSE_SCHEMA["properties"]["category"]["enum"])
    for category in CrisisCategory:
        assert category.value in allowed


def test_the_request_constrains_the_output_and_names_the_model() -> None:
    client = _replying({"crisis": False, "category": "none"})
    AnthropicCrisisScreen(client)("what is a PPS number")
    sent = client.messages.calls[0]
    assert sent["model"] == DEFAULT_MODEL
    assert sent["output_config"]["format"]["schema"] == RESPONSE_SCHEMA
    assert sent["output_config"]["effort"] == DEFAULT_EFFORT
    assert sent["system"] == SYSTEM_PROMPT
    assert sent["messages"] == [{"role": "user", "content": "what is a PPS number"}]


def test_the_prompt_names_every_category() -> None:
    for category in CrisisCategory:
        assert category.value in SYSTEM_PROMPT


def test_the_prompt_states_the_asymmetry_rather_than_assuming_it() -> None:
    """The model has to be told that the two errors do not cost the same,
    because nothing else in the request says so."""
    assert "false positive" in SYSTEM_PROMPT.lower()
    assert "false negative" in SYSTEM_PROMPT.lower()


def test_the_prompt_distinguishes_asking_about_a_rule_from_being_in_it() -> None:
    """The same distinction the determination markers draw, in the crisis path:
    "what happens if somebody is evicted" is a question, not an emergency."""
    assert "evicted" in SYSTEM_PROMPT


# --- reading the response ---------------------------------------------------


def test_a_negative_verdict_is_no_opinion_not_a_clearance() -> None:
    """The model saying nothing is wrong is not the same as it saying the turn
    is safe. `NO_OPINION` is the only negative it can express, by design."""
    screen = AnthropicCrisisScreen(_replying({"crisis": False, "category": "none"}))
    assert screen("what documents do I need") == (ModelVerdict.NO_OPINION, None)


def test_a_positive_verdict_carries_its_category() -> None:
    screen = AnthropicCrisisScreen(
        _replying({"crisis": True, "category": "rough_sleeping"})
    )
    assert screen("the hostel say i must go before lunch") == (
        ModelVerdict.CRISIS,
        CrisisCategory.ROUGH_SLEEPING,
    )


def test_a_crisis_with_no_category_still_escalates() -> None:
    """Escalating without a category beats discarding the verdict over a
    missing field."""
    screen = AnthropicCrisisScreen(_replying({"crisis": True, "category": "none"}))
    verdict, category = screen("something is very wrong")
    assert verdict is ModelVerdict.CRISIS
    assert category is None


@pytest.mark.parametrize(
    "payload",
    [
        {"crisis": True, "category": "invented_category"},
        {"category": "medical"},
        {},
    ],
)
def test_a_response_outside_the_schema_raises(payload: dict[str, Any]) -> None:
    """Raising becomes a visibly degraded screen upstream. Guessing would
    become a silent miss."""
    screen = AnthropicCrisisScreen(_replying(payload))
    with pytest.raises((ValueError, KeyError)):
        screen("anything")


def test_unparseable_text_raises() -> None:
    screen = AnthropicCrisisScreen(_FakeClient(_Response("I think this is fine?")))
    with pytest.raises(json.JSONDecodeError):
        screen("anything")


def test_a_refusal_raises_rather_than_reading_as_clear() -> None:
    """A model that declined to screen has not screened. Reading that as "no
    crisis" would turn a refusal into a clearance."""
    screen = AnthropicCrisisScreen(_FakeClient(_Response("", stop_reason="refusal")))
    with pytest.raises(ValueError, match="declined to screen"):
        screen("anything")


def test_a_response_with_no_text_block_raises() -> None:
    empty = _Response("")
    empty.content = []
    with pytest.raises(ValueError, match="no text block"):
        AnthropicCrisisScreen(_FakeClient(empty))("anything")


# --- how it composes with the deterministic screen --------------------------


def test_the_model_is_never_consulted_once_the_lexicon_fires(
    lexicon: CrisisLexicon,
) -> None:
    """ADR-0008's whole claim. The model has no path to a verdict on a turn the
    lexicon already caught, so it cannot clear one however it answers."""
    client = _replying({"crisis": False, "category": "none"})
    result = full_screen(
        "I have nowhere to sleep tonight",
        lexicon,
        model=AnthropicCrisisScreen(client),
    )
    assert result.is_crisis
    assert result.outcome is ScreenOutcome.LEXICON
    assert client.messages.calls == []


def test_the_model_catches_what_the_lexicon_missed(lexicon: CrisisLexicon) -> None:
    """The turn that motivated ADR-0008: an ordinary sentence with no keyword."""
    text = "manager say i must go before lunch, i have small baby"
    assert full_screen(text, lexicon).hit is None

    escalated = full_screen(
        text,
        lexicon,
        model=AnthropicCrisisScreen(
            _replying({"crisis": True, "category": "rough_sleeping"})
        ),
    )
    assert escalated.is_crisis
    assert escalated.outcome is ScreenOutcome.MODEL


def test_an_api_failure_degrades_visibly(lexicon: CrisisLexicon) -> None:
    class TransportError(Exception):
        pass

    result = full_screen(
        "manager say i must go before lunch",
        lexicon,
        model=AnthropicCrisisScreen(_FakeClient(TransportError("connection reset"))),
    )
    assert not result.is_crisis
    assert not result.screening_was_complete


def test_a_timeout_degrades_rather_than_hanging(lexicon: CrisisLexicon) -> None:
    """This runs before anything else on every turn. A screen that hangs delays
    somebody in an emergency."""
    result = full_screen(
        "anything",
        lexicon,
        model=AnthropicCrisisScreen(_FakeClient(TimeoutError("timed out"))),
    )
    assert not result.screening_was_complete


def test_a_malformed_response_degrades_rather_than_clearing(
    lexicon: CrisisLexicon,
) -> None:
    """The end-to-end version of the schema tests: a model that returns nonsense
    must not read as a clearance."""
    result = full_screen(
        "manager say i must go before lunch",
        lexicon,
        model=AnthropicCrisisScreen(_FakeClient(_Response("not json"))),
    )
    assert not result.is_crisis
    assert not result.screening_was_complete


def test_the_deterministic_build_needs_no_model_at_all(
    lexicon: CrisisLexicon,
) -> None:
    """`plan/` and the deterministic layers must stay installable and usable
    without the anthropic package. Nothing here imports it."""
    result = full_screen("I want to kill myself", lexicon)
    assert result.is_crisis
    assert result.outcome is ScreenOutcome.LEXICON
