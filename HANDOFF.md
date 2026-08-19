# Handoff

**Read this first.** It tells you what exists, what to build, and the things that
are easy to get wrong.

---

## Where things stand

**M1 to M6 are built.** 409 tests, mypy strict across 74 source files, four
import-linter contracts kept, 93 percent coverage, green in CI. A question goes
in through `wayfinder ask` or the API, gets classified, and comes back either as
an answer with dated citations, as a phone number, as a refusal that names
somebody else, or as a paused thread waiting on a caseworker.

Run `uv run python scripts/demo.py` to see all of it in about four seconds.

**What is built and what merely exists.** Everything listed above is called by
something. There is no module in `src/` that nothing reaches: the import graph is
checked by import-linter and the coverage floor is 90 percent. The two pieces
that exist without being exercised in normal use are `wayfinder.safety.llm`,
which needs a key, and `wayfinder.eval.compare`, which is a measurement tool
rather than a runtime path. Both have offline tests against injected fakes.

**Two of the design's headline safety claims were unprovable as written.**

[ADR-0007](docs/adr/ADR-0007-topology-proof-method.md): the topology test as
sketched would have gone green while the property it names was false, because
`path.taken_when(...)` does not exist and a compiled graph exports every
conditional-edge target as an edge. The replacement is a declarative route table
plus a deletion test that removes the human node and proves generation becomes
unreachable.

[ADR-0008](docs/adr/ADR-0008-crisis-recall-needs-a-model.md): the deterministic
crisis screen measures 0.167 recall on held-out data against a gate of 0.99,
which invalidates PDD assumption A2. A model screen behind the lexicon takes it
to 1.000 with no false positives, but twelve held-out items can only demonstrate
0.78 at 95 percent confidence and certifying the gate needs 299 consecutive
successes. **The gate is still unmet**, now because the corpus is too small
rather than because the approach cannot reach it.

All sixteen changes are in
[`docs/12-changes-from-design.md`](docs/12-changes-from-design.md).

```
02-wayfinder/
├─ README.md                what it is
├─ HANDOFF.md               this file
└─ docs/
   ├─ 00-INDEX.md           reading orders
   ├─ 01-research-and-analysis.md
   ├─ 02-PDD.md             goals, non-goals, users, scope, risks
   ├─ 03-requirements.md
   ├─ 04-HLD.md             the graph
   ├─ 05-LLD.md             modules, state, node contracts, corpus format
   ├─ 06-plan-graph-design.md      core contribution 1
   ├─ 07-safety-and-escalation.md  core contribution 2
   ├─ 08-roadmap.md         milestones and estimates
   ├─ 09-test-and-eval-plan.md
   ├─ 10-risk-and-ethics.md
   ├─ 11-interview-pitch.md
   ├─ 12-changes-from-design.md   what building it proved wrong
   └─ adr/ADR-0001..0008
```

```
src/wayfinder/
├─ plan/        the DAG engine. No I/O, no framework, no model
├─ safety/      three ordered layers, plus the optional model screen
├─ corpus/      loading, validation, staleness banding
├─ retrieval/   BM25 with a two-term match floor
├─ graph/       the compiled LangGraph, the routes table, the checkpointer
├─ eval/        the CI gate and the model comparison runner
├─ api/         threads, turns, the caseworker queue, the corpus alarm
└─ cli/         plan, diff, corpus, ask, serve
```

**Minimum before writing code:** `02-PDD.md`, `04-HLD.md`,
`06-plan-graph-design.md`, `07-safety-and-escalation.md`, and
`adr/ADR-0004-no-determinations.md`.

---

## The five things that matter

1. **It never makes an eligibility determination.** Structurally, not by prompt.
   No edge exists from a determination question to a generated answer. There is a
   test that walks the compiled graph and proves it. ADR-0004 is immutable.

2. **The plan is a DAG.** Ordering is computed, not generated. The valuable output
   is the frontier plus the minimal unblocking set for anything blocked.

3. **The crisis path has no LLM in it.** Deterministic lexicon, static dated
   directory, terminal. It over-triggers on purpose.

4. **The handoff is a multi-day durable pause.** `interrupt()` plus a
   checkpointer. Test it by killing the process mid-pause.

5. **Every claim carries a dated citation.** Unsupported claims are dropped, never
   hedged, because "you may be entitled to" is still an entitlement claim.

---

## Build order

Follow `08-roadmap.md`. The sequencing is deliberate: **M3, the safety layer,
comes before M4, the agent.** Building the agent first and adding guardrails
afterwards produces a system whose guardrails are an afterthought, and it shows.

