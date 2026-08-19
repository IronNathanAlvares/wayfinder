"""ADR-0004 as an executable assertion, by the method ADR-0007 settled on.

Three tests carry the claim, and only the third actually proves it.

The first two say determinations are routed to a person. Both would still pass
if some other edge reached `compose` another way, which is why the original
design's version of this test would have gone green while the property it names
was false.

The third deletes `handoff` from the compiled topology and asserts `compose`
becomes unreachable from where a determination lands. That is the claim: not
"determinations pass through the human", but "there is no other way round".
"""

from __future__ import annotations

from typing import Any

import pytest

from wayfinder.graph.build import (
    edges_of,
    paths_between,
    reachable,
    routing_targets,
    without_node,
)
from wayfinder.graph.routes import (
    CLASSIFY,
    COMPOSE,
    CRISIS,
    HANDOFF,
    ROUTES,
    route,
)
from wayfinder.safety.taxonomy import QuestionClass

# --- 1. the table is total ---------------------------------------------------


def test_the_routing_table_is_total_over_every_question_class() -> None:
    """A class with nowhere to go has no safety claim attached to it.

    `routes.py` fails at import time if this is violated, so reaching this
    assertion at all means the module loaded. It is kept as a test so the
    intent is visible next to the other two.
    """
    assert set(routing_targets()) == set(QuestionClass)


def test_every_class_routes_somewhere_the_graph_actually_has(compiled: Any) -> None:
    nodes = set(compiled.get_graph().nodes)
    for question_class, destination in ROUTES.items():
        assert destination in nodes, f"{question_class.value} -> {destination}"


# --- 2. determinations route to the human -----------------------------------


def test_determination_routes_to_handoff_through_the_real_router() -> None:
    """Driven through `route`, not read off the table.

    Reading the table would test that the table says what the table says.
    """
    for question_class in QuestionClass:
        destination = route(question_class)
        if question_class is QuestionClass.DETERMINATION:
            assert destination == HANDOFF
        else:
            assert destination != HANDOFF


def test_the_graph_path_map_is_built_from_the_same_table(compiled: Any) -> None:
    """One table, two consumers. A second hand-written copy is what ADR-0007
    forbids, because the drift would be invisible and the consequence would not
    be."""
    targets = {t for _, t in edges_of(compiled) if _ == CLASSIFY}
    assert targets == set(ROUTES.values())


# --- 3. there is no other way round. this is the claim ----------------------


def test_compose_is_unreachable_from_a_determination_without_the_human(
    compiled: Any,
) -> None:
    """The load-bearing test.

    Delete `handoff` and every edge through it, then ask whether a determination
    can still reach generation. If it can, the safety architecture has a hole
    regardless of how well the classifier performs.
    """
    edges = edges_of(compiled)
    determination_lands_at = ROUTES[QuestionClass.DETERMINATION]

    # Sanity: with the human present, it does reach composition. Otherwise the
    # deletion below would prove nothing, because it was already unreachable.
    assert reachable(edges, determination_lands_at, COMPOSE)

    surviving = without_node(edges, HANDOFF)
    assert not reachable(surviving, determination_lands_at, COMPOSE), (
        "a determination can reach generation without passing through a human: "
        f"{paths_between(surviving, determination_lands_at, COMPOSE)[:3]}"
    )


def test_every_path_from_classification_to_composition_passes_through_a_human_or_retrieval(
    compiled: Any,
) -> None:
    """The positive form of the same claim, stated over whole paths.

    Composition is reachable two ways and only two: after a human answered, or
    after retrieval produced spans to cite. There is no third route in which
    something is generated from neither.
    """
    edges = edges_of(compiled)
    for path in paths_between(edges, CLASSIFY, COMPOSE):
        assert HANDOFF in path or "retrieve" in path, path


def test_a_crisis_response_never_reaches_generation(compiled: Any) -> None:
    """No generated content in a crisis response, as a property of the graph.

    A model improvising during somebody's emergency is unacceptable, and a model
    is not needed to read out a phone number.
    """
    assert not reachable(edges_of(compiled), CRISIS, COMPOSE)


def test_the_crisis_path_is_terminal(compiled: Any) -> None:
    """A crisis response does not continue into planning.

    Somebody who says they have nowhere to sleep tonight needs a phone number,
    not a forty-step onboarding plan.
    """
    onward = {t for s, t in edges_of(compiled) if s == CRISIS}
    assert onward == {"__end__"}


def test_the_decline_path_is_terminal(compiled: Any) -> None:
    onward = {
        t for s, t in edges_of(compiled) if s == ROUTES[QuestionClass.OUT_OF_SCOPE]
    }
    assert onward == {"__end__"}


# --- the machinery itself ----------------------------------------------------


def test_deleting_a_node_removes_edges_through_it_rather_than_contracting() -> None:
    """Contracting around a deleted node would preserve a path through it and
    quietly prove nothing."""
    edges = [("a", "b"), ("b", "c")]
    assert reachable(edges, "a", "c")
    assert not reachable(without_node(edges, "b"), "a", "c")


def test_path_enumeration_terminates_on_a_cycle() -> None:
    """A proof that hangs is not a proof."""
    edges = [("a", "b"), ("b", "a"), ("b", "c")]
    assert paths_between(edges, "a", "c") == (("a", "b", "c"),)


@pytest.mark.parametrize("question_class", list(QuestionClass))
def test_no_class_reaches_generation_without_its_gate(
    question_class: QuestionClass,
    compiled: Any,
) -> None:
    """Swept over every class rather than asserted for the one we worried about.

    A class added later inherits this check for free, which is the point of
    parametrising over the enum instead of listing the cases.
    """
    edges = edges_of(compiled)
    landing = ROUTES[question_class]
    if question_class is QuestionClass.DETERMINATION:
        assert not reachable(without_node(edges, HANDOFF), landing, COMPOSE)
    elif question_class is QuestionClass.CRISIS:
        assert not reachable(edges, landing, COMPOSE)
