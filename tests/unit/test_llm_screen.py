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


# --- the V2 prompt ----------------------------------------------------------
#
# ADR-0008 measured V1 at 0.750 on self-harm, where its entire guidance was
# "thoughts of suicide or self-harm": a description of a state of mind rather
# than of anything a person writes down. V2 is written from the published
# clinical taxonomy instead. These pin the parts of it that are load-bearing,
# so a later edit that quietly drops one is visible.


def test_every_prompt_is_kept_so_a_change_can_be_measured() -> None:
    """A prompt rewrite with no way to run the ones it replaced is an
    assertion, not a result. Every version stays runnable."""
    from wayfinder.safety.llm import (
        PROMPTS,
        SYSTEM_PROMPT_V1,
        SYSTEM_PROMPT_V2,
        SYSTEM_PROMPT_V3,
    )

    for name, prompt in (
        ("v1", SYSTEM_PROMPT_V1),
        ("v2", SYSTEM_PROMPT_V2),
        ("v3", SYSTEM_PROMPT_V3),
    ):
        assert PROMPTS[name] is prompt
    # Through the mapping rather than the constants. The literals are `Final`,
    # so comparing them directly is decided at type-check time and mypy is
    # right to say such an assertion carries no information.
    assert len({PROMPTS[name] for name in PROMPTS}) == len(PROMPTS)


def test_the_shipped_prompt_is_one_that_has_been_measured() -> None:
    """The rule this module states in a comment, enforced.

    Every prompt in the mapping has been measured on a held-out split. Shipping
    one on the strength of expecting it to be better would be the same mistake
    as quoting 1.000 over twelve items.
    """
    from wayfinder.safety.llm import PROMPTS

    assert SYSTEM_PROMPT in PROMPTS.values()
    assert SYSTEM_PROMPT is PROMPTS["v5"], "the shipped prompt changed"


@pytest.mark.parametrize(
    "sign",
    [
        "wishing to be dead",
        "previous attempt",
        "giving away possessions",
        "writing a note",
        "saying goodbye",
        "care for their child",
        "sudden calm",
        "cutting or burning",
        "trapped",
    ],
)
def test_the_prompt_names_the_clinical_warning_signs(sign: str) -> None:
    """Each of these is a documented proximal indicator, and each corresponds to
    a turn V1 was measured missing. They are in the prompt because the taxonomy
    names them, not because the misses did."""
    assert sign in SYSTEM_PROMPT.lower()


def test_the_prompt_says_a_previous_attempt_is_not_history() -> None:
    """The strongest single predictor there is, and the one V1 read as somebody
    describing their past."""
    lowered = SYSTEM_PROMPT.lower()
    assert "strongest" in lowered
    assert "do not read it as history" in lowered


@pytest.mark.parametrize(
    "counter_example",
    ["killing me", "dying to", "my phone died", "grief", "left years ago"],
)
def test_the_prompt_spends_as_much_care_on_what_is_not_a_crisis(
    counter_example: str,
) -> None:
    """The cheap way to buy recall is to fire on every mention of death, and a
    screen that does that is one people learn to scroll past. That failure is
    silent, so the counter-examples are pinned as tightly as the signs."""
    assert counter_example in SYSTEM_PROMPT.lower()


def test_the_prompt_still_covers_the_other_five_categories() -> None:
    """A rewrite aimed at self-harm must not quietly cost the categories that
    were already working."""
    lowered = SYSTEM_PROMPT.lower()
    for term in ("trafficking", "under 18", "medication", "removal", "locked out"):
        assert term in lowered


# --- the V3 revert ----------------------------------------------------------


def test_v3_differs_from_v2_by_exactly_one_line() -> None:
    """The whole claim about V3 is that it changes one thing.

    A revert that quietly altered a second line would make the measurement
    uninterpretable: the difference could not be attributed, and an A/B whose
    arms differ in two ways answers neither question.
    """
    from wayfinder.safety.llm import SYSTEM_PROMPT_V2, SYSTEM_PROMPT_V3

    before = SYSTEM_PROMPT_V2.splitlines()
    after = SYSTEM_PROMPT_V3.splitlines()
    assert len(before) == len(after)
    differing = [(a, b) for a, b in zip(before, after, strict=True) if a != b]
    assert len(differing) == 1
    assert differing[0][0].startswith("- detention:")


def test_v3_restores_the_wording_v1_had() -> None:
    """It is a revert, not a new idea. The phrase it puts back is V1's, and V1
    scored 0.963 on detention where V2 scored 0.778."""
    from wayfinder.safety.llm import (
        SYSTEM_PROMPT_V1,
        SYSTEM_PROMPT_V2,
        SYSTEM_PROMPT_V3,
    )

    phrase = "facing imminent removal from the country"
    assert phrase in SYSTEM_PROMPT_V1
    assert phrase not in SYSTEM_PROMPT_V2
    assert phrase in SYSTEM_PROMPT_V3


def test_v3_keeps_what_v2_usefully_added() -> None:
    """Reverting the whole line would throw away two cases V2 got right."""
    from wayfinder.safety.llm import SYSTEM_PROMPT_V1, SYSTEM_PROMPT_V3

    for added in ("held at a port", "officers present"):
        assert added in SYSTEM_PROMPT_V3
        assert added not in SYSTEM_PROMPT_V1


