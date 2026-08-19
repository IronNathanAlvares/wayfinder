# 12. Changes from the design, and why

**Date:** 18 August 2026 · **Made during:** M1 and M3

The design package was written on 17 August 2026 with no code. Building M1
turned up places where it was wrong, underspecified, or contradicted by the
tool. HANDOFF says to fix the doc rather than work around it, so this records
every change and the reason.

Nothing here relaxes ADR-0004. Two of the changes tighten it.

---

## Verified rather than changed

**LangGraph.** The design assumes 1.x with `interrupt()` and
`Command(resume=...)`. Checked against a real install: `langgraph 1.2.11`,
`langgraph-checkpoint 4.2.0`, `langgraph-checkpoint-sqlite 3.1.1`,
`langchain-core 1.5.6`, `pydantic 2.13.4`. `langgraph.types.interrupt` exists,
`Command` carries `resume`, `langgraph.errors.GraphInterrupt` exists,
`SqliteSaver` imports. `01-research-and-analysis.md` §1.1 is accurate and needs
no change.

One incidental correction for whoever writes M4: `BranchSpec` exposes `ends`,
not `path_map`.

---

## 1. The topology test could not be written as specified

`09` §5 used `path.taken_when(question_class=...)`, which does not exist. A
compiled graph exports every conditional-edge target as an edge, so static
topology cannot distinguish which class routes where.

**Changed:** `ADR-0007` records the proof method that does work, and `09` §5 is
rewritten to match. The claim is unchanged and is now actually testable.

This is the most important change in the list. The original test would have
passed while the property it names was false.

## 2. `Condition` was undefined, and needed three-valued logic

`06` §2 referenced `applies_when: Condition` without defining it. `05` §7
implied a flat equality map, which cannot express membership, negation or
anything about a household. Worse, it had no answer for a situation field nobody
has asked about yet: under two-valued logic an unasked question reads as a
negative answer and the plan silently asserts something about somebody.

**Changed:** conditions evaluate under Kleene K3 to TRUE, FALSE or UNKNOWN. The
plan gains a fourth partition, `needs_info`, alongside frontier, blocked and
done. Every condition also reports which facts would move it off UNKNOWN, pruned
to nothing once the result is decided, which is what makes FR-P8 computable
instead of guessed.

## 3. The minimal unblocking set formula was wrong, and was two things

`06` §5.1 gave `unblock(t) = { u in frontier : u is an ancestor of t }`. That is
the set of all frontier ancestors, which is exactly the non-minimal superset the
same section rejects, and it is incomplete: doing the frontier ancestors does
not unblock `t`, because the tasks between them and `t` still have to happen.

**Changed:** two outputs, defined separately.

- `unblocking_route(t)`: the smallest set of tasks at any status whose
  completion makes `t` startable, minimised over alternative routes.
- `next_actions(t)`: the part of that route startable today. This is the
  sentence a person reads.

Also stated honestly: requirements form an AND of ORs, so this is minimum-cost
solving over an AND/OR graph, which is NP-hard in general. The implementation is
exact rather than greedy, because a greedy choice per alternative is not
globally optimal when two alternatives share a sub-task. A hard bound guards the
assumption that alternatives stay shallow, and breaching it raises rather than
returning a possibly non-minimal answer quietly.

## 4. The critical path weighting was unspecified, then wrong twice

`06` §6 said to rank by how many blocked tasks a frontier task unblocks,
weighted somehow by severity and waiting time. Left there, the headline claim of
the demo rests on invented weights.

First attempt was longest downstream waiting time alone, a standard critical
path computation. That is the right computation and the wrong ordering: it puts
a ten day language class above a seven day application for the card somebody
needs to see a doctor. Both gate the same amount of downstream work, which is
none, so the computation has nothing to say and the order falls to an accident
of duration.

**Changed:** severity is the coarse band, gated calendar time orders within it.
Severity is an editorial judgement about what being blocked costs; gated time is
computed. Keeping them separable avoids combining them with weights nobody can
defend.

Checked against the twelve reference personas: this ordering matched the
hand-written expectation in eleven of twelve, and in the twelfth the computed
answer was better than the hand-written one.

## 5. `Situation` was missing what the builder needs

`06` §5 partitions into done, and FR-S9 forbids the system marking a
`determination` prerequisite complete, but `Situation` had nowhere to record
either.

**Changed:** added `tasks_completed`, and `determinations` keyed by artefact
reference. A determination record requires a non-empty `authority` and a
`recorded_on` date, so one cannot exist in state without a named decider. The
plan engine has no code path that constructs one, and a test asserts that by
inspecting the modules.

