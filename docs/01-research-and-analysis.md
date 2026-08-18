# 01. Research and analysis

**Project:** Wayfinder · **Date:** 17 August 2026

---

## 1. LangGraph, current state

Version at time of writing: **LangGraph 1.x** (1.2.x line). 1.0 shipped in
October 2025 and stabilised four runtime features that matter here.

| Feature | Why this project needs it |
|---|---|
| **Durable execution** | State is checkpointed at every superstep. A caseworker handoff can take days and survive a restart |
| **Human in the loop** | `interrupt()` pauses the graph and surfaces a payload |
| **Streaming** | Tokens, tool calls, state updates and node transitions |
| **Memory** | Checkpointers back onto SQLite or Postgres |

### 1.1 The interrupt API

`interrupt()` is the current standard. The older `NodeInterrupt` exception class
is superseded. Mechanically:

- `interrupt()` raises a `GraphInterrupt` which the executor catches at the top
  of the execution loop, unwinding the call stack cleanly without corrupting
  state.
- The executor serialises the full state snapshot, including every state key at
  the moment of interruption, under the current `thread_id`, and records which
  node interrupted and the interrupt payload.
- Resume with `Command(resume=...)`.

That last point is the whole reason LangGraph is the right tool here rather than
a hand-rolled state machine. The handoff in this project is not a confirmation
dialog, it is a pause that may last days.

Relevant packages: `langgraph`, `langgraph-checkpoint`,
`langgraph-checkpoint-sqlite`, `langgraph-checkpoint-postgres`.

### 1.2 Supervisor versus swarm

Two patterns. In a **swarm** agents hand off directly to each other using
`Command` objects returned from handoff tools. In a **supervisor** there is one
routing node, clear control flow, and every decision visible in traces.

Current guidance is unambiguous: start with the supervisor. It is simpler to
build and debug, and routing accuracy matters more than the latency penalty in
early deployments. Swarms need budget limits, handoff schemas, loop detection,
tool isolation and observability before they are safe to run.

There is also a documented anti-pattern: do not use a supervisor for strictly
sequential work, or single-step retrieval. Supervisors add latency and token
cost, and are only justified when routing genuinely requires reasoning.

**For this project the argument goes further than "start simple".** The safety
claim is that no path exists from a determination question to a generated answer.
With explicit supervisor edges that is checkable by walking the compiled graph.
In a swarm, where any agent may hand to any other, it becomes an argument rather
than a proof. See ADR-0002.

### 1.3 What this implies for the design

- Supervisor pattern, domain agents as subgraphs that do not route to each other.
- Checkpointer is not optional, it is what makes the handoff real.
- The supervisor needs a capable model; classification does not and should not
  use one for the deterministic layers.

---

## 2. The domain

Jurisdiction for v1 is **Ireland**, chosen for one reason: depth beats breadth
here, and a shallow system spanning five countries would be actively harmful.

### 2.1 The prerequisite structure is real

This is not a contrived dependency graph.

- **PPS number.** A unique reference needed to access public services. Typically
  applied for at the same time as the protection application, at the
  International Protection Office or Citywest, and collected from a local Social
  Welfare Office within a few working days.
- **IPAS.** International Protection Accommodation Services, a unit of the
  Department of Justice, responsible for accommodation for people in the
  protection process. An IPAS letter is often the evidence that unlocks other
  steps.
- **Habitual Residence Condition.** Gates entitlement to a number of social
  welfare payments. The Department distinguishes between those granted protection
  and those who have not yet been. It is assessed on five factors, and the
  guidance is explicit that not all five need be satisfied, only that Ireland is
  shown to be the main centre of interest.

The HRC is the clearest example of why the `determination` prerequisite kind
exists. It is a multi-factor judgement made by a named authority. Describing how
it is assessed is procedural and safe. Telling somebody whether they satisfy it
is a determination, and this system must not do it.

### 2.2 Sources for the corpus

Primary, and all dated on ingestion:

| Source | Covers |
|---|---|
| Citizens Information | The broadest plain-language coverage of processes and entitlements |
| gov.ie, Department of Social Protection operational guidelines | Authoritative on welfare, including IPAS-specific guidance |
| International Protection Office | The protection process itself |
| IPAS | Accommodation |
| Irish Refugee Council | Practical guidance, information hub, PPSN and homelessness |
| NASC | Know your rights, asylum in Ireland |
| UNHCR Ireland help pages | Accommodation and where to seek help |
| HSE | Healthcare access, medical cards, GP registration |