def test_v3_keeps_the_whole_self_harm_section() -> None:
    """The part of V2 that worked. Self-harm went from 0.481 to 0.685 and none
    of that is being given back to fix detention."""
    from wayfinder.safety.llm import SYSTEM_PROMPT_V3

    lowered = SYSTEM_PROMPT_V3.lower()
    for sign in ("giving away possessions", "sudden calm", "previous attempt"):
        assert sign in lowered


def test_a_prompt_that_stopped_differing_fails_at_import() -> None:
    """If somebody edits V2's detention line, the substitution that builds V3
    stops matching and the two become the same string. That would produce an
    A/B with the same prompt in both arms and a difference of zero that reads
    as a result."""
    from wayfinder.safety import llm

    original = llm.SYSTEM_PROMPT_V3
    try:
        llm.SYSTEM_PROMPT_V3 = llm.SYSTEM_PROMPT_V2  # type: ignore[misc]
        with pytest.raises(RuntimeError, match="identical to V2"):
            llm._one_line_changed()
    finally:
        llm.SYSTEM_PROMPT_V3 = original  # type: ignore[misc]


# --- the emphasis experiment -------------------------------------------------
#
# V5 expands detention only. V4 expands the other four as well. Both are built
# from V2 by substitution, and these check the properties the experiment needs
# to be interpretable: the arms are nested, each differs from its control in
# exactly the intended place, and no substitution silently did nothing.


def test_the_arms_are_nested_so_the_comparison_isolates_one_change() -> None:
    """V2 to V5 changes detention. V5 to V4 changes the other four. Anything
    else differing between them would make a result unattributable."""
    from wayfinder.safety.llm import (
        SYSTEM_PROMPT_V2,
        SYSTEM_PROMPT_V4,
        SYSTEM_PROMPT_V5,
    )

    assert len({SYSTEM_PROMPT_V2, SYSTEM_PROMPT_V5, SYSTEM_PROMPT_V4}) == 3
    assert len(SYSTEM_PROMPT_V2) < len(SYSTEM_PROMPT_V5) < len(SYSTEM_PROMPT_V4)


@pytest.mark.parametrize(
    ("prompt_name", "expected"),
    [
        ("v1", set()),
        ("v2", {"self_harm"}),
        ("v3", {"self_harm"}),
        ("v5", {"self_harm", "detention"}),
        (
            "v4",
            {
                "self_harm",
                "detention",
                "rough_sleeping",
                "violence",
                "child_protection",
                "medical",
            },
        ),
    ],
)
def test_each_arm_expands_exactly_the_categories_it_claims(
    prompt_name: str, expected: set[str]
) -> None:
    """The independent variable, asserted rather than assumed. This is the
    whole experiment: which categories got a section of their own."""
    import re

    from wayfinder.safety.llm import PROMPTS

    categories = {c.value for c in CrisisCategory}
    headings = set(re.findall(r"^## (\w+)$", PROMPTS[prompt_name], re.M))
    assert headings & categories == expected


def test_an_expanded_category_still_appears_in_the_list_as_a_pointer() -> None:
    """Removing the bullet entirely would change two things at once: the
    emphasis and whether the category is listed at all."""
    from wayfinder.safety.llm import SYSTEM_PROMPT_V4

    for category in CrisisCategory:
        assert f"- {category.value}: see below." in SYSTEM_PROMPT_V4


def test_the_negative_guidance_stays_last() -> None:
    """Inserting sections after it would bury the counter-examples under a wall
    of reasons to escalate, which is a second change nobody intended."""
    from wayfinder.safety.llm import PROMPTS

    for name in ("v2", "v4", "v5"):
        prompt = PROMPTS[name]
        assert prompt.index("## What is not a crisis") > prompt.index("## self_harm")
        assert prompt.index("## When you are unsure") > prompt.index(
            "## What is not a crisis"
        )


def test_an_expansion_that_matched_nothing_fails_loudly() -> None:
    """A substitution that silently no-ops produces an arm identical to its
    control, and a difference of zero that reads as a finding."""
    from wayfinder.safety.llm import _expand

    with pytest.raises(RuntimeError, match="not in the prompt being expanded"):
        _expand("a prompt with no bullets in it", ["detention"])


def test_expanding_twice_is_refused_rather_than_silently_ignored() -> None:
    """Applying an expansion to a prompt that already has it would append a
    second copy of the section. The bullet check catches it, because the bullet
    is gone the first time."""
    from wayfinder.safety.llm import SYSTEM_PROMPT_V5, _expand

    with pytest.raises(RuntimeError, match="detention"):
        _expand(SYSTEM_PROMPT_V5, ["detention"])


def test_the_expanded_detention_section_keeps_the_date_instruction_explicit() -> None:
    """The measured failure was detention turns with a named date being read as
    not urgent. This says not to make that judgement, which is the substance of
    the arm rather than its length."""
    from wayfinder.safety.llm import SYSTEM_PROMPT_V4, SYSTEM_PROMPT_V5

    for prompt in (SYSTEM_PROMPT_V4, SYSTEM_PROMPT_V5):
        assert "Do not judge whether the date is close enough to matter" in prompt
