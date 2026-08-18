# 02. Project Definition Document

**Project:** Wayfinder
**Package:** `wayfinder`
**One line:** A LangGraph agent team that turns "I have just arrived, what do I do?" into an ordered plan with prerequisites, and refuses to answer the questions that need a human.
**Author:** Nathan Alvares · **Date:** 17 August 2026 · **Version:** 1.0

> **This is a standalone project.** It has no dependency on anything else, and
> nothing else needs to exist for it to run or be demoed.

---

## 1. Executive summary

Someone who has just arrived in a new country faces perhaps forty separate
administrative tasks across housing, healthcare, schooling, welfare and legal
status. The tasks are spread across a dozen agencies that do not talk to each
other, they are described in language written for civil servants, and they have
**hard prerequisites that nobody tells you about**. You cannot apply for most
things without a PPS number. You often cannot get a PPS number without proof of
address. You may not be able to get proof of address until accommodation is
allocated. Getting the order wrong costs weeks, and for someone with no income
and a family, weeks matter enormously.

Wayfinder is a LangGraph agent team that takes a situation description and
produces an **ordered plan with explicit prerequisites**, where every statement
carries a citation to a named source with a date, and where any question that
requires a determination about that person's entitlements is **handed to a human
rather than answered**.

The thing worth building here is not the agent's cleverness. It is the
discipline around it. The interesting engineering is deciding what the system
must refuse to do, and making that refusal structural rather than a prompt
instruction.

**The pitch:** most agent demos produce a to-do list. This produces a dependency
graph, tells you what is blocked and exactly what unblocks it, and knows which
questions it has no business answering.

---

## 2. Problem statement

| # | Problem | What happens today |
|---|---|---|
| P1 | Tasks have hidden prerequisites | You queue for hours, get turned away for a document nobody mentioned, and lose a week |
| P2 | Information is scattered across agencies | Ten websites, each authoritative for one slice, none of which reference the others |
| P3 | Guidance is written for administrators | Dense, conditional, full of terms of art like "habitual residence condition" |
| P4 | Rules change and pages go stale | A page last reviewed two years ago looks identical to one updated last week |
| P5 | The stakes are asymmetric | Bad advice about entitlements can cost someone a payment they needed, or worse, damage a protection claim |

P5 is why the safety design leads the technical design rather than being bolted
on afterwards.

### 2.1 Why an LLM agent is the right shape

This is a genuine multi-step reasoning problem, not a lookup:

- The plan depends on the **situation**: family composition, arrival date,
  protection status, whether accommodation is already allocated.
- Tasks have **conditional prerequisites** that vary by that situation.
- The right answer is often "you cannot do this yet, and here is the one thing
  that unblocks it", which requires reasoning over a graph rather than retrieval.
- Follow-up questions need context from everything established so far.

### 2.2 Why an LLM agent is also dangerous here

The same capability that makes it useful makes it hazardous. A model that will
confidently explain a process will just as confidently tell someone they qualify
for a payment they do not qualify for. In this domain that is not an
embarrassing hallucination, it is a person budgeting around money that will not
arrive.

So the architecture treats **eligibility determination as out of scope by
construction**, not by instruction.

---

## 3. Goals and non-goals

### 3.1 Goals

| ID | Goal | Measured by |
|---|---|---|
| G1 | Turn a situation into an ordered plan with correct prerequisites | Topological correctness against a hand-built reference plan set |
| G2 | Never state a claim without a citation to a dated source | Zero uncited claims in the eval corpus. Enforced structurally, not by prompt |
| G3 | Classify every question and refuse the ones needing a determination | ≥ 0.97 recall on `DETERMINATION`, ≥ 0.99 on `CRISIS` |
| G4 | Escalate crisis language immediately, before any other processing | 100% on the crisis corpus, bypassing the graph entirely |
| G5 | Pause durably for a human and resume correctly hours or days later | Checkpoint survives process restart; resumed state is byte-identical |
| G6 | Flag stale sources rather than quoting them confidently | Any source older than the threshold downgrades the answer |

### 3.2 Non-goals, and these are load-bearing

| ID | Non-goal | Why |
|---|---|---|
| NG1 | **It never determines eligibility.** Not for welfare, not for housing, not for protection status | Those are legal determinations made by named authorities. A wrong answer causes real harm to someone with no margin for it |
| NG2 | **It never gives legal advice** | It is not a solicitor. It names organisations that are |
| NG3 | **It never predicts an outcome** of a protection application | Nobody can, and false hope is its own harm |
| NG4 | It does not submit forms or contact agencies on anyone's behalf | Actions with consequences stay with the person and their caseworker |
| NG5 | It does not store personal data by default | See §7. The less it retains, the less there is to leak |
| NG6 | It is not a replacement for a caseworker | It is a way to arrive at a caseworker already knowing which questions to ask |

**NG1 deserves the emphasis.** The single most likely failure of a naive build
of this project is a system that cheerfully answers "am I entitled to X?"
because the model can produce a fluent paragraph about entitlement rules. The
whole safety architecture exists to make that structurally impossible.

---

## 4. Users

| Persona | Situation | Needs | Feature |
|---|---|---|---|
| **Amara**, newly arrived, two children | Week one, no PPSN, in emergency accommodation | To know what to do first and what she needs to bring | Ordered plan, document checklist, blocked-task explanation |
| **Yusuf**, six months in, status granted | Moving from the protection system into mainstream services | To understand what changes now that his status changed | Situation-diff replanning |
| **Clare**, caseworker at an NGO | Forty clients, limited hours | Clients arriving prepared, and a queue of questions that genuinely need her | The human handoff queue, with context attached |
| **A support volunteer** | Well-meaning, not trained | Not to give confidently wrong advice | The refusal taxonomy, which protects the volunteer as much as the client |