Curation is manual in v1 and that is a deliberate choice, not a shortcut. See
`06-plan-graph-design.md` §8.

---

## 3. What already exists, and the gap

| Category | Examples | What it does not do |
|---|---|---|
| Static information sites | Citizens Information, NGO information hubs | Excellent reference. Cannot tell you what applies to *your* situation or in what order |
| Printed checklists | Orientation packs | Fixed order for everyone. No prerequisite reasoning, stale the day they print |
| General chatbots | A general model asked about immigration | Fluent, uncited, confidently wrong about entitlements, no idea when rules changed |
| Caseworkers | NGO support workers | The actual answer, and severely rationed |

**The gap:** nothing turns a specific situation into an ordered plan with
prerequisites while refusing to make determinations. Static sites cannot
personalise. General chatbots personalise and will happily make determinations,
which in this domain is the dangerous failure. Caseworkers do it properly and
there are not enough of them.

Wayfinder sits deliberately between the last two: personalised on *process*,
never on *entitlement*, and its main output for a caseworker is a client who
arrives knowing what to ask.

---

## 4. Design conclusions

Five constraints fall out of the research.

1. **The plan is a DAG.** The prerequisite structure is real and load-bearing, so
   ordering should be computed, not generated. → `06-plan-graph-design.md`
2. **Determination must be structurally unreachable.** HRC is the canonical
   example: describable, not applicable-by-a-machine. → `07-safety-and-escalation.md`
3. **Supervisor, not swarm**, because the reachable path set has to be
   enumerable to make the safety claim checkable. → ADR-0002
4. **The handoff is a real pause**, days long, which makes the checkpointer a
   core dependency rather than an optimisation. → ADR-0003
5. **Sources must be dated**, because rules change and a stale page is
   indistinguishable from a current one at a glance. → ADR-0005

---

## 5. Sources

**LangGraph**
- [Human-in-the-loop and interrupts (DeepWiki, langchain-ai/langgraph)](https://deepwiki.com/langchain-ai/langgraph/3.7-human-in-the-loop-and-interrupts)
- [LangGraph releases](https://github.com/langchain-ai/langgraph/releases)
- [langgraph.checkpoint reference](https://reference.langchain.com/python/langgraph.checkpoint)
- [langgraph.store reference](https://reference.langchain.com/python/langgraph.store)
- [LangGraph 1.0, production ready](https://medium.com/@romerorico.hugo/langgraph-1-0-released-no-breaking-changes-all-the-hard-won-lessons-8939d500ca7c)
- [Multi-agent orchestration: supervisor vs swarm, tradeoffs and architecture](https://focused.io/lab/multi-agent-orchestration-in-langgraph-supervisor-vs-swarm-tradeoffs-and-architecture)
- [LangGraph multi-agent patterns that work in production](https://123ofai.com/articles/blogs/langgraph-multi-agent)
- [The multi-agent trap](https://towardsdatascience.com/the-multi-agent-trap/)
- [LangGraph agents in production: architecture, costs, outcomes](https://www.alphabold.com/langgraph-agents-in-production/)

**Domain**
- [Irish Refugee Council, PPSN](https://www.irishrefugeecouncil.ie/get-help/information-hub/applied-before-12-june-2026/ppsn/)
- [Irish Refugee Council, homeless international protection applicants](https://www.irishrefugeecouncil.ie/get-help/information-hub/information-for-homeless-international-protection-applicants/)
- [NASC, know your rights: asylum in Ireland](https://nascireland.org/know-your-rights/asylum-ireland)
- [Operational guidelines: social welfare entitlements for people in IPAS accommodation](https://www.gov.ie/en/department-of-social-protection/publications/operational-guidelines-social-welfare-entitlements-for-people-in-international-protection-accommodation-provided-by-ipas/)
- [Habitual Residence Condition (Crosscare)](https://diasporasupport.ie/returning-to-ireland/habitual-residence-condition/)
- [UNHCR Ireland, accommodation for asylum seekers](https://help.unhcr.org/ireland/where-to-seek-help/accommodation-for-asylum-seekers/)
- [International Protection Accommodation Services](https://en.wikipedia.org/wiki/International_Protection_Accommodation_Services)

> **Note for whoever builds this.** Every one of these needs re-checking at build
> time and recording with a `last_verified` date. They are cited here as research
> for the design, which is not the same as being verified for the corpus.
