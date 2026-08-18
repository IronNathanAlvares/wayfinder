# ADR-0005. Hand-curated, dated corpus with staleness gating

**Status:** Accepted · **Date:** 2026-08-17

## Context

Immigration and welfare rules change often. An agency page last reviewed two
years ago looks identical to one updated last week. Scraped guidance is
conditional and cross-referenced in ways that defeat naive extraction.

## Decision

Every task, prerequisite and citation is written by a person against a named
source carrying a mandatory `last_verified` date. A source without one fails the
build. Retrieval applies staleness bands: normal, verify-this, downgraded,
excluded.

Automated ingestion is deferred to v1.2, and when it arrives it proposes changes
for human review rather than writing to the corpus directly.

## Why manual is the right call here

A wrong prerequisite sends somebody on a journey they cannot afford to waste.
Task granularity is an editorial judgement: "apply for a PPS number" is one task
because that is how a person experiences it, not seven because that is how the
form works. Neither of those should be handed to a scraper for the sake of scale.

## Consequences

The corpus is small, partial, and says so. "I do not have a reliable source for
that, here is who to ask" is a supported and correct outcome, and it appears in
the eval set as a correct answer rather than as a failure.

Maintenance is ongoing and made visible: `/v1/corpus/health` reports staleness as
an operational alarm, because a silently stale corpus is the most likely way this
system starts being quietly wrong while looking fine.
