# ADR-0008. A deterministic crisis screen cannot reach the recall the design requires

**Status:** Accepted · **Date:** 2026-08-18
**Invalidates:** PDD assumption A2 · **Amends:** ADR-0006

> This is the result M3 was for. PDD A2 said "a deterministic classifier can
> catch `CRISIS` reliably" and listed it as an assumption to be validated
> against a corpus. It has been, twice, and it is false.

## What was measured

Two held-out splits, each written before being run and each evaluated once.

| Split | Approach | CRISIS recall | Gate |
|---|---|---|---|
| Dev splits, 320 items | phrase lexicon, tuned against them | **1.000** | 0.99 |
| Holdout v1, 50 items | phrase lexicon | **0.300** | 0.99 |
| Holdout v2, 47 items | lexicon rebuilt with compositional regex | **0.167** | 0.99 |

The dev number is worthless: the lexicon was fixed against the items it failed
on, so 1.000 measures the tuning. The moment the phrasing was unseen, recall
collapsed, and rebuilding the patterns compositionally rather than literally did
not recover it.

None of the missed turns were exotic:

- "manager say i must go before lunch, i have small baby"
- "he came back drunk and put his hands on my throat"
- "there is blood and she is not moving"
- "my boss holds my passport until i finish the debt"
- "they say the plane is booked for friday"

The last one needs an inference that a booked plane means removal. No pattern
set reaches that, and pretending otherwise by adding "plane is booked" to a list
would be fitting the test rather than solving the problem.

The same collapse hit the other classes. `PLANNING` recall on holdout v2 was
**0.000**, because every planning pattern was anchored on the phrasings that had
been thought of.

## Decision

**The deterministic screen is a floor, not a classifier.** A model becomes
load-bearing in the crisis path, with one constraint that preserves the property
ADR-0006 actually cared about.

**The model may only add crisis detections. It may never remove one.**

```
raw turn
  -> deterministic lexicon        hit  -> CRISIS, terminal. Nothing overrides it.
  -> model crisis screen          hit  -> CRISIS, terminal.
                                  no opinion, or unavailable -> continue
  -> determination markers, etc.
```

The lexicon keeps its veto. Nothing downstream, model or otherwise, can clear a
hit it produced. What changes is that the model gets to escalate turns the
lexicon missed, which is where all the missed recall lives.

**When the model is unavailable, the system says so.** It does not silently fall
back to a screen with 0.17 recall and carry on as though it had screened. It
surfaces the crisis directory unprompted and tells the person the check is
degraded. A crisis screen that quietly stops working is worse than one that is
visibly off, because the first one is trusted.

## Why this does not contradict ADR-0006

ADR-0006's argument was "an LLM supervisor deciding whether to escalate is a
supervisor that can be talked out of escalating." That remains true, and the
monotonic constraint answers it directly: this model cannot be talked out of
anything, because it has no path to a non-crisis verdict that overrides the
lexicon. It can only ever say "this too". Being talked *into* an unnecessary
escalation costs somebody a list of helplines they did not need, which is the
error direction the design already accepts.

What does change is honesty about the dependency. ADR-0006 implied the crisis
path had no availability or cost dependency. It now has one, and that is worse
than the design hoped rather than better.

## Consequences

**M3 is not complete.** The deterministic layers, the lexicon, the directory,
the labelled corpus and the gate all exist and work. The recall target does not
hold, and no amount of pattern writing will make it hold. M4 should not start on
the strength of a gate that only passes in-sample.

**CI gates on a committed baseline rather than on the design targets.** The
baseline records the real numbers and states plainly that the design gates are
unmet. A permanently red build gets ignored, and a build that goes green by
scoring the training set is how this went wrong in the first place.

**The eval corpus needs somebody else.** Both holdouts were written by the
person who wrote the rules, and knowing the patterns leaks into the sentences
however careful the intent. A corpus written by an NGO worker who has read real
messages is the highest-value thing available to this project, and it is what
PDD assumption A4 was already pointing at.

## Status of the fix

**Built, and not yet measured.** The model screen exists, satisfies the
`ModelScreen` protocol, and is tested end to end against a fake transport: the
schema it sends, every response it accepts, and every way it can fail. What has
not happened is a run against the real API, because that needs a key.

Two things follow, and both matter more than the code.

**The 0.167 stands until somebody re-measures.** Building a fix is not evidence
that the fix works, and this project has already been burned once by a number
that measured its own tuning. `wayfinder-compare` produces the comparison in one
command, and until it is run against a key the honest description of this ADR is
"a diagnosis and a proposed treatment", not "solved".

**The prompt was written from the category definitions, not from the failures.**
Fitting it to the held-out turns the deterministic screen missed would burn the
split, which is exactly how holdout v1 died. If the model does poorly on those
same turns, that is a result to report, not a prompt to tune.

```bash
uv sync --extra llm
uv run wayfinder-compare --model claude-opus-5 --model claude-haiku-4-5
```

The runner refuses to print a model number without a key, and reports a
could-not-evaluate rather than a result if any turn degraded partway through. A
partial measurement presented as a measurement is how a safety number becomes
fiction.

## Rejected alternatives

| Option | Why not |
|---|---|
| Add the missed phrasings to the lexicon | Fits the test rather than the problem. Holdout v1 was fixed this way and v2 came back worse |
| Lower the recall gate to what the patterns achieve | The gate is not a target to be met, it is a statement about what is acceptable. Somebody sleeping outside does not care what the classifier could manage |
| Drop the crisis screen and route everything to a human | The response is a phone number and it should arrive in seconds, not in the days a caseworker queue takes |
| Keep the model out and accept the recall | This is the one the design implicitly chose, and the measurement says it means missing four crisis turns in five |
