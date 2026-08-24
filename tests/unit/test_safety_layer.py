"""The safety layer, including the parts that are claims rather than behaviour.

The claims under test here:

- No model runs before the crisis verdict.
- Nothing can clear a lexicon hit.
- A crisis response is looked up, never composed.
- A crisis response is terminal.
- Ambiguity resolves to DETERMINATION.
- Every refusal names somebody who can help.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from wayfinder.safety import refusals
from wayfinder.safety.classify import classify
from wayfinder.safety.crisis import respond, screen
from wayfinder.safety.escalation import (
    ModelVerdict,
    ScreenOutcome,
    full_screen,
)
from wayfinder.safety.loader import (
    SafetyDataError,
    load_directory,
    load_lexicon,
)
from wayfinder.safety.models import (
    CrisisCategory,
    CrisisDirectory,
    CrisisLexicon,
    CrisisPattern,
)
from wayfinder.safety.normalise import normalise
from wayfinder.safety.taxonomy import Layer, QuestionClass

TODAY = date(2026, 8, 24)


@pytest.fixture(scope="module")
def lexicon() -> CrisisLexicon:
    return load_lexicon(today=TODAY)


@pytest.fixture(scope="module")
def directory() -> CrisisDirectory:
    return load_directory(today=TODAY)


# --- normalisation ----------------------------------------------------------


def test_normalisation_is_idempotent() -> None:
    """NFR-3: identical output for identical input, always."""
    text = "I can’t sleep — I’m scared"
    once = normalise(text)
    assert normalise(once) == once


def test_curly_quotes_and_straight_quotes_normalise_together() -> None:
    """Phone keyboards produce curly quotes. A matcher that treats them as
    different strings misses every turn typed on a phone."""
    assert normalise("I can’t cope") == normalise("I can't cope")


def test_contractions_are_expanded_so_the_lexicon_writes_one_form() -> None:
    assert "cannot" in normalise("I can't go on")


def test_zero_width_characters_are_stripped() -> None:
    assert normalise("kill​myself") == "killmyself"


# --- the crisis screen ------------------------------------------------------


def test_word_boundaries_stop_the_screen_crying_wolf(lexicon: CrisisLexicon) -> None:
    """ "kill" must not fire on "skills". A screen that fires on ordinary
    sentences trains people to ignore it, which costs the lives it protects."""
    assert screen("I want to improve my skills", lexicon) is None
    assert screen("I am taking a course in social care", lexicon) is None


def test_the_screen_finds_the_obvious_cases(lexicon: CrisisLexicon) -> None:
    for text, expected in [
        ("I have nowhere to sleep tonight", CrisisCategory.ROUGH_SLEEPING),
        ("I want to kill myself", CrisisCategory.SELF_HARM),
        ("my husband is beating me", CrisisCategory.VIOLENCE),
        ("I need an ambulance", CrisisCategory.MEDICAL),
        ("I am an unaccompanied minor", CrisisCategory.CHILD_PROTECTION),
        ("I am being deported tomorrow", CrisisCategory.DETENTION),
    ]:
        hit = screen(text, lexicon)
        assert hit is not None, text
        assert hit.category is expected, text


def test_the_most_urgent_category_wins_when_two_match(
    lexicon: CrisisLexicon,
) -> None:
    """Somebody describing violence and homelessness in one sentence needs the
    violence numbers first."""
    hit = screen("he is beating me and I have nowhere to sleep", lexicon)
    assert hit is not None
    assert hit.category is CrisisCategory.VIOLENCE


def test_the_screen_is_deterministic(lexicon: CrisisLexicon) -> None:
    text = "I have nowhere to go tonight"
    assert [screen(text, lexicon) for _ in range(20)].count(screen(text, lexicon)) == 20


# --- the crisis response ----------------------------------------------------


def test_a_crisis_response_is_looked_up_and_never_composed(
    lexicon: CrisisLexicon, directory: CrisisDirectory
) -> None:
    """FR-S3. Every phone number in the output must appear verbatim in a dated
    directory entry. A model cannot mis-type a number it looked up."""
    known = {e.contact for s in directory.sections for e in s.entries}
    # Spaces only, not \s: a number must not be allowed to span a line break,
    # or the test quietly stops checking anything.
    number = re.compile(r"\b(?:\d[\d ]{4,}\d|\d{3})\b")
    for category in CrisisCategory:
        hit = screen(_example_for(category), lexicon)
        assert hit is not None, category
        text = respond(hit, directory)
        for candidate in number.findall(text):
            assert any(candidate in contact for contact in known), (
                f"{candidate!r} in the {category.value} response is not in the directory"
            )


def _example_for(category: CrisisCategory) -> str:
    return {
        CrisisCategory.ROUGH_SLEEPING: "I have nowhere to sleep tonight",
        CrisisCategory.VIOLENCE: "my partner is threatening me",
        CrisisCategory.CHILD_PROTECTION: "I am an unaccompanied minor",
        CrisisCategory.MEDICAL: "I need an ambulance",
        CrisisCategory.SELF_HARM: "I want to kill myself",
        CrisisCategory.DETENTION: "I am being deported tomorrow",
    }[category]


def test_every_crisis_response_carries_opening_hours(
    lexicon: CrisisLexicon, directory: CrisisDirectory
) -> None:
    """The Dublin homeless freephone closes at 10pm and "nowhere to sleep
    tonight" is mostly typed after that. A number without its hours sends
    somebody to a phone nobody answers."""
    for section in directory.sections:
        for entry in section.entries:
            assert entry.hours
        hit = screen(_example_for(section.category), lexicon)
        assert hit is not None, section.category
        text = respond(hit, directory)
        for entry in section.entries:
            assert entry.hours in text


def test_every_section_leads_with_a_line_that_names_what_to_do(
    directory: CrisisDirectory,
) -> None:
    for section in directory.sections:
        assert len(section.lead_line) > 30


def test_the_emergency_number_appears_in_every_life_threatening_section(
    directory: CrisisDirectory,
) -> None:
    for category in (
        CrisisCategory.SELF_HARM,
        CrisisCategory.MEDICAL,
        CrisisCategory.VIOLENCE,
        CrisisCategory.CHILD_PROTECTION,
    ):
        contacts = [e.contact for e in directory.section(category).entries]
        assert any("999" in c for c in contacts), category


# --- the layered classifier -------------------------------------------------


def test_crisis_wins_over_everything_downstream(lexicon: CrisisLexicon) -> None:
    """A turn that is both a crisis and a determination is a crisis. Somebody
    with nowhere to sleep does not need an entitlements discussion."""
    result = classify(
        "Am I entitled to anything? I have nowhere to sleep tonight",
        lexicon=lexicon,
    )
    assert result.question_class is QuestionClass.CRISIS
    assert result.layer is Layer.CRISIS_LEXICON


def test_no_model_can_override_a_crisis(lexicon: CrisisLexicon) -> None:
    """The layer 3 hook is never reached once the lexicon has fired, so there is
    no arrangement of a model response that clears a crisis."""
    calls: list[str] = []

    def spy(text: str) -> QuestionClass | None:
        calls.append(text)
        return QuestionClass.PROCEDURAL

    result = classify("I want to kill myself", lexicon=lexicon, remainder=spy)
    assert result.question_class is QuestionClass.CRISIS
    assert calls == [], "layer 3 was consulted on a crisis turn"


def test_a_layer_three_model_cannot_declare_a_crisis(
    lexicon: CrisisLexicon,
) -> None:
    """The crisis path is a deterministic screen and a static directory. A model
    reaching it would put generated text into somebody's emergency."""

    def rogue(text: str) -> QuestionClass | None:
        return QuestionClass.CRISIS

    result = classify("what is a PPS number", lexicon=lexicon, remainder=rogue)
    assert result.question_class is not QuestionClass.CRISIS


