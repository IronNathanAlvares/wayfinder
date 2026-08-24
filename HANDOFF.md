# Handoff

**Read this first.** It tells you what exists, what to build, and the things that
are easy to get wrong.

---

## Where things stand

**M1 to M6 are built.** 645 tests, mypy strict across 89 source files, four
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
site/           the demo site. Static, no dependencies, no network requests
scripts/        the demo script and the site data generator
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

**1. The crisis screen misses 8 turns in 320, and certifying the gate now needs
a bigger corpus rather than a better screen.** The shipped configuration scores
**0.975, lower bound 0.955**, against a gate of 0.99. The rest of this section
is the seven rounds it took to get there and what each one ruled out; read the
last three paragraphs first if you only want the current state.

The held-out corpus is 320 crisis turns and 156 near misses. The first number
measured against it was `claude-haiku-4-5` behind the lexicon at **0.897, lower
bound 0.865**, and everything below follows from trying to move it.

Thirteen of the thirty-three misses are self-harm items, and they are the
recognised warning signs: giving away possessions, arranging care for a child, a
note, a goodbye, a previous attempt. Both layers are good at stated emergencies
and poor at implied ones, and self-harm is the category people almost never
state.

The prompt has since been rewritten from the clinical taxonomy and validated on
a second split, `crisis-holdout-v2`, written for the purpose. **Self-harm recall
went from 0.481 to 0.685 and detention fell from 0.963 to 0.778, so the overall
number did not move.** Precision held: 13 false positives against 14.

That was tested on a third split and **the hypothesis holds.** Giving detention
its own section took it from 0.796 to 1.000, every one of 54 turns, p = 0.001.
Expanding the other four as well then cost self-harm, p = 0.016. Attention is a
budget: each category gains what the others pay for. The aggregate still rises,
so expansion is a real gain, just not a free one.

Precision did not move at all: 10 false positives out of 180 in every arm, with
45 of those near misses written to be detention-adjacent and routine. The screen
got better rather than louder, which is the only reason the recall numbers mean
anything.

**V5 ships**, expanding detention only. It gains detention significantly over V2
and loses nothing significantly. V4 expands everything, scores higher overall,
and is not shipped: it pays for the extra with a significant self-harm loss, and
self-harm is the category that cannot be asked twice.

**All three splits are now spent.** v1 and v2 answered two questions each and v3
answered one. Write a fourth before measuring another prompt change.

**Per-category screening was tried and does not help.** Six calls per turn
carrying the same sections scored 0.891 against V4's 0.884, paired p = 0.80.
The competition is not a packaging artefact. Precision did not suffer either,
six false positives against seven, so the reason not to build it is that it buys
nothing rather than that it is unsafe.

**Four rounds now say the same thing.** Putting a model behind the lexicon took
recall from 0.10 to 0.85. Everything since has moved it between 0.85 and 0.93
and never near 0.99, across four held-out splits and two thousand items. The
ceiling is a property of the approach, not of any prompt.

**Repeated sampling was tried and is exhausted.** Three samples gained two
turns, p = 0.50. The reason is in the stability data: only 1.7 percent of
verdicts move at all, non-crisis verdicts never moved once across 122 turns, and
35 of 288 crisis turns are missed by every sample. The ceiling of infinite
resampling is exactly what three samples already reached.

**Twenty-five turns are missed by every configuration ever measured**, and the
best union of all of them scores 0.922 against a gate that allows three misses
in 320. The residue is almost all self-harm and includes a disclosure of a
previous attempt, which is the strongest predictor there is.

**That was tested and it changed everything.** Same prompt, same items, only
the model: Haiku + V5 scores 0.856 and **Opus 5 + V5 scores 0.975 (312/320),
bound 0.955**, paired p = 0.0000. Self-harm goes from 0.648 to every one of 54.
Precision costs 13 false positives in 200 against 7.

`DEFAULT_MODEL` was already `claude-opus-5`, so the shipped configuration has
not changed. What changed is that it is measured rather than assumed. Every
number in this project before that run was Haiku, chosen for evaluation cost,
and that choice quietly became what four rounds of conclusions were about.

**The gate is still not met, and now the corpus is the binding constraint.** The
bound is 0.955 against 0.99, and a perfect 320 of 320 on a 320-item split only
bounds at 0.9907. Certifying 0.99 needs on the order of a thousand items at
Opus's observed rate, not a better screen.

So the remaining work is:

1. **A bigger crisis corpus.** Written to the same protocol, and by somebody who
   did not write the rules, which has been the standing gap since ADR-0008 was
   first written. Whoever writes it needs telling what item 2 found, because a
   split written the natural way will not contain the items that would move
   anything.
