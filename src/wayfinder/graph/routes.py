"""The routing table. One table, two consumers, and that is the whole point.

ADR-0007. The claim this project makes is that no path exists from a
determination question to a generated answer without passing through a human.
Static graph topology cannot prove that on its own: a compiled LangGraph exports
every target of a conditional edge as an edge, so `classify -> compose` is
present in the topology whatever the router does.

What makes the claim provable is keeping the routing decision in one declarative
place that feeds both the runtime router and the conditional-edge path map. Two
copies would drift, the drift would be invisible, and the consequence would not
be.

Three tests together carry the claim, and they live in
`tests/graph/test_topology.py`:

1. the table is total over `QuestionClass`
2. `DETERMINATION` routes to `handoff`, driven through the real router
3. with `handoff` deleted from the compiled topology, `compose` is unreachable
   from where a determination lands

The third is the one that matters. The first two say determinations go to a
person; only the third says nothing else gets there another way.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from wayfinder.safety.taxonomy import QuestionClass

# Node names, in one place so a typo is an import error rather than a silent
# edge to nowhere.
CLASSIFY: Final = "classify"
INTAKE: Final = "intake"
PLANNER: Final = "planner"
SUPERVISOR: Final = "supervisor"
RETRIEVE: Final = "retrieve"
STALENESS: Final = "staleness"
COMPOSE: Final = "compose"
VERIFY: Final = "verify"
PLAIN: Final = "plain"
HANDOFF: Final = "handoff"
DECLINE: Final = "decline"
CRISIS: Final = "crisis_response"

# Where each class goes after classification. Exhaustive by construction: the
# validator below fails at import time if a class is ever added without a route.
ROUTES: Final[Mapping[QuestionClass, str]] = {
    QuestionClass.CRISIS: CRISIS,
    QuestionClass.DETERMINATION: HANDOFF,
    QuestionClass.OUT_OF_SCOPE: DECLINE,
    QuestionClass.PLANNING: INTAKE,
    QuestionClass.PROCEDURAL: SUPERVISOR,
}


def _check_total() -> None:
    missing = sorted(c.value for c in QuestionClass if c not in ROUTES)
    if missing:
        msg = (
            f"ROUTES has no destination for {missing}. Every question class must "
            "have one, because the safety claim is about where classes go and a "
            "class with nowhere to go has no claim attached to it."
        )
        raise RuntimeError(msg)


_check_total()

# The classes whose route is terminal: they produce an answer without any
# generation at all, and nothing follows them.
TERMINAL: Final[frozenset[str]] = frozenset({CRISIS, DECLINE})


def route(question_class: QuestionClass) -> str:
    """The single runtime router. The graph's path map is built from the same table."""
    return ROUTES[question_class]
