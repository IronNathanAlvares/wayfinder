# 00. Documentation index

**Project:** Wayfinder
**What it is:** A LangGraph agent team that turns "I have just arrived, what do I
do?" into an ordered plan with prerequisites, and refuses to answer the questions
that need a human.
**Author:** Nathan Alvares · **Date:** 17 August 2026 · **Status:** M1 to M6 built, 669 tests green. See [`12-changes-from-design.md`](12-changes-from-design.md)

> **Standalone project.** No dependency on anything else. Nothing else needs to
> exist for it to run.

---

## Reading orders

**Five minutes:** [`README.md`](../README.md), then
[`11-interview-pitch.md`](11-interview-pitch.md) §1.

**To understand the design:** [`02-PDD.md`](02-PDD.md) →
[`04-HLD.md`](04-HLD.md) → [`06-plan-graph-design.md`](06-plan-graph-design.md) →
[`07-safety-and-escalation.md`](07-safety-and-escalation.md).

**To run it:** [`14-getting-started.md`](14-getting-started.md). Clone, install,
every command, Docker, and the caseworker credentials.

**To build on it:** [`HANDOFF.md`](../HANDOFF.md) first, then
[`03-requirements.md`](03-requirements.md) → [`05-LLD.md`](05-LLD.md) →
[`08-roadmap.md`](08-roadmap.md).

**To evaluate the judgement:** [`07-safety-and-escalation.md`](07-safety-and-escalation.md) →
[`adr/ADR-0004`](adr/ADR-0004-no-determinations.md) →
[`10-risk-and-ethics.md`](10-risk-and-ethics.md).

---

## Documents

| # | Document | Answers |
|---|---|---|
| 01 | [Research and analysis](01-research-and-analysis.md) | What is LangGraph capable of right now, what does the domain actually look like, what already exists |
| 02 | [PDD](02-PDD.md) | What are we building, for whom, and what are we deliberately not building |
| 03 | [Requirements](03-requirements.md) | What exactly must it do, and how will we know |
| 04 | [HLD](04-HLD.md) | What is the graph, and why is it shaped that way |
| 05 | [LLD](05-LLD.md) | Modules, state schema, node contracts, corpus format, API |
| 06 | [Plan graph design](06-plan-graph-design.md) | **Core contribution one.** Why the plan is a DAG and how it is built |
| 07 | [Safety and escalation](07-safety-and-escalation.md) | **Core contribution two.** What it refuses to answer and how that is enforced |
| 08 | [Roadmap](08-roadmap.md) | In what order, how long, what will go wrong |
| 09 | [Test and eval plan](09-test-and-eval-plan.md) | Corpus, gates, topology tests |
| 10 | [Risk and ethics](10-risk-and-ethics.md) | Who can be harmed and what stops it |
| 11 | [Interview pitch](11-interview-pitch.md) | How to explain it, demo it, and defend it |
| 13 | [Deploying the site](13-deploying-the-site.md) | The static demo, its security headers, and why the API is not on Vercel |
| 14 | [Getting started](14-getting-started.md) | **Clone to running.** Every command, Docker, caseworker auth, and what is not secured |
| 15 | [Latency and cost](15-latency-and-cost.md) | What the crisis screen costs in seconds and dollars, and what ADR-0008's choice of Opus actually buys |
| 12 | [Changes from the design](12-changes-from-design.md) | **The twenty-nine things building it proved wrong, and what replaced them** |

## Decision records

| ADR | Decision | Why it matters |
|---|---|---|
| [0001](adr/ADR-0001-langgraph.md) | LangGraph 1.x | Durable execution is what makes a multi-day handoff real |
| [0002](adr/ADR-0002-supervisor-not-swarm.md) | Supervisor, not swarm | The reachable path set has to be enumerable for the safety claim to be checkable |
| [0003](adr/ADR-0003-durable-handoff.md) | Handoff is a durable pause | Caseworkers answer in days, not seconds |
| [0004](adr/ADR-0004-no-determinations.md) | **Never determines eligibility** | The immutable one. The whole architecture follows from it |
| [0005](adr/ADR-0005-dated-corpus.md) | Hand-curated dated corpus | A stale page looks exactly like a current one |
| [0006](adr/ADR-0006-deterministic-safety-layer.md) | Deterministic safety layer, pre-graph | A model can be talked out of escalating. A regex cannot |
| [0007](adr/ADR-0007-topology-proof-method.md) | How the topology claim is proved | The originally sketched test would have passed while the property was false |
| [0008](adr/ADR-0008-crisis-recall-needs-a-model.md) | **A deterministic crisis screen cannot reach 0.99 recall** | Measured at 0.17 held out. Invalidates PDD A2, amends ADR-0006 |

---

## The claims this package makes

| Claim | Defended in |
|---|---|
| The plan is genuinely a graph, and that is the useful part | `06` §1, §5 |
| Determination must be structurally unreachable, not discouraged | `07` §1, ADR-0004 |
| The crisis path must not contain a model | `07` §3, ADR-0006 |
| Supervisor beats swarm here for a safety reason, not just simplicity | ADR-0002 |
| The handoff is a real multi-day pause and that is why LangGraph earns its place | `04` §6, ADR-0003 |
| The corpus being partial and dated is a feature | ADR-0005 |
