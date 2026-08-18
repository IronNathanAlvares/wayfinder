# ADR-0001. LangGraph as the orchestration framework

**Status:** Accepted · **Date:** 2026-08-17

## Context

The project needs multi-step reasoning, routing between specialist agents, and a
human handoff that may take days.

## Decision

LangGraph 1.x, with `langgraph-checkpoint-sqlite` in development and
`langgraph-checkpoint-postgres` for deployment.

## Why, specifically

The deciding feature is durable execution. `interrupt()` serialises the full
state snapshot under the thread id and unwinds cleanly, so the process can
restart and a caseworker can respond on Thursday to a question asked on Monday.
That is the actual shape of the human handoff in this domain, and building it on
anything without a checkpointer means reimplementing that badly.

Closing the LangGraph gap is also the stated purpose of the project, so using a
named orchestration framework properly is part of the point rather than
incidental to it.

## Alternatives

| Option | Why not |
|---|---|
| CrewAI | Good at role-based collaboration, weaker on the durable pause and on explicit graph topology, and topology is what makes the safety claim checkable |
| Hand-rolled state machine | Would mean writing checkpointing and resume, which is the hard part, and would close no skills gap |
| Plain sequential chain | Routing genuinely needs reasoning, and there is a real multi-day pause in the middle |

## Consequences

Framework churn is a real cost, since LangGraph moves quickly. Mitigated by
keeping `plan/` and the deterministic parts of `safety/` free of any framework
import, so the parts carrying the actual value survive a migration.