| M | What | Hours |
|---|---|---|
| M1 | Plan graph engine. Pure Python, no LLM, no framework | 22 |
| M2 | Corpus and retrieval. Slow, unglamorous, load-bearing | 20 |
| M3 | **Safety layer, classifier, eval gate** | 24 |
| M4 | LangGraph assembly, supervisor, subgraphs, handoff | 24 |
| M5 | Composition, verification, staleness, plain language | 18 |
| M6 | API, caseworker queue, deployment | 14 |

All six are built. The estimates held roughly, with M3 running long because
measuring the crisis screen honestly meant discovering it did not work.

---

## Check these before trusting the design

The design was written on 17 August 2026. Two things drift.

**LangGraph. Checked on 18 August 2026 and the design holds.** `langgraph
1.2.11`, `langgraph-checkpoint 4.2.0`, `langgraph-checkpoint-sqlite 3.1.1`,
`langchain-core 1.5.6`, `pydantic 2.13.4`. `interrupt()`, `Command(resume=...)`,
`GraphInterrupt` and `SqliteSaver` all exist as assumed. One incidental
correction for M4: `BranchSpec` exposes `ends`, not `path_map`.

What did *not* hold was the assumption that compiled-graph topology alone can
prove the no-determination-path claim. See ADR-0007.

**The corpus sources.** Every URL in `01-research-and-analysis.md` §5 is research
for the design, not verified content. Re-check each at build time and record a
real `last_verified`. A source without a date fails the build by design.

Checked on 18 August 2026: four were reachable and are cited in the seed corpus.
citizensinformation.ie and gov.ie returned 403, and the irishimmigration.ie URL
returned 404. The tasks that would have cited them are absent, which is the rule
working. The visible cost is that the Habitual Residence Condition, the
canonical determination in this design, is not modelled yet. See
`src/wayfinder/corpus/data/README.md`.

---

## Things that will be tempting and are wrong

| Tempting | Why not |
|---|---|
| Answer determinations with a disclaimer | "You may be entitled to X" is still an entitlement claim, and it sounds like permission to plan around it |
| Let the LLM supervisor decide when to escalate | A model can be talked out of escalating. Deterministic layers first |
| Use a swarm because it is more interesting | The safety claim needs an enumerable path set. ADR-0002 |
| Scrape the corpus to get coverage faster | A wrong prerequisite costs somebody a wasted journey they cannot afford. ADR-0005 |
| Skip the `boundary` eval split | Precision on procedural questions is meaningless without minimal pairs |
| Add reminders, appointments, form filling | That is case management, a different product. PDD §5.2 |
| Cover five countries | Depth beats breadth. Shallow coverage here is harmful, not merely less useful |

---

## Conventions

Carried over because they worked on the previous project.

- Python 3.12 via `uv`. `ruff`, `mypy --strict`, `pytest`, `import-linter`.
- `plan/` and the deterministic parts of `safety/` import nothing with I/O or a
  framework dependency. Enforce it with an import-linter contract so the claim
  cannot decay.
- The safety classifier is gated in CI like a model: labelled corpus, precision
  and recall, committed baseline, fails the build on regression.
- Exit codes: 0 pass, 1 verdict of fail, 2 could not evaluate. Never collapse 1
  and 2.
- Comments explain **why**, not what. If a decision is non-obvious, the reasoning
  goes next to the code.
- Prose style: plain and direct. No em dashes.
- Every refusal names an alternative. A refusal that leaves somebody stuck is a
  failure, not a safety win.

---

## What is left

Ordered by how much it matters, not by how hard it is.

**1. The crisis screen misses about one turn in ten, and the misses are
self-harm.** The held-out crisis corpus is now 320 crisis turns and 156 near
misses, which is large enough to certify the 0.99 gate. Measured against it,
`claude-haiku-4-5` behind the lexicon scores **0.897, lower bound 0.865**. The
gate is not met.

Thirteen of the thirty-three misses are self-harm items, and they are the
recognised warning signs: giving away possessions, arranging care for a child, a
note, a goodbye, a previous attempt. Both layers are good at stated emergencies
and poor at implied ones, and self-harm is the category people almost never
state.

**Do not fix this by editing the prompt against those thirty-three turns.** That
burns the only large held-out split the project has. The order of work is in
[ADR-0008](docs/adr/ADR-0008-crisis-recall-needs-a-model.md): rewrite the prompt
from the clinical warning-sign taxonomy rather than from the category names,
validate on a fresh split written to the same protocol, and run it more than
once because the screen is not deterministic.

Getting the corpus written by somebody who did not write the rules is still the
highest-value item available and still not something testing substitutes for.

**2. The Habitual Residence Condition is still not in the corpus.**
citizensinformation.ie and gov.ie return 403 to the fetcher, so the canonical
determination in this whole design, the one the README leads with, is the one
thing the corpus cannot cite. Everything around it works. The gap is content,
and under ADR-0005 an unverified source cannot be cited, so it stays absent
until somebody obtains the pages a way that produces a real `last_verified`.