Also added `protection_application_date`, distinct from `arrival_date`. Waiting
periods in this domain run from the application, and somebody can arrive weeks
before they apply. Collapsing the two produces a date that is wrong in the
direction that costs somebody an entitlement.

## 6. Prerequisite `kind` and `ref` encoded the same fact twice

`05` §7 had `kind: document, ref: document:ppsn`. Two places to state one fact
is one place to get it wrong.

**Changed:** the prefixed URI is the single identity, and the kind is derived
from the prefix and validated at load.

Two consequences followed.

`documents_held` became `held` plus `known_absent`, both holding full artefact
references. That is change 2 applied to artefacts: something in neither set is
genuinely unknown. `has_ppsn` and `employment_permission` are gone, because they
duplicated `document:ppsn` and `status:labour_market_access`.

`optional: true` on a prerequisite became `any_of`. A flat optional flag cannot
say *which* alternatives belong together, and change 3 needs exactly that.

---

## Found while building, not in the review

### A determination was being offered as an intake question

Discovered by a reference persona failing. An undecided determination has no
record, so it evaluated to UNKNOWN, so the task landed in `needs_info` and the
determination appeared in the list of open questions.

That is a safety bug. "Do you satisfy the residence test?" is precisely the
question this system must never put to somebody, and listing it as an open
question invites an answer from the person, or later from a model, standing in
for a decision only an authority can make.

**Fixed:** determinations are excluded from open questions. An undecided
determination blocks, is named, and names its authority. A property test asserts
no determination ever reaches `open_questions` for any generated situation.

### Completing a task did not imply holding what it produces

`Situation` knows nothing about the corpus, so it could not work out that
finishing `ppsn.apply` is the same fact as holding the PPS number. Somebody
reporting what they had done got a plan that did not move.

**Fixed:** the builder derives held artefacts from completed tasks.
`tasks_completed` means finished with the output in hand. There is no
in-progress state in v1, and adding one means modelling the gap between applying
and receiving, which is real in this domain and a larger change than it looks.

### Blocked tasks lost their actionable part

A task blocked by both a missing document and a determination reported "there is
no route", because the determination made the whole task unroutable.

**Fixed:** a route is reported even when it cannot complete the task, alongside
the named things nothing can clear. Somebody waiting on a determination still
needs to know which of the other prerequisites they can be getting on with, and
telling them there is no route when three of four steps are available is both
wrong and demoralising.

---

---

# M3, the safety layer

## 7. A deterministic crisis screen does not reach the required recall

This is the finding the milestone was for, and it has its own record in
ADR-0008. PDD assumption A2 said "a deterministic classifier can catch `CRISIS`
reliably" and listed it as something to validate against a corpus in M3. It has
been validated against two, and it is false.

| Measured on | CRISIS recall | Gate |
|---|---|---|
| Dev splits, tuned against | 1.000 | 0.99 |
| Holdout v1, phrase lexicon | 0.300 | 0.99 |
| Holdout v2, compositional patterns | 0.167 | 0.99 |

**Changed:** a model becomes load-bearing in the crisis path, constrained so it
can only add a detection and never clear one. The lexicon keeps its veto, which
is what ADR-0006 was actually protecting. The design loses the claim that the
crisis path has no availability dependency, and when the model is unavailable
the system says so and surfaces the directory rather than pretending it screened.

## 8. The eval was measuring its own tuning

The first five splits were written, the classifier was fixed against the items
it failed on them, and it then reported 1.000 across the board. Those numbers
said the tuning worked, which is a different claim from the classifier working.

**Changed:** a held-out split, written before being run and evaluated once. The
rule is that a failure there is reported rather than patched away. When holdout
v1 revealed a whole class of failure it was burned fixing it and retired to
`regression.yaml`, and a fresh one replaced it.

The gate reports dev and holdout separately, because one number over both would
let three hundred in-sample items drown out the fifty that measure anything.

## 9. CI gates on a baseline, not on the design targets

The design targets are not met. A build that is permanently red gets ignored,
and a build that goes green by scoring its training set is how this went wrong
in the first place.

**Changed:** `wayfinder-eval` reports against the design gates and exits 1 when
they are unmet, which is the truth. `wayfinder-eval --baseline`, which is what
CI runs, checks against a committed baseline and fails only on regression. The
baseline file records the real numbers, including the 0.167, and the command
prints that the design gates are unmet every time it passes.

## 10. Layer 3 is pluggable rather than necessarily a model

