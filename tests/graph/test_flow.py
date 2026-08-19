"""Whole turns, end to end, one per route out of classification.

The topology tests prove which paths exist. These check what a person actually
receives when they walk one, which is a different question: a graph can be
correctly shaped and still produce an answer nobody can use.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from wayfinder.graph.build import compile_graph
from wayfinder.graph.nodes import Deps
from wayfinder.graph.state import Answer, WayfinderState
from wayfinder.plan.situation import (
    Accommodation,
    Household,
    ProtectionStage,
    Situation,
)
from wayfinder.safety.taxonomy import QuestionClass

TODAY = date(2026, 8, 18)
NOTHING_KNOWN = Situation()

AMARA = Situation(
    arrival_date=date(2026, 8, 1),
    protection_application_date=date(2026, 8, 4),
    protection_stage=ProtectionStage.APPLIED,
    accommodation=Accommodation.HOMELESS,
    household=Household(adults=1, children_ages=(7,)),
    held=frozenset(
        {
            "document:national_id",
            "document:temporary_residence_certificate",
            "document:asylum_application_letter",
        }
    ),
    known_absent=frozenset({"document:ppsn", "status:ipas_accommodation"}),
)


@pytest.fixture
def run(deps: Deps) -> Any:
    graph = compile_graph(deps)

    def go(question: str, situation: Situation = NOTHING_KNOWN) -> dict[str, Any]:
        return dict(
            graph.invoke(
                WayfinderState(
                    current_question=question, situation=situation, today=TODAY
                )
            )
        )

    return go


def test_a_crisis_turn_gets_a_phone_number_and_nothing_else(run: Any) -> None:
    """Terminal, looked up, no plan attached.

    Somebody who says they have nowhere to sleep tonight needs a number, not a
    forty-step onboarding plan.
    """
    result = run("i have nowhere to sleep tonight and my son is with me")
    assert result["question_class"] is QuestionClass.CRISIS
    text = result["answer"].text
    assert "1800 707 707" in text
    assert "999 or 112" in text
    # Absent rather than None: the crisis path is terminal, so no planning or
    # retrieval node ever ran to write those keys.
    assert not result.get("plan"), "it started planning during an emergency"
    assert not result.get("retrieved"), "it retrieved during an emergency"


def test_a_procedural_turn_is_answered_with_its_sources(run: Any) -> None:
    result = run("how do I apply for a PPS number")
    assert result["question_class"] is QuestionClass.PROCEDURAL
    assert result["active_domain"] == "status"
    assert result["retrieved"], "nothing was retrieved for an answerable question"
    assert result["answer"].citations


def test_a_planning_turn_produces_a_plan_before_it_answers(run: Any) -> None:
    result = run("I have just arrived, what do I do?", AMARA)
    assert result["question_class"] is QuestionClass.PLANNING
    plan = result["plan"]
    assert plan is not None
    assert plan.frontier_order, "a planning question produced no startable tasks"
    assert "ppsn.apply" in plan.frontier_order


def test_an_out_of_scope_turn_names_somebody_else(run: Any) -> None:
    """A refusal that leaves somebody stuck is a failure, not a safety win."""
    result = run("should I appeal or make a new application?")
    assert result["question_class"] is QuestionClass.OUT_OF_SCOPE
    text = result["answer"].text
    assert "Legal Aid Board" in text or "Irish Refugee Council" in text


def test_no_answer_on_any_route_asserts_an_entitlement(run: Any) -> None:
    """The claim the whole system exists to make, checked on output rather than
    on intent."""
    questions = [
        "how do I apply for a PPS number",
        "I have just arrived, what do I do?",
        "should I appeal?",
        "i have nowhere to sleep tonight",
        "what documents does a medical card need",
    ]
    banned = (
        "you are entitled",
        "you may be entitled",
        "you qualify",
        "you may qualify",
        "you will get",
        "you are eligible",
    )
    for question in questions:
        text = run(question, AMARA)["answer"].text.lower()
        for phrase in banned:
            assert phrase not in text, f"{question!r} produced {phrase!r}"


def test_no_answer_on_any_route_is_cheerful(run: Any) -> None:
    """Read by somebody under stress who may have just been refused."""
    for question in ["how do I register with a GP", "should I appeal?", "what now?"]:
        assert "!" not in run(question, AMARA)["answer"].text


def test_every_turn_leaves_a_reconstructable_trace(run: Any) -> None:
    """NFR-6. Somebody reviewing a bad answer needs to see why it happened."""
    for question in [
        "how do I apply for a PPS number",
        "i have nowhere to sleep tonight",
    ]:
        trace = run(question, AMARA)["trace"]
        assert trace
        assert any(e.node == "classify" for e in trace)
        assert all(e.detail for e in trace), "a trace entry recorded no reason"


def test_a_question_with_no_source_says_so_rather_than_inventing_one(run: Any) -> None:
    """ "I do not have a reliable source for that" is a supported outcome and a
    correct answer, not a failure."""
    result = run("what is the exchange rate for the Nigerian naira today")
    text = result["answer"].text
    assert "reliable source" in text or "Irish Refugee Council" in text
    assert not result["answer"].citations


def test_the_domain_scoping_keeps_answers_inside_their_domain(run: Any) -> None:
    """Letting retrieval wander outside the routed domain is how a banking
    answer ends up citing a healthcare source."""
    result = run("how do I open a bank account")
    assert result["active_domain"] == "banking"
    for span in result["answer"].citations:
        assert span.domain.value == "banking"


def test_a_stale_source_makes_the_answer_say_so(deps: Deps) -> None:
    """Staleness is surfaced in the text a person reads, not just in state."""
    from wayfinder.graph.nodes import plain

    state = WayfinderState(
        current_question="anything",
        answer=Answer(text="Some guidance.\n", needs_verifying=True),
        stale_sources=("some.source",),
        today=TODAY,
    )
    updated = cast("Answer", cast("dict[str, Any]", plain(state))["answer"])
    assert "not been checked recently" in updated.text


def test_a_degraded_crisis_screen_is_surfaced_not_buried(deps: Deps) -> None:
    """A crisis screen that quietly stops working is worse than one that is
    visibly off, because the first one is still trusted."""
    from wayfinder.graph.nodes import plain

    state = WayfinderState(
        current_question="anything",
        answer=Answer(text="Some guidance.\n"),
        stale_sources=("crisis-screen-degraded",),
        today=TODAY,
    )
    updated = cast("Answer", cast("dict[str, Any]", plain(state))["answer"])
    assert "safety check is not working" in updated.text
    assert "999 or 112" in updated.text


def test_running_the_same_turn_twice_gives_the_same_answer(run: Any) -> None:
    """With a deterministic composer the whole graph is deterministic, which is
    what makes any of these assertions exact rather than approximate."""
    first = run("how do I apply for a PPS number", AMARA)["answer"].text
    second = run("how do I apply for a PPS number", AMARA)["answer"].text
    assert first == second


def test_the_shipped_data_directory_is_the_one_under_test() -> None:
    """Guards against the fixtures quietly pointing at a toy corpus."""
    data = Path(__file__).parents[2] / "src" / "wayfinder" / "corpus" / "data"
    assert (data / "tasks" / "ireland.yaml").exists()