def test_ambiguity_resolves_to_determination(lexicon: CrisisLexicon) -> None:
    """FR-S7. The tie-break is what makes the default safe."""

    def no_opinion(text: str) -> QuestionClass | None:
        return None

    result = classify("mmmm", lexicon=lexicon, remainder=no_opinion)
    assert result.question_class is QuestionClass.DETERMINATION
    assert result.layer is Layer.TIE_BREAK


def test_the_determination_markers_run_without_a_model(
    lexicon: CrisisLexicon,
) -> None:
    """FR-S6. The marker corpus must pass with no model available at all."""

    def unavailable(text: str) -> QuestionClass | None:  # pragma: no cover
        raise AssertionError("layer 3 should not have been reached")

    for text in (
        "Am I entitled to the daily expenses allowance?",
        "Do I qualify for a medical card?",
        "Will mine be refused?",
        "Are my documents enough?",
    ):
        result = classify(text, lexicon=lexicon, remainder=unavailable)
        assert result.question_class is QuestionClass.DETERMINATION, text
        assert result.layer is Layer.DETERMINATION_MARKERS


def test_the_classification_records_which_layer_decided(
    lexicon: CrisisLexicon,
) -> None:
    """A class assigned by the tie-break is a different thing from one a marker
    was certain about, and a bad refusal has to be reviewable."""
    assert classify("Do I qualify?", lexicon=lexicon).reason
    assert classify("I want to die", lexicon=lexicon).reason