The design assumed layer 3 would always be an LLM. Without one the system can
never say `PROCEDURAL`, so it escalates everything, which the design itself
names as the useless outcome. Measuring precision on a class the system never
assigns is a division by zero, and reporting that as a pass would be the
broken-eval-reads-as-passing failure the exit codes exist to prevent.

**Changed:** layer 3 is a protocol with a deterministic default implementation.
The layered contract in `07` §4 is unchanged; what changed is that layer 3 is
not necessarily sampled. Held out, the deterministic implementation scores
`PLANNING` recall of 0.000, so it is a safe floor and not a working classifier.

## 11. `PLANNING` had no eval split at all

Found by the gate reporting zero support for it. One of five classes, and the
one the project is named for, was untested.

**Changed:** a `planning.yaml` split exists. Held out it scores 0.000, which is
the same generalisation problem as the crisis lexicon and is recorded rather
than hidden.

## 12. The crisis directory contains only numbers that were verified

Eleven services were checked against their publishers' own pages on 18 August
2026. No dedicated anti-trafficking line could be verified, so there is not one:
trafficking routes to the Garda emergency and confidential lines instead, which
is worse than a specialist service and better than a number nobody checked.

`hours` is a required field on every entry. The Dublin homeless freephone closes
at 10pm and "I have nowhere to sleep tonight" is mostly typed after that, so a
number shown without its hours sends somebody to a phone nobody answers.

## 13. The model crisis screen closes the gap, and the corpus becomes the limit

ADR-0008 said a model becomes load-bearing in the crisis path. That model screen
now exists: a closed two-field schema, an enumerated category set, a bounded
timeout, and no swallowed exceptions. Every failure path turns into a visibly
degraded screen rather than a silent clearance, and the whole adapter is tested
offline against an injected fake client.

**Measured on 18 August 2026.** Held out, the deterministic screen scores 0.167
and the same screen with `claude-haiku-4-5` behind it scores 1.000 with zero
false positives, stable across four runs. It caught all ten turns the patterns
missed. `claude-opus-5` also scored 1.000, three times slower and with one extra
non-crisis trigger, so Haiku is the better choice for a screen whose latency is
part of its safety story.

**Twelve items cannot demonstrate 0.99.** Twelve out of twelve puts the 95
percent lower bound at 0.78; the gate needs 299 consecutive successes to certify
at that confidence. The gate is still unmet, now because the corpus is too small
rather than because the approach cannot reach it. Full numbers in ADR-0008.

One bug the offline tests caught before it could matter: a response missing the
`crisis` field read as "no crisis" rather than as malformed, which would have
turned every schema failure into a silent clearance. It raises now.

The screen defaults to `claude-opus-5` at low effort. The effort setting is a
real decision rather than a default: this runs before everything else on every
turn, so its latency is part of its safety story, and the deterministic lexicon
has already run by the time it is consulted.

## 14. A caseworker's answer was followed by a refusal

Found by running the server, not by reading the code, and not caught by any of
the six handoff tests that existed at the time.

Determinations route from classification straight to the handoff, so retrieval
never runs on that path. Composition then called the composer anyway, and with
no spans to work from the composer returns the no-source refusal. What a person
actually received was a named caseworker's answer, followed immediately by "I
do not have a source I trust for that". That reads as the system doubting the
person it had just named, and it contradicts the sentence directly above it.

Composition now returns the attributed answer alone when a determination is
present. `test_a_caseworkers_answer_is_not_followed_by_a_refusal` covers it.

The wider lesson is about where the tests were pointed. Every handoff test
asserted on state and on substrings that were present. None of them read the
whole answer as a person would, so a contradiction sitting in plain sight
survived six of them.

## 15. The checkpoint deserialises an explicit list of types, not anything

LangGraph 1.2.11 deserialises whatever it finds in a checkpoint, warns once per
type, and says the permissive behaviour will be blocked in a future version.
Its own serialiser docstring notes that an attacker who can write to the
checkpoint database may be able to trigger code execution.

That is a live concern in this design rather than a theoretical one. The
database holds paused threads containing what somebody said about their own
situation, and by design it outlives the process by days.

`checkpoint.py` now passes an explicit `allowed_msgpack_modules` naming the
thirty-four types this system actually checkpoints, listed as classes so a
rename is an import error. A blocked type does not raise: it comes back as a
plain dict, so the tests assert on attribute access after a real reopen rather
than on the absence of a warning.

## 16. Both entry points refuse to start with the deterministic screen alone

`wayfinder ask` and `wayfinder serve` stop with exit code 2 unless
`ANTHROPIC_API_KEY` is set or `--no-model-screen` is passed. Opting out prints
the measured recall on stderr on every run.

