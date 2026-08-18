# 11. Interview pitch and demo

**Project:** Wayfinder · For: Nathan Alvares · **Date:** 17 August 2026

---

## 1. Thirty seconds

> "Somebody who has just arrived in a new country faces about forty
> administrative tasks across a dozen agencies, and they have prerequisites
> nobody tells you about. You cannot apply for most things without a PPS number.
> You often cannot get a PPS number without proof of address. You may not get
> proof of address until accommodation is allocated. Getting the order wrong
> costs weeks, and if you have no income and two children, weeks matter.
>
> I built a LangGraph agent team that turns a situation into an ordered plan with
> those prerequisites made explicit, where every statement carries a dated
> citation.
>
> The part I would actually defend is what it refuses to do. It will tell you how
> the habitual residence condition is assessed. It will not tell you whether you
> satisfy it, because that is a legal determination made by a named authority,
> and a model that answers it confidently is somebody budgeting around money that
> is not coming. That refusal is structural: there is no path in the graph from a
> determination question to a generated answer, and there is a test that walks the
> compiled graph to prove it."

---

## 2. Two minutes, structure

1. **The problem** *(20s)*. Prerequisites, not information. The information is
   published; the ordering is not.
2. **Why a list is not enough** *(20s)*. Any model produces a competent bulleted
   list. It cannot tell you what is blocked and what unblocks it, because that is
   a graph property, not a prose one.
3. **What I built** *(40s)*. Supervisor routing to six domain subgraphs, a plan
   engine that computes ordering rather than generating it, citation-bound
   composition, and a human handoff that is a genuine multi-day pause.
4. **The bit worth arguing about** *(40s)*. The refusal boundary. Describing a
   rule is procedural, applying it to a person is a determination. That boundary
   is the product.

---

## 3. Demo, five minutes

| # | Action | The line |
|---|---|---|
| 1 | Situation in, plan out. No LLM involved | "This part is pure Python. The ordering is computed from a dependency graph, not generated, so it is the same every time and I can test it exactly." |
| 2 | Point at the critical path | "Do the PPS number first. Four things are waiting on it. That sentence comes from graph structure, and a language model has no reliable way to work it out from prose." |
| 3 | Show a blocked task and its unblocking set | "Not every unmet prerequisite. The smallest set of things you can start today that unblocks it. That is the answer to 'what do I do about this'." |
| 4 | Ask a procedural question | "Answered, with a citation and the date that source was verified." |
| 5 | **Ask the determination version of the same question** | "Same topic, same vocabulary, one word different. Refused, escalated, and still useful: it gives the process, names the authority, and names an organisation that helps." |
| 6 | Show the graph topology test | "That is not a prompt asking it to be careful. There is no edge. This test walks the compiled graph and asserts the path does not exist." |
| 7 | **Kill the process mid-handoff. Restart. Resume** | "The caseworker answers on Thursday a question asked on Monday. `interrupt()` checkpointed the whole state, and it comes back byte-identical. This is the feature that made LangGraph the right tool rather than a hand-rolled state machine." |
| 8 | Show the answer attributing the determination to the caseworker | "It does not restate her judgement in its own voice. That would launder human accountability into machine confidence." |
| 9 | Crisis input | "No model in this path at all. Pattern match, static directory, terminal. A model cannot be talked out of a regex and cannot mis-generate a phone number." |

Steps 5 and 6 together are the pitch. Everything else is supporting evidence.

---

## 4. Questions to expect

**"Why not just let the model answer with a disclaimer?"**
> Because "you may be entitled to X" is still an entitlement claim, and it is
> worse than saying nothing, because it sounds like permission to plan around it.
> The people using this often have no financial buffer. If they arrange their
> month around a payment that does not arrive, the disclaimer did not help them.
> So the boundary is structural rather than linguistic.

**"How do you draw the line between procedural and determination?"**
> Describing a rule is procedural. Applying a rule to this person is a
> determination. Practically, anything scoped to "I", "my" or "in my case" where
> the answer depends on that person's specific facts is a determination. I test it
> with minimal pairs: same topic, same vocabulary, one word different, opposite
> handling. That split is the most valuable part of the eval corpus, because
> precision on procedural questions is meaningless without hard negatives.

**"Why supervisor and not swarm? Swarm is more interesting."**
> Because my central safety claim is that no path exists from a determination
> question to a generated answer. With a supervisor and explicit edges I can walk
> the compiled graph and prove it. In a swarm, where any agent can hand off to any
> other, the reachable path set is large and dynamic and the claim becomes an
> argument. A safety property you can only argue for is one you will eventually be
> wrong about.

**"Why is there no LLM in the crisis path?"**
> Two reasons. A model can be talked out of escalating, and the input here is
> written by people in distress and sometimes by people testing the system. And a
> model can mis-generate a phone number. Neither of those risks is worth taking to
> gain fluency in a message that is four lines of a phone directory. It also
> over-triggers deliberately: the eval gate is 0.99 recall with no precision gate,
> because a false positive shows somebody helplines they did not need and a false
> negative is somebody sleeping outside.

**"What is the weakest part?"**
> Two things. The crisis lexicon covers phrasing I thought of, and multilingual or
> non-native phrasing is where it is thinnest. And I do not know whether
> caseworkers would accept the escalation volume or start ignoring the queue,
> which is the most likely way the whole safety design fails in practice. It is
> written down as an unvalidated assumption because it needs a conversation with
> an actual NGO, not a guess from me.

**"Why hand-curate the corpus? That does not scale."**
> It does not, and for this it should not. A wrong prerequisite sends somebody
> across a city for a document they cannot get, and they may not have the bus
> fare. Task granularity is also an editorial judgement: "apply for a PPS number"
> is one task because that is how a person experiences it, not seven because that
> is how the form works. Automated ingestion is a later version, and even then it
> should propose changes for review rather than write to the corpus.

**"Is this deployed?"**
> No, and I would not deploy it without a qualified adviser reviewing the corpus,
> a named organisation accountable for the escalation queue, and a data protection
> assessment. That list is in the docs. It is a portfolio project and it says so.

---

## 5. What this demonstrates

| Signal | Where |
|---|---|
| **LangGraph depth** | Supervisor with subgraphs, `interrupt()` with durable resume, checkpointer as a core dependency rather than a demo flourish |
| **Knowing when not to use an LLM** | The plan engine is pure computation. The crisis path is a regex. Both deliberate |
| **Safety as architecture** | The refusal is a missing edge with a test, not a prompt instruction |
| **Evaluation discipline** | Labelled corpus with minimal-pair hard negatives, CI gate, asymmetric thresholds justified by the cost matrix |
| **Product judgement** | Optimising for caseworker time rather than for the appearance of capability |
| **Honesty** | Named non-goals, an unvalidated assumption flagged as the biggest risk, a written list of what would be needed before real deployment |

---

## 6. It stands alone

Standalone project, no dependency on anything else I have built.

Built to learn LangGraph and multi-agent orchestration properly, on a problem
where the orchestration is genuinely necessary: routing that needs reasoning,
a plan that is a graph rather than a sequence, and a human checkpoint that pauses
for days and resumes correctly. If the human handoff were a confirmation dialog,
a framework would be overkill. It is not, and that is what earns it.
