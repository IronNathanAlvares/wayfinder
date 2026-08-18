# ADR-0002. Supervisor pattern, not swarm

**Status:** Accepted · **Date:** 2026-08-17

## Context

LangGraph offers two multi-agent shapes. In a swarm, agents hand off directly to
each other via `Command` objects returned from handoff tools. In a supervisor,
one routing node decides, and every decision is visible in a trace.

General guidance already says start with the supervisor: simpler to build and
debug, and routing accuracy usually matters more than the latency cost. Swarms
need budget limits, handoff schemas, loop detection and tool isolation before
they are safe to run.

## Decision

Supervisor, with domain agents as subgraphs that never route to each other.

## The reason that actually decides it

The central safety claim of this project is that **no path exists from a
determination question to a generated answer without passing through a human**.

With a supervisor and explicit edges, that is checkable. There is a test that
walks the compiled graph and asserts the path does not exist. In a swarm, where
any agent may hand off to any other, the reachable path set is large and dynamic,
and the same claim becomes an argument rather than a proof.

A safety property you can only argue for is a safety property you will eventually
be wrong about.

## Consequences

Higher latency and token cost on routing, accepted. Cross-domain questions must
be decomposed by the planner rather than resolved by agents talking to each
other, which is more work in the planner and keeps the reachable path set small
enough to enumerate.

Revisit only if routing accuracy becomes the dominant failure mode, and even then
prefer hierarchical teams over a flat swarm.
