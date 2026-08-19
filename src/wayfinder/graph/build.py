"""Graph construction, plus the reachability helpers the safety proof needs.

The path map on `classify` is built from `ROUTES` rather than written out
alongside it. That is the whole mechanism ADR-0007 rests on: one table, two
consumers, no way for the runtime router and the topology to disagree.

`reachable` and `without_node` live here rather than in the tests because they
are part of the claim, not part of checking it. A proof whose machinery lives
only in a test file is a proof somebody deletes while tidying.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

from wayfinder.graph import nodes
from wayfinder.graph.routes import (
    CLASSIFY,
    COMPOSE,
    CRISIS,
    DECLINE,
    HANDOFF,
    INTAKE,
    PLAIN,
    PLANNER,
    RETRIEVE,
    ROUTES,
    STALENESS,
    SUPERVISOR,
    VERIFY,
    route,
)
from wayfinder.graph.state import WayfinderState
from wayfinder.safety.taxonomy import QuestionClass


def _branch(state: WayfinderState) -> str:
    """The runtime router. Reads the same table the path map is built from."""
    if state.question_class is None:  # pragma: no cover - classify always sets it
        return HANDOFF
    return route(state.question_class)


def _add(
    graph: Any, name: str, node: nodes.Node, *, destinations: tuple[str, ...] = ()
) -> None:
    """Register a node.

    Wrapped rather than called directly because `StateGraph.add_node` is
    overloaded such that omitting `input_schema` leaves its type parameter
    unbound, and every plain node callable then fails to match. Taking the
    graph as `Any` here confines that to one line, and the node signature is
    still checked, by this function.
    """
    # `destinations` is not optional for a node that returns Command(goto=...).
    # Without it the edge exists at runtime and is absent from the exported
    # topology, so a reachability proof over that topology passes by describing
    # a graph the executor does not run. That is a vacuous proof, and it is the
    # exact failure ADR-0007 was written to prevent.
    if destinations:
        graph.add_node(name, node, destinations=destinations)
    else:
        graph.add_node(name, node)


def build(deps: nodes.Deps) -> Any:
    """The uncompiled graph. Kept separate so tests can inspect it before compiling."""
    # Unannotated on purpose: StateGraph is generic in its state type and an
    # explicit annotation erases the parameter that makes node signatures check.
    # input_schema and output_schema are passed explicitly. They default to None,
    # which leaves their type parameters unbound and makes every node signature
    # fail to check against the graph.
    g = StateGraph(
        WayfinderState,
        input_schema=WayfinderState,
        output_schema=WayfinderState,
    )

    _add(g, CLASSIFY, nodes.make_classify(deps))
    _add(g, CRISIS, nodes.make_crisis_response(deps))
    _add(g, DECLINE, nodes.decline)
    _add(g, INTAKE, nodes.make_intake(deps))
    _add(g, PLANNER, nodes.make_planner(deps))
    _add(g, SUPERVISOR, nodes.supervisor, destinations=(RETRIEVE,))
    _add(g, RETRIEVE, nodes.make_retrieve(deps))
    _add(g, STALENESS, nodes.staleness_gate)
    _add(g, HANDOFF, nodes.handoff, destinations=(COMPOSE,))
    _add(g, COMPOSE, nodes.make_compose(deps))
    _add(g, VERIFY, nodes.verify)
    _add(g, PLAIN, nodes.plain)

    g.add_edge(START, CLASSIFY)

    # The path map is derived from ROUTES. Adding a question class without a
    # route fails at import time in routes.py, and adding one with a route it
    # cannot reach fails here.
    # The router returns a node name taken from ROUTES, so the path map is the
    # set of destinations that table can produce. Derived, never written out
    # beside it: a hand-written map is the second copy ADR-0007 forbids.
    g.add_conditional_edges(
        CLASSIFY,
        _branch,
        {destination: destination for destination in sorted(set(ROUTES.values()))},
    )

    # Terminal paths. Nothing is generated on either.
    g.add_edge(CRISIS, END)
    g.add_edge(DECLINE, END)

    # Planning, then the same retrieval path a procedural question takes.
    g.add_edge(INTAKE, PLANNER)
    g.add_edge(PLANNER, SUPERVISOR)

    # supervisor and handoff return Command(goto=...), so their outgoing edges
    # are declared on the node above via `destinations` rather than added here.
    # Declaring them is what puts them in the exported topology, which is what
    # makes the reachability proof describe the graph that actually runs.
    g.add_edge(RETRIEVE, STALENESS)
    g.add_edge(STALENESS, COMPOSE)
    g.add_edge(COMPOSE, VERIFY)
    g.add_edge(VERIFY, PLAIN)
    g.add_edge(PLAIN, END)

    return g


def compile_graph(deps: nodes.Deps, *, checkpointer: Any = None) -> Any:
    """Compile with a checkpointer. Without one there is no durable pause."""
    return build(deps).compile(checkpointer=checkpointer)


# --- the reachability machinery the safety claim uses -----------------------


def edges_of(compiled: Any) -> tuple[tuple[str, str], ...]:
    """Every edge in the compiled topology, conditional ones included.

    A conditional edge exports one entry per path-map target, which is exactly
    why static topology alone cannot prove the routing claim and why the
    deletion test below exists.
    """
    drawn = compiled.get_graph()
    return tuple((e.source, e.target) for e in drawn.edges)


def without_node(
    edges: Iterable[tuple[str, str]], node: str
) -> tuple[tuple[str, str], ...]:
    """The topology with one node removed, and every edge through it removed too.

    Not contracted around: removed. Contracting would preserve a path through
    the deleted node and quietly prove nothing.
    """
    return tuple((a, b) for a, b in edges if a != node and b != node)


def reachable(edges: Sequence[tuple[str, str]], start: str, end: str) -> bool:
    """Whether `end` can be reached from `start` by following edges."""
    adjacency: dict[str, list[str]] = {}
    for a, b in edges:
        adjacency.setdefault(a, []).append(b)

    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current == end:
            return True
        for nxt in adjacency.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def paths_between(
    edges: Sequence[tuple[str, str]], start: str, end: str, *, limit: int = 200
) -> tuple[tuple[str, ...], ...]:
    """Every simple path from start to end, for reporting what a violation is.

    Bounded, because a graph with a cycle has infinitely many walks and a proof
    that hangs is not a proof.
    """
    adjacency: dict[str, list[str]] = {}
    for a, b in edges:
        adjacency.setdefault(a, []).append(b)

    found: list[tuple[str, ...]] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
    while stack and len(found) < limit:
        current, path = stack.pop()
        if current == end:
            found.append(path)
            continue
        for nxt in adjacency.get(current, ()):
            if nxt not in path:
                stack.append((nxt, (*path, nxt)))
    return tuple(found)


def routing_targets() -> Mapping[QuestionClass, str]:
    """The table, re-exported so a test asserts against one source rather than two."""
    return ROUTES