def test_a_crisis_classification_always_carries_its_hit(
    lexicon: CrisisLexicon,
) -> None:
    result = classify("I have nowhere to sleep tonight", lexicon=lexicon)
    assert result.crisis is not None
    assert result.crisis.matched


# --- the monotonic model screen, ADR-0008 ----------------------------------


def test_the_model_screen_cannot_clear_a_lexicon_hit(
    lexicon: CrisisLexicon,
) -> None:
    """The claim ADR-0008 rests on. The model is never consulted once the
    lexicon has fired, so it has no path to a non-crisis verdict."""
    consulted: list[str] = []

    def model(text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        consulted.append(text)
        return (ModelVerdict.NO_OPINION, None)

    result = full_screen("I want to kill myself", lexicon, model=model)
    assert result.is_crisis
    assert result.outcome is ScreenOutcome.LEXICON
    assert consulted == []


def test_the_model_screen_can_add_a_crisis_the_lexicon_missed(
    lexicon: CrisisLexicon,
) -> None:
    def model(text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        return (ModelVerdict.CRISIS, CrisisCategory.ROUGH_SLEEPING)

    result = full_screen(
        "they say the plane is booked for friday", lexicon, model=model
    )
    assert result.is_crisis
    assert result.outcome is ScreenOutcome.MODEL


def test_a_failing_model_degrades_visibly_rather_than_silently(
    lexicon: CrisisLexicon,
) -> None:
    """A crisis screen that stops working without saying so is worse than one
    that is visibly off, because the first one is still trusted."""

    def broken(text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        msg = "the API is down"
        raise RuntimeError(msg)

    result = full_screen("what is a PPS number", lexicon, model=broken)
    assert not result.is_crisis
    assert not result.screening_was_complete


def test_no_model_configured_is_still_a_complete_screen(
    lexicon: CrisisLexicon,
) -> None:
    result = full_screen("what is a PPS number", lexicon)
    assert result.screening_was_complete


def test_the_degraded_notice_carries_real_numbers(
    directory: CrisisDirectory,
) -> None:
    from wayfinder.safety.escalation import DEGRADED_NOTICE

    known = {e.contact for s in directory.sections for e in s.entries}
    for fragment in ("999", "116 123", "1800 247 247", "1800 341 900", "1800 707 707"):
        assert fragment in DEGRADED_NOTICE
        assert any(fragment in c for c in known), fragment


# --- refusals ---------------------------------------------------------------


def test_every_refusal_names_somebody_who_can_help() -> None:
    """FR-S8. A refusal that leaves somebody stuck is a failure, not a safety
    win: they go and ask a system with no such scruples instead."""
    named = (
        "caseworker",
        "Legal Aid Board",
        "Irish Refugee Council",
        "GP",
        "solicitor",
        "Citizens Information",
    )
    for template in refusals.ALL_TEMPLATES:
        assert any(name in template for name in named), template[:60]


def test_no_refusal_hedges_about_entitlement() -> None:
    """ "You may be entitled to X" is still an entitlement claim, and it is worse
    than silence because it sounds like permission to plan around it."""
    for template in refusals.ALL_TEMPLATES:
        lowered = template.lower()
        for phrase in (
            "you may be entitled",
            "you might be entitled",
            "you probably qualify",
            "you may qualify",
            "you should be eligible",
            "likely",
        ):
            assert phrase not in lowered, template[:60]


def test_no_refusal_is_cheerful() -> None:
    """Read as somebody who has just been refused. No exclamation marks."""
    for template in refusals.ALL_TEMPLATES:
        assert "!" not in template


# --- loading and staleness --------------------------------------------------


def test_the_shipped_lexicon_and_directory_load(
    lexicon: CrisisLexicon, directory: CrisisDirectory
) -> None:
    assert lexicon.categories
    assert directory.sections


def test_every_crisis_category_has_somewhere_to_send_people(
    directory: CrisisDirectory,
) -> None:
    for category in CrisisCategory:
        assert directory.section(category).entries


def test_a_stale_lexicon_raises_rather_than_downgrading(tmp_path: Path) -> None:
    """Stricter than the corpus rule on purpose. A stale procedure wastes a
    journey; a stale helpline is dialled during an emergency."""
    source = (Path(__file__).parents[2] / "src/wayfinder/safety/data").resolve()
    (tmp_path / "crisis_lexicon.yaml").write_text(
        (source / "crisis_lexicon.yaml")
        .read_text(encoding="utf-8")
        .replace("reviewed_on: 2026-08-18", "reviewed_on: 2020-01-01"),
        encoding="utf-8",
    )
    with pytest.raises(SafetyDataError, match="operational alarm"):
        load_lexicon(tmp_path, today=TODAY)


def test_a_lexicon_reviewed_in_the_future_is_a_typo(tmp_path: Path) -> None:
    source = (Path(__file__).parents[2] / "src/wayfinder/safety/data").resolve()
    (tmp_path / "crisis_lexicon.yaml").write_text(
        (source / "crisis_lexicon.yaml")
        .read_text(encoding="utf-8")
        .replace("reviewed_on: 2026-08-18", "reviewed_on: 2099-01-01"),
        encoding="utf-8",
    )
    with pytest.raises(SafetyDataError, match="typo"):
        load_lexicon(tmp_path, today=TODAY)


def test_missing_safety_data_raises(tmp_path: Path) -> None:
    with pytest.raises(SafetyDataError, match="not found"):
        load_lexicon(tmp_path, today=TODAY)


def test_the_shipped_data_is_within_its_review_window() -> None:
    """The one that will eventually go red on its own, which is the point."""
    lex = load_lexicon()
    assert lex.reviewed_on >= TODAY - timedelta(days=180)


def test_a_pattern_with_word_boundaries_does_not_match_inside_a_word() -> None:
    pattern = CrisisPattern(phrase="kill").compile()
    assert pattern.search("kill") is not None
    assert pattern.search("skills") is None


def test_a_regex_pattern_is_used_as_written() -> None:
    pattern = CrisisPattern(phrase=r"no\s+bed", regex=True).compile()
    assert pattern.search("no  bed") is not None
