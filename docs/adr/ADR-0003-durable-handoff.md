# ADR-0003. The human handoff is a durable pause, not a blocking call

**Status:** Accepted · **Date:** 2026-08-17

## Context

When a question needs a determination it goes to a caseworker. Caseworkers are
busy. The realistic response time is hours to days.

## Decision

`interrupt()` plus a durable checkpointer. The graph pauses, state is serialised
under the thread id, the process may restart, and `Command(resume=...)` continues
exactly where it stopped.

## What this rules out

A blocking wait, a polling loop, or a "come back later and start again" flow.
Making somebody re-explain their situation because our process restarted is a
poor outcome for anyone, and a demeaning one for somebody in this position.

## Consequences

The checkpointer becomes a core dependency rather than a nice-to-have, and
correctness after restart becomes a tested property: kill the process mid-pause,
resume, assert the state hash is unchanged.

State contains personal data while paused. The retention rules in PDD §7 and HLD
§8 apply, and escalations carry only what the caseworker actually needs.
