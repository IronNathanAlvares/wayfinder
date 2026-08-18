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

**M3 is not complete, and the reason changed.** The deterministic layers, the
lexicon, the directory, the labelled corpus, the gate and the model screen all
exist and work. With the model in place no crisis turn was missed in four runs.
What is missing is a corpus large enough to certify the 0.99 gate: twelve
held-out crisis items can demonstrate 0.78, and the gate needs 299. Until that
corpus exists, M4 should not start on the strength of a number that small.

**CI gates on a committed baseline rather than on the design targets.** The
baseline records the real numbers and states plainly that the design gates are
unmet. A permanently red build gets ignored, and a build that goes green by
scoring the training set is how this went wrong in the first place.

**The eval corpus needs somebody else.** Both holdouts were written by the
person who wrote the rules, and knowing the patterns leaks into the sentences
however careful the intent. A corpus written by an NGO worker who has read real
messages is the highest-value thing available to this project, and it is what
PDD assumption A4 was already pointing at.

## The fix, measured

Run on 18 August 2026 against the held-out split, 12 crisis items and 35
non-crisis items. The prompt was written from the category definitions in `07`
section 3.1 and never tuned against these turns.

| Configuration | Crisis recall | Fired on non-crisis | Wall clock |
|---|---|---|---|
| Deterministic lexicon only | **0.167** (2/12) | 0/35 | instant |
| Lexicon + `claude-haiku-4-5` | **1.000** (12/12) | 0/35 | 51s |
| Lexicon + `claude-opus-5`, effort low | **1.000** (12/12) | 1/35 | 2m46s |

Haiku was repeated three more times on the crisis items and returned 12/12 every
time, with 0/35 false positives on each run. It caught all ten turns the
patterns missed, including "they say the plane is booked for friday", which
needs the inference that a booked plane means removal. No pattern set reaches
that, and this is the clearest evidence in the project that the deterministic
screen was never going to.

**Haiku is the better choice here and it is not close.** Same recall, fewer
false positives, three times faster, and roughly a fifth of the cost. Latency is
part of this screen's safety story because it runs before everything else on
every turn, so the faster model is also the safer one. Opus's single extra
trigger is not a mark against it: over-triggering is the accepted direction, and
one helpline list nobody needed is the cheapest error in this system.

### What twelve items can and cannot show

**They cannot show 0.99.** Twelve successes out of twelve puts the 95 percent
one-sided lower bound on recall at **0.78**, not 1.00. Certifying the design's
0.99 gate at that confidence needs **299 consecutive successes**, and the
held-out split has twelve. The honest statement is "no failures observed in
twelve, which is consistent with recall anywhere above 0.78", and a project that
rounds that to "gate met" has learned nothing from holdout v1.

So the gate is still unmet, for a different reason than before. It was unmet
because the approach could not reach it; it is now unmet because the corpus
cannot demonstrate it. That is a much better problem and it has a concrete
answer: the crisis split needs to be two orders of magnitude larger, and it
needs to be written by somebody who is not the person who wrote the rules.

**The comparison is reproducible in one command:**

```bash
uv sync --extra llm
ANTHROPIC_API_KEY=... uv run wayfinder-compare --model claude-haiku-4-5 --effort none
```

The runner refuses to print a model number without a key, and reports a
could-not-evaluate rather than a result if any turn degraded partway through. A
partial measurement presented as a measurement is how a safety number becomes
fiction.

One portability fix came out of the first real run: `claude-haiku-4-5` rejects
the `effort` parameter with a 400, so the adapter omits it rather than sending a
default. A screen that only works on one model tier is not a screen you can fall
back with.

## Rejected alternatives

| Option | Why not |
|---|---|
| Add the missed phrasings to the lexicon | Fits the test rather than the problem. Holdout v1 was fixed this way and v2 came back worse |
| Lower the recall gate to what the patterns achieve | The gate is not a target to be met, it is a statement about what is acceptable. Somebody sleeping outside does not care what the classifier could manage |
| Drop the crisis screen and route everything to a human | The response is a phone number and it should arrive in seconds, not in the days a caseworker queue takes |
| Keep the model out and accept the recall | This is the one the design implicitly chose, and the measurement says it means missing four crisis turns in five |
