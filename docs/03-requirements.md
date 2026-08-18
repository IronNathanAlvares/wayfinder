# 03. Requirements

**Project:** Wayfinder · **Version:** 1.0 · **Date:** 17 August 2026

MoSCoW: **M**ust / **S**hould / **C**ould / **W**on't for v1.

---

## 1. Safety (FR-S). These come first on purpose

| ID | Requirement | M | Acceptance |
|---|---|---|---|
| FR-S1 | Every turn is classified before any other processing | M | Trace shows a class for every turn. No turn reaches a domain agent unclassified |
| FR-S2 | Crisis detection is deterministic and runs before the graph | M | No LLM call occurs before the crisis verdict. Verified by call log |
| FR-S3 | A crisis response is looked up, never generated | M | Response bytes match a directory entry exactly |
| FR-S4 | A crisis response is terminal | M | No planning or retrieval follows a crisis hit |
| FR-S5 | `DETERMINATION` cannot reach composition without a human | M | Graph topology test asserts no such path exists |
| FR-S6 | Deterministic markers catch the first-person entitlement shape before any model runs | M | Marker corpus passes without an LLM available |
| FR-S7 | Ambiguous classification resolves to `DETERMINATION` | M | Tie-break test |
| FR-S8 | Every refusal names an alternative | M | No refusal template lacks a named organisation or authority |
| FR-S9 | The system never marks a `determination` prerequisite complete | M | Assertion in the plan engine |
| FR-S10 | Crisis lexicon and directory carry review dates | M | Load fails without them |

---

## 2. Planning (FR-P)

| ID | Requirement | M | Acceptance |
|---|---|---|---|
| FR-P1 | Tasks are selected by situation predicate | M | Table-driven tests across the situation space |
| FR-P2 | Prerequisites resolve against produced artefacts, not hard-wired task ids | M | Adding an alternative producing task links dependents automatically |
| FR-P3 | The task graph is validated acyclic, and a cycle fails loudly | M | Property test. A cycle is a corpus bug, never silently broken |
| FR-P4 | Plans are topologically ordered, tie-broken by severity then wait time | M | Twelve reference personas asserted exactly |
| FR-P5 | Blocked tasks report a minimal unblocking set | M | Asserted minimal, not merely correct |
| FR-P6 | The critical path is identified and explained | M | "Do this first, N things wait on it" appears in output |
| FR-P7 | Replanning produces a diff, not a fresh list | S | Snapshot test across a scripted timeline |
| FR-P8 | Intake asks only questions that change the plan | S | A field whose resolutions produce identical plans is never asked |

---

## 3. Retrieval and composition (FR-R)

| ID | Requirement | M | Acceptance |
|---|---|---|---|
| FR-R1 | Retrieval is scoped to the routed domain | M | |
| FR-R2 | Every source carries `last_verified`; load fails without it | M | |
| FR-R3 | Staleness bands applied: normal, verify, downgrade, exclude | M | Table-driven across age bands |
| FR-R4 | Composition sees only retrieved spans | M | No free-recall path exists |
| FR-R5 | Every claim carries a citation | M | Unconstructable otherwise, enforced by type |
| FR-R6 | Unsupported claims are removed, not hedged | M | Verifier test. Hedged output is a failure |
| FR-R7 | "No reliable source" is a supported outcome | M | Appears in the eval set as a correct answer |
| FR-R8 | Output meets a plain-English reading target | S | Measured |

---

## 4. Orchestration (FR-O)

| ID | Requirement | M | Acceptance |
|---|---|---|---|
| FR-O1 | Supervisor routes to exactly one domain per question | M | |
| FR-O2 | Domain subgraphs never route to each other | M | Topology test |
| FR-O3 | ReAct loops are step-bounded | M | Recursion limit enforced |
| FR-O4 | `interrupt()` pauses and checkpoints full state | M | |
| FR-O5 | State survives process restart | M | Kill mid-pause, resume, assert state hash unchanged |
| FR-O6 | Resume injects the determination and attributes it to the named human | M | Output names the caseworker, not the system |
| FR-O7 | The person receives an immediate acknowledgement on handoff, including the procedural part of their question | M | Never a silent wait |

---

## 5. Non-functional

| ID | Category | Requirement | Target |
|---|---|---|---|
| NFR-1 | Latency | Plan build, no LLM | under 200 ms |
| NFR-2 | Latency | Procedural answer, end to end | p95 under 8 s |
| NFR-3 | Determinism | Safety layers 1 and 2 | Identical output for identical input, always |
| NFR-4 | Privacy | Personal data not persisted by default | Purged on thread completion |
| NFR-5 | Privacy | Escalations carry the minimum needed | Reviewed field by field |
| NFR-6 | Auditability | Every turn reconstructable from the trace | Classification, route, sources, verification result |
| NFR-7 | Maintainability | `plan/` and deterministic `safety/` import nothing with I/O | import-linter contract |
| NFR-8 | Operability | Corpus staleness surfaced as an alarm | `/v1/corpus/health` |
| NFR-9 | Accessibility | Client-facing output readable and screen-reader friendly | Tested |
| NFR-10 | Tone | No cheerfulness, no false reassurance | Manual review of every template |

---

## 6. User stories

**US-1.** As somebody who arrived last week, I want to know what to do first and
what to bring, so I do not waste a day queuing for something I cannot get yet.
*Accept:* a situation produces a frontier of startable tasks, each with its
document list, and the critical path is named.

**US-2.** As somebody whose child benefit is blocked, I want to know why and what
to do about it, without being told whether I will get it.
*Accept:* output names the determination, the deciding authority, the application
route, and an organisation that helps. It contains no assessment of the outcome.

**US-3.** As somebody in crisis tonight, I want a phone number, not a plan.
*Accept:* crisis screen fires before anything else, response comes from the
directory, nothing else is produced.

**US-4.** As a caseworker, I want escalations that arrive with the situation
attached, so I can answer in two minutes rather than twenty.
*Accept:* queue item includes the question, the situation summary, the retrieved
sources, and when it was asked.

**US-5.** As a caseworker, I want my determination attributed to me.
*Accept:* the resumed answer names the caseworker and does not restate the
judgement in the system's voice.

**US-6.** As somebody whose status was just granted, I want to know what changed,
not my whole list again.
*Accept:* replanning returns a diff, leading with newly unblocked items.

---

## 7. Traceability

| Goal (PDD §3.1) | Requirements | Tests |
|---|---|---|
| G1 correct ordering | FR-P1 to P6 | Reference personas |
| G2 no uncited claims | FR-R4 to R6 | Type-level plus verifier |
| G3 refuse determinations | FR-S5 to S7 | Corpus gate plus topology test |
| G4 crisis escalation | FR-S2 to S4 | Crisis corpus, 0.99 recall |
| G5 durable pause | FR-O4 to O6 | Process-kill test |
| G6 staleness flagged | FR-R2, R3 | Age-band tests |