2. **The eight misses are one failure mode, and it now has a name.** All eight
   fall in two of six categories, against 2.65 expected if they were spread at
   random (Fisher exact p = 1.2e-4); the other four categories are perfect at
   214 of 214. Not one of the eight describes danger. Every one describes a
   process outcome in the process's own vocabulary: a council warning, a list,
   an address requirement, a file. **The screen recognises danger described as
   danger, including implied danger. It does not recognise danger described as
   administration.** Analysis in ADR-0008; note that a prompt round targeting
   this risks paying for it out of self-harm, per change 21.
3. ~~Cost and latency of Opus.~~ **Done.** 2.24 s p50, $0.0102 per turn, and the
   model is 99.87 percent of the wait. See
   [`15-latency-and-cost.md`](docs/15-latency-and-cost.md). What is left is p99
   and concurrency, which need load rather than a sample.

Getting a corpus written by somebody who did not write the rules is still the
highest-value item available and still not something testing substitutes for.

**2. The remaining blocked sources, and a deadline field.**
citizensinformation.ie **is now retrieved and cited** (24 August 2026). Its 403
was real for a bare client, but the address in the design also 404s: the page
moved. Worth remembering, because a source recorded as unreachable stops being
retried. It brought two facts nothing else in the corpus had: that asylum
seekers are not regarded as habitually resident, and that a social welfare
appeal has a 60 day window.

gov.ie's operational guidelines still 403, and irishimmigration.ie still 404s at
the design's URL. Under ADR-0005 those stay uncited.

The modelling gap that surfaced is bigger than either: **tasks have
`typical_wait` and no way to express a deadline.** The 60 day appeal window sits
in prose inside `why` because there is nowhere else to put it. A wait and a
deadline are opposite things, one is time you spend and the other is time you
lose, and for a system whose premise is that timing matters that is a real hole
in the model rather than a missing field.

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

**5. The applicant endpoints have no authentication, and thread ids are bearer
capabilities.** The caseworker queue is done: it is behind a token, and the name
on a determination now comes from that credential rather than from a free-text
field in the body, which is the half that actually mattered (change 27 in
`12-changes-from-design.md`). What is not done is the applicant side. Anybody
holding a thread id can read that plan and post turns to it.

That is a deliberate consequence of the applicant not having an account:
requiring registration before somebody can find out where the nearest GP is
defeats the point of the project.

The guessing half is now closed (change 28): the server mints the id, 256 bits
from `secrets`, and the caller cannot choose one. What is left is inherent to
capabilities rather than a defect: an id that leaks is an id somebody else
holds, and the server cannot tell. Keeping it out of referrer headers, logs and
shared screens is a deployment concern, and `DELETE /v1/threads/{id}` is the
revocation.

Still missing around it: no TLS, no rate limiting, no revocation beyond editing
the registry and restarting, and the SQLite file is not encrypted at rest.
[`14-getting-started.md`](docs/14-getting-started.md) §11 is the full list and
[`10-risk-and-ethics.md`](docs/10-risk-and-ethics.md) section 5 is the ethics
statement of it.

**6. SQLite only.** `sqlite_checkpointer` is the one implementation. Postgres is
what the design assumes for deployment and the swap is small, but it is not
done, and the deserialisation allowlist in `checkpoint.py` would need to carry
over with it.

**7. The Docker image works and has never been deployed anywhere.** It builds,
it refuses to start without a crisis screen, and a real turn goes through it;
CI does all three on every push. Nothing has run it for longer than a smoke
test, so nothing is known about it under any real load or over any real time.

**8. Concurrency and p99 are still unmeasured.** Single-caller latency and cost
are done: **2.24 s p50, $0.0102 per turn**, and the model is 99.87 percent of
the wait, so there is nothing worth tuning below it.
See [`15-latency-and-cost.md`](docs/15-latency-and-cost.md).

What is left is the part that needs load rather than a sample. Forty sequential
calls cannot establish p99, and p99 is where this matters: a call over the 8
second timeout returns `DEGRADED`, meaning the turn went unscreened, so the far
tail is the rate at which the safety layer silently stops working. Nothing here
says what happens under concurrency, rate limits, or contention either.

Prompt caching is the open cost decision. It would cut the bill 81 percent, to
$1.93 per thousand turns, but only above roughly 15 turns an hour; below that a
cold cache makes every call more expensive than sending it uncached. Which side
of that a deployment sits on is not known, which is why it is not implemented.

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
