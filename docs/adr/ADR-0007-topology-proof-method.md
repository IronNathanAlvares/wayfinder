# ADR-0007. How the no-determination-path claim is actually proved

**Status:** Accepted · **Date:** 2026-08-18 · **Supersedes the test sketch in `09` §5**

## Context

ADR-0004 says there is no path from a determination question to a generated
answer. `09-test-and-eval-plan.md` §5 sketched the proof as:

```python
for path in all_paths(graph, start="classify", end="compose"):
    if path.taken_when(question_class="DETERMINATION"):
        assert "handoff" in path.nodes
```

`path.taken_when(...)` does not exist and cannot exist. Checked against
LangGraph 1.2.11, a compiled graph exports every target of a conditional edge as
an edge:

```
edges: [('__start__','classify',False), ('classify','compose',True),
        ('classify','handoff',True), ('handoff','compose',False), ...]
```

So `classify -> compose` is present in the static topology no matter which class
routes where. The routing decision lives inside a Python function, and static
topology alone cannot tell "DETERMINATION goes to handoff" from "DETERMINATION
goes to compose".

The claim is still true. The sketched test simply does not test it, and a test
that appears to check a safety property without checking it is worse than no
test, because it stops anybody looking.

## Decision

Routing becomes a declarative table, and the proof becomes three tests that
together carry the claim.

**One table, two consumers.** `ROUTES: Mapping[QuestionClass, NodeName]` is the
single source both for the runtime router and for the `add_conditional_edges`
path map. Not two copies that can drift apart, because the drift would be
invisible and the consequence would not be.

**Test 1, totality.** The router is exhaustive over `QuestionClass`. Adding a
class without a route fails at construction rather than at runtime.

**Test 2, routing.** `ROUTES[DETERMINATION] == "handoff"`, exercised through the
real router function for every class rather than by reading the table.

**Test 3, reachability under deletion.** Delete `handoff` from the compiled
topology, then assert `compose` is unreachable from `ROUTES[DETERMINATION]`.

Test 3 is the one that carries the claim. Tests 1 and 2 say determinations are
routed to the human. Test 3 says there is no *other* way round, which is what
"no path exists" actually asserts and what the original sketch never checked.

## Consequences

The claim becomes checkable rather than arguable, which was the whole reason for
choosing a supervisor over a swarm in ADR-0002.

The cost is that supervisor routing must stay declarative. A router that
computes its target rather than looking it up would break test 1 and would put
the safety claim back into prose. That constraint is accepted, and it is cheap:
routing here is a classification lookup, not a computation.

This lands in M4. Recording it now, rather than discovering it while writing the
test, is the point of checking a design against the tool it assumes.