ADR-0008 measured that configuration catching 2 of 12 held-out crisis turns.
Starting quietly with it would ship a safety claim the measurements do not
support, and a warning in a README is not a control. Exit code 2 rather than 1
because this is a configuration problem, not a verdict.

A concrete case from a live run on 19 August 2026. The turn "my landlord says we
have to be out by tomorrow and i have my daughter with me" is routed to the
crisis directory with the model screen on, and classified as a determination and
queued for a caseworker with it off. Same input, same code, one line of
configuration: a phone number now, or a wait of days.

## 17. The caseworker queue emptied on restart

The first version of `/v1/queue` listed threads out of an in-memory dictionary,
so after a redeploy it returned an empty list while the graph was still paused
on disk with somebody's question in it. The endpoint's own docstring claimed the
opposite: that it reads paused threads out of the checkpointer so the queue
cannot drift out of step with what the graph is waiting on.

Nothing caught it. Every API test built the app once and used it, which is the
shape that makes an in-memory cache look like durable storage. The durability
tests that did kill a process were all one layer down, against the graph.

The queue now enumerates threads from the checkpointer, and situations read
through to the checkpoint as well, so a person coming back after a redeploy is
not asked to describe their circumstances again.
`test_the_queue_survives_a_restart` builds the app twice over one file.

The pattern is the same one as change 14: the durability of the pause was
tested thoroughly at the graph, and not at all at the surface a caseworker
actually uses.

## 18. The crisis holdout was sized to certify the gate, and the gate failed

`tests/corpus/crisis-holdout.yaml` holds 320 crisis turns across the six
categories and 156 near misses. The size is not arbitrary: certifying 0.99 at 95
percent confidence takes 299 consecutive successes, so anything smaller cannot
demonstrate the gate however well it scores. The size was fixed from that
arithmetic before a line of it was written.

The confidence arithmetic moved out of prose and into `eval/metrics.py`, where
`lower_bound` and `trials_needed` are computed and printed next to every recall
figure. A number that lives only in a paragraph is a number nobody recomputes
when the corpus changes.

**The result.** Deterministic 0.138, lexicon plus `claude-haiku-4-5` **0.897**.
On the previous twelve-item split the same model scored 1.000. The gate is not
met and the misses concentrate in self-harm, which is measured per category
because an aggregate hides that. Details in ADR-0008.

Three things worth separating out.

**The 0.138 is the contamination check.** This corpus was written by the person
who wrote the lexicon, which is the wrong person, and no amount of care fixes
that. But if the sentences had been produced by recalling the patterns, the
deterministic screen would have scored near the top of its range on them. It
scored 0.138, in line with the 0.167 that came before, which is evidence the
file measures something the patterns do not already contain.

**The near misses are not padding.** Recall alone is achieved perfectly by a
screen that fires on everything, so 156 turns that mention homelessness,
violence, deportation and death without being an emergency are what stops the
headline number being meaningless. Both configurations fired on 7 of them.

**The screen is not deterministic.** Two runs with identical settings scored 288
and 287 out of 320. That is worth knowing before anybody quotes a single figure
from it, and it means a gate this tight cannot be certified from one run.

One process failure of my own, recorded because it cost real money: the first
run's output was piped through `head` and the per-item detail was lost, so the
measurement had to be paid for twice. `wayfinder-compare` now takes `--save` and
writes every miss to JSON, and the run is committed under
`tests/corpus/measurements/`.

---

## Scope decisions

**Two corpora.** `08-roadmap.md` puts reference personas in M1 and corpus
curation in M2, which cannot both be true: personas need tasks. So the twelve
reference personas assert exact plans against a synthetic fixture corpus under
`tests/fixtures/`, and the real Irish corpus lives separately. Curating content
in M2 therefore cannot break M1's tests, and an engine change cannot be masked
by a content change.

**Three sources could not be fetched.** citizensinformation.ie and gov.ie
returned 403, and the irishimmigration.ie URL in the design returned 404. Under
ADR-0005 an unverified source cannot be cited, so every task depending on them
is absent from the seed corpus. The visible consequence is that the Habitual
Residence Condition, the canonical determination and the example used throughout
the design, is not modelled. Adding it from memory would be inventing content.
Recorded in the corpus README and carried into M2.

**`TC` lint rules disabled.** flake8-type-checking fights Pydantic, which
resolves annotations at runtime. The purity guarantee comes from the
import-linter contracts, which check what is imported rather than where the
import statement sits.