Clare is the user the design optimises for. The system's job is to increase the
proportion of caseworker time spent on things only a caseworker can do.

---

## 5. Scope

### 5.1 In scope for v1

- **Jurisdiction: Ireland.** One jurisdiction, done properly, with real sourced
  content. A shallow system covering five countries would be worse than useless
  here.
- Domains: **status and documentation, accommodation, income support, healthcare,
  education, banking**
- Situation intake as a structured interview, not a free-text prompt
- Plan graph construction with prerequisites and blocked-task detection
- Per-domain retrieval agents over a curated, dated source corpus
- Question classification and routing, including hard-coded crisis escalation
- Human handoff via `interrupt()` with durable checkpointing
- Citation-bound answer generation with an entailment check
- Staleness gating
- Plain-language output, with a reading-level target
- A caseworker queue view and a client-facing plan view

### 5.2 Out of scope for v1

| Item | Target | Note |
|---|---|---|
| Multiple jurisdictions | v2 | The plan-graph engine is jurisdiction-agnostic; the corpus is not |
| Multilingual output | v1.1 | Translation of *safety-critical* text needs its own eval, so it is not a free win |
| Voice interface | v2 | |
| Automatic source ingestion from agency sites | v1.2 | v1 uses a curated corpus with human-verified dates, deliberately |
| Case management, appointments, reminders | out | That is a caseworker tool, a different product |

---

## 6. Success criteria

| # | Criterion | Target |
|---|---|---|
| S1 | Plan ordering respects every prerequisite | 100% on the reference plan set. A violation is a bug, not a tuning issue |
| S2 | `DETERMINATION` recall | ≥ 0.97. Missing one means answering something we must not answer |
| S3 | `CRISIS` recall | ≥ 0.99, and it must fire before any other node runs |
| S4 | Uncited claims in generated output | Zero. Structurally enforced |
| S5 | Stale source usage without a flag | Zero |
| S6 | Durable resume after restart | State identical, verified by hash |
| S7 | Reading level of client-facing output | Plain English target, measured |

### 6.1 What this project is for

Closing the LangGraph and multi-agent orchestration gap, by building something
where the orchestration is genuinely necessary: a supervisor routing between
specialist retrieval agents, a planning step that produces a graph rather than a
list, and human-in-the-loop checkpoints that pause for days and resume correctly.

---

## 7. Constraints, assumptions and risks

### 7.1 Constraints

| ID | Constraint | Implication |
|---|---|---|
| CN1 | Solo, part-time | Ruthless sequencing. The safety layer ships before the polish |
| CN2 | The corpus must be real and dated | Curation is manual in v1 and that is a feature, since a wrong source is worse than no source |
| CN3 | No real personal data, ever, including in testing | Synthetic personas only. See NG5 |
| CN4 | LLM cost | Supervisor routing is the expensive part; cache aggressively, use a small model for classification |

### 7.2 Assumptions

| ID | Assumption | How it gets validated |
|---|---|---|
| A1 | Prerequisites can be expressed as a DAG | Validated in M1 by building the reference plan set. If cycles appear, the model is wrong |
| A2 | A deterministic classifier can catch `CRISIS` reliably | Tested against a corpus. This one must not rely on an LLM alone |
| A3 | Retrieval over a curated corpus is enough for `PROCEDURAL` questions | Measured in M3 |
| A4 | Caseworkers will accept a queue of escalations rather than resenting it | **Unvalidated and the biggest product risk.** Needs a real conversation with an NGO, not a guess |

### 7.3 Risks

| ID | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | The system gives advice that harms someone | L | **Very high** | The entire safety architecture. NG1-NG3, the refusal taxonomy, citation binding, staleness gating. This risk is why the project is designed the way it is |
| R2 | Sources go stale and nobody notices | H | H | Every source carries `last_verified`; staleness downgrades answers automatically |
| R3 | It reads as a toy that trivialises a serious situation | M | H | Ground it in real sourced content for one jurisdiction, and be explicit in the README about what it is not |
| R4 | Scope creep into case management | M | M | §5.2 |
| R5 | The crisis detector misses something | L | **Very high** | Deterministic patterns first, generous over-triggering, and an eval corpus. Over-escalation is a cost worth paying |

---

## 8. Milestones

| M | Deliverable | Demoable |
|---|---|---|
| M0 | This design package | - |
| M1 | Plan graph engine: task model, prerequisites, topological ordering, blocked detection | Yes. "Here is a real plan with a real critical path" |
| M2 | Source corpus, curated and dated, plus retrieval | Yes |
| M3 | **Question taxonomy, classifier, crisis escalation, eval gate** | **Yes. This is the milestone that matters** |
| M4 | LangGraph assembly: supervisor, domain subgraphs, `interrupt()` handoff, checkpointing | Yes. The durable-pause demo |
| M5 | Citation binding, entailment check, staleness gating, plain-language pass | Yes |
| M6 | Caseworker queue and client plan view, deployment | Yes |

**M3 before M4 is deliberate.** The safety layer exists before the thing it
protects. Building the agent first and adding guardrails later produces a system
whose guardrails are an afterthought, and it shows.
