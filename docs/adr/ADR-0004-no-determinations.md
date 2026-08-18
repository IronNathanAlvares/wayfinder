# ADR-0004. The system never makes an eligibility determination

**Status:** Accepted · **Immutable** · **Date:** 2026-08-17

> The most important decision in the project. Not configurable, not behind a
> flag, not relaxed for a demo.

## Context

A language model asked "do I qualify for X?" will produce a fluent, confident
paragraph whether or not it knows, and whether or not the rules changed last
month. For most applications that is an irritating hallucination. Here it is
somebody with no income planning around money that is not coming, or taking a
step that damages a protection claim.

Determinations in this domain are legal decisions made by named authorities. The
Habitual Residence Condition is the clearest case: a multi-factor assessment made
by the Department of Social Protection, where the guidance is explicit that not
all factors need be satisfied and that the question is where a person's main
centre of interest lies. That is a judgement, and it is not ours.

## Decision

Eligibility determination is out of scope **by construction**.

1. A question taxonomy classifies every turn, with deterministic markers for the
   first-person entitlement shape.
2. `DETERMINATION` routes to a human handoff. There is no edge from
   classification to composition for that class.
3. A test walks the compiled graph and asserts that path does not exist.
4. The `determination` prerequisite kind carries the same rule into the corpus,
   so a contributor cannot add a task that implies otherwise.
5. Ambiguity resolves to `DETERMINATION`.

## Rejected alternatives

| Option | Why not |
|---|---|
| Answer with a disclaimer | "You may be entitled to X" is still an entitlement claim, and it sounds like permission to plan around it |
| Answer only when confident | Model confidence is not calibrated to legal correctness |
| Answer for simple cases | Somebody has to decide which cases are simple, and that decision is itself a determination |

## Consequences

**Positive.** The dangerous failure mode is structurally unavailable rather than
discouraged. Caseworker time goes to what only a caseworker can do. Every refusal
is explainable, because it names the authority and the route to them.

**Negative.** More escalations than a less careful system, and the boundary will
sometimes catch a question that could have been answered safely. That is the
accepted direction of error. Whether caseworkers find the volume acceptable is
assumption A4 in the PDD, and it needs validating with a real organisation rather
than assumed.
