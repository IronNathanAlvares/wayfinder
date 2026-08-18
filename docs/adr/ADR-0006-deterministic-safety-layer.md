# ADR-0006. Crisis and determination checks are deterministic and run before the graph

**Status:** Accepted · **Date:** 2026-08-17

## Context

Two decisions carry the highest cost of being wrong: missing a crisis, and
answering a determination.

## Decision

Both are checked deterministically, before the graph is entered.

- **Crisis:** pattern match against a curated lexicon on the raw turn. No LLM. On
  a hit, the response comes from a static dated directory with no generation at
  all, and it is terminal.
- **Determination:** deterministic markers for the first-person entitlement shape
  run before any model-based classification.
- An LLM classifier handles only what survives both, and ambiguity resolves to
  `DETERMINATION`.

## Why not let the supervisor decide

An LLM supervisor deciding whether to escalate is a supervisor that can be talked
out of escalating. The input here is written by people in distress, sometimes in
a second language, and sometimes by somebody deliberately probing the system.
What is needed from this layer is predictability, not intelligence.

A model also cannot mis-generate a phone number that was looked up rather than
composed. During an emergency that property is worth more than fluency.

## Deliberate over-triggering

The crisis lexicon is generous. The eval gate requires recall of 0.99 and accepts
poor precision. A false positive shows somebody a list of helplines they did not
need. A false negative is somebody sleeping outside. The cost matrix is not
symmetric and the design should not pretend it is.

## Consequences

Some procedural questions get escalated unnecessarily, costing a caseworker
seconds. Novel phrasing may still be missed, and multilingual or non-native
phrasing is the weakest area, which is stated openly in `07` §9 rather than
claimed as solved.