**3. The corpus is 20 tasks against a design that describes about 40.** Four
domains are covered properly. Employment, and the transition after a protection
decision, are not covered at all.

**4. Nothing generates prose.** Composition works, is verified, and is measured
for reading age, but `default_composer` is extractive: it states what the
retrieved spans say and attaches their sources. The `Composer` protocol exists
and takes a model implementation, and nothing implements it. That is a
deliberate ordering, since the citation rule is satisfied structurally by
extraction and a model composer has to be evaluated against it rather than
trusted, but it does mean the system does not yet write.

**5. The API has no authentication.** `/v1/queue` exposes what people have said
about their own circumstances to anybody who can reach the port. Fine for a
local demo, disqualifying for anything else, and
[`10-risk-and-ethics.md`](docs/10-risk-and-ethics.md) section 5 is the honest
statement of that gap.

**6. SQLite only.** `sqlite_checkpointer` is the one implementation. Postgres is
what the design assumes for deployment and the swap is small, but it is not
done, and the deserialisation allowlist in `checkpoint.py` would need to carry
over with it.

**7. The Docker image works and has never been deployed anywhere.** It builds,
it refuses to start without a crisis screen, and a real turn goes through it;
CI does all three on every push. Nothing has run it for longer than a smoke
test, so nothing is known about it under any real load or over any real time.

**8. No load or latency measurement.** The crisis screen's timeout is 8 seconds
and its latency is part of its safety story, and nobody has measured what a real
turn costs end to end.

---

## Open questions

Genuinely open. Do not paper over them.

| # | Question | Suggested handling |
|---|---|---|
| 1 | Will caseworkers accept the escalation volume, or resent it? PDD A4 | The largest product risk. Worth asking an actual NGO before M6 |
| 2 | Is the corpus better organised by domain or by life stage? | Try domain first, since retrieval is domain-scoped. Revisit if intake feels wrong |
| 3 | How much does the intake interview ask before producing anything? | Bias hard toward less. Somebody in distress should not face twenty questions |
| 4 | Multilingual in v1.1 needs a safety eval per language | Do not ship a translated refusal that has not been evaluated in that language |

---

## Prompt for the new session

Copy from here down.

---

I want to build a project called **Wayfinder**. The complete design package
already exists and I want you to read it before writing any code.

**Location:** `C:\Users\natha\OneDrive\Desktop\Things I learn\Portfolio Projects\02-wayfinder`

Start by reading `HANDOFF.md`, then `docs/00-INDEX.md`, then at minimum
`docs/02-PDD.md`, `docs/04-HLD.md`, `docs/06-plan-graph-design.md`,
`docs/07-safety-and-escalation.md` and `docs/adr/ADR-0004-no-determinations.md`.
Read the other docs as they become relevant.

**What it is:** a LangGraph agent team that turns "I have just arrived in Ireland,
what do I do?" into an ordered plan with prerequisites, where every statement
carries a dated citation, and where any question needing a judgement about that
person's entitlements is handed to a human caseworker instead of being answered.

**This is a standalone project.** It has no connection to any other project of
mine. Do not reference or depend on anything else. The point of it is to learn
LangGraph and multi-agent orchestration properly, so the orchestration should be
genuinely necessary rather than decorative.

**The two things that make it worth building**, and both are already designed:

1. The plan is a dependency graph, not a list. Ordering is computed rather than
   generated, and the useful output is what you can start now plus the minimal
   set of tasks that unblocks anything blocked.
2. It refuses to make eligibility determinations, structurally. There is no path
   in the graph from a determination question to a generated answer, and a test
   proves it by walking the compiled graph.

**Before you start:** check the installed LangGraph version against what the
design assumes, which is 1.x with `interrupt()` and `Command(resume=...)`. If they
disagree, the installed version wins. Tell me what changed and update the design
doc rather than working around it.

**Build order:** follow `docs/08-roadmap.md`. Start with **M1, the plan graph
engine**. It is pure Python, needs no API keys, and produces a real demo on its
own. Do not start on the LangGraph assembly until the safety layer in M3 exists.

**How I want you to work:**

- Set up the repo properly first: `uv`, Python 3.12, ruff, mypy strict, pytest,
  import-linter, and CI. Quality bar on day one, not retrofitted.
- Comments explain why, not what.
- Plain, direct prose everywhere. No em dashes.
- If you find something in the design that is wrong or that reality contradicts,
  tell me and fix the doc. Do not quietly work around it.
- Tell me honestly what is built and working versus what merely exists. If a
  component is written but nothing calls it, say so.
- Create a public GitHub repo under `IronNathanAlvares` when there is something
  worth pushing, and keep CI green.

Start by reading the docs, then tell me your plan for M1 and anything in the
design you disagree with.
