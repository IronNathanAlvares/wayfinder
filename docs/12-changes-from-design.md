# 12. Changes from the design, and why

**Date:** 18 August 2026 · **Made during:** M1

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
