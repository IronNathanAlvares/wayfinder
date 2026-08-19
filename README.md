# Wayfinder

A LangGraph agent team that turns "I have just arrived, what do I do?" into an
ordered plan with prerequisites, and refuses to answer the questions that need a
human.

**Status: M1 to M6 built. 409 tests, mypy strict, four import contracts.** A
question goes in through the CLI or the API, the safety layers classify it, a
determination pauses the graph for a named caseworker, and the answer comes back
with dated citations or with a refusal that names somebody who can help.

**Two of the design's headline safety claims turned out to be unprovable as
written, and finding that out is the most useful thing this project has
produced.** The topology test could not have proved what it claimed
([ADR-0007](docs/adr/ADR-0007-topology-proof-method.md)), and the deterministic
crisis screen scored 0.167 on held-out data against a gate of 0.99
([ADR-0008](docs/adr/ADR-0008-crisis-recall-needs-a-model.md)). Both were fixed
in the design rather than in the test.

Start with [`HANDOFF.md`](HANDOFF.md), and see
[`docs/12-changes-from-design.md`](docs/12-changes-from-design.md) for the
nineteen things building this proved wrong about the design.

Standalone project. Nothing else needs to exist for it to run.

---

## The problem

Somebody who has just arrived in a new country faces around forty separate
administrative tasks across housing, healthcare, schooling, welfare and legal
status. They are spread across a dozen agencies that do not talk to each other,
written in language meant for civil servants, and they have **hard prerequisites
that nobody tells you about**.

You cannot apply for most things without a PPS number. Getting one usually needs
evidence of address or of being in the protection process. Address evidence often
depends on accommodation being allocated, which is not something you control.

Getting the order wrong costs weeks. For somebody with no income and children,
weeks matter enormously.

---

## What it does

Takes a situation and produces an ordered plan with explicit prerequisites, where
every statement carries a citation to a dated source, and where any question
requiring a judgement about that person's entitlements goes to a human instead of
being answered.

```
"I arrived two weeks ago, applied for protection, I am in IPAS
 accommodation, no PPS number, one child aged 7."

  Start now
    Apply for your PPS number
    Get proof of address from IPAS
    Register with a GP

  Do the PPS number first. Four other things are waiting on it.

  Child benefit is blocked on a habitual residence decision.
  That is decided by the Department of Social Protection, not by you
  and not by me. Here is how it is applied for, and here is who can
  help you with it.
```

That last paragraph is the whole project: name the blocker, name the authority,
refuse to assess it, and still be useful.

---

## Running it

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups --all-extras
uv run python scripts/demo.py
```

That is the whole system in one run: a plan, a cited answer, an entitlement
question pausing for a caseworker, the caseworker's answer coming back
attributed, a six-week diff, and the corpus staleness check. No server, no
network, no key.

```bash
uv run wayfinder --today 2026-08-18 plan examples/amara-week-one.yaml
uv run wayfinder ask "how do I apply for a PPS number"
uv run wayfinder serve
```

The date is an input rather than a clock read, so the same situation always
produces the same plan. That is also why the engine is testable.

```bash
uv run wayfinder corpus check     # integrity: dates, references, citations
uv run wayfinder corpus health    # staleness bands, the maintenance alarm
uv run pytest                     # unit, property and persona tests
uv run lint-imports               # proves plan/ imports nothing with I/O
uv run wayfinder-eval             # the safety gate, against the design targets
uv run wayfinder-eval --baseline  # what CI runs: no regression
uv run wayfinder-compare          # crisis recall, deterministic only
```

The comparison against a model needs a key. The default split holds 500 turns,
so a run against one prompt is 500 requests:

```bash
uv sync --extra llm
ANTHROPIC_API_KEY=... uv run wayfinder-compare --model claude-haiku-4-5 --effort none --cache .eval-cache.json --save out.json
```

`--cache` makes an interrupted run resume for the price of what is left, keyed
on the model, the prompt and the turn together so a prompt edit never reads a
stale verdict. `--save` keeps the per-item misses, which are the half of the
result worth having. Both exist because two paid runs were lost without them.

`--prompt v1 --prompt v2` measures both prompts on the same items in one run,
which is the only way to attribute a difference to the prompt rather than to
the day.

`ask` and `serve` both exit 2 without `ANTHROPIC_API_KEY`, because the crisis
screen they would otherwise run with catches one crisis turn in six. Pass
`--no-model-screen` to accept that; it prints the measured number on stderr
every time.

Or in Docker, where there is no opt-out at all:

```bash
ANTHROPIC_API_KEY=... docker compose up
```

## The API

`uv run wayfinder serve`, then `http://127.0.0.1:8000/docs`.

| | |
|---|---|
| `POST /v1/threads` | Start a thread with a situation |
| `POST /v1/threads/{id}/turn` | Ask something. Answers, refuses, or pauses |
| `GET /v1/threads/{id}/plan` | What can start now, what is waiting, what is unknown |
| `DELETE /v1/threads/{id}` | Forget it. NG5, and it is expected to be used |
| `GET /v1/queue` | Everything waiting on a caseworker, with the context to answer it |
| `POST /v1/queue/{id}/respond` | A named person's answer, relayed rather than restated |
| `GET /v1/corpus/health` | **503** once a source has aged out of retrieval |

Two of those are the point. The queue is the endpoint the design optimises for,
because Clare the caseworker is the user whose time this project is actually
trying to save. And corpus health returns 503 rather than a green page with a
list of rotting sources on it, because staleness is the failure this system is
most likely to have while still looking fine, and an alarm nobody reads is not
an alarm.

The queue is read from the checkpointer, not from process memory, so it survives
a redeploy with paused threads intact. There is a test that builds the app twice
over one file to prove it.

---

## The number that matters

A hand-written crisis lexicon scores 1.000 on the corpus it was tuned against
and **0.138** on a held-out one. The design assumed a deterministic screen could
reach 0.99, and PDD assumption A2 said to validate that in M3. It was validated,
and it is false.

The response was not to add the missing phrases. It was to accept that a model
is load-bearing in the crisis path, and to constrain it so it can only ever add
a detection and never clear one, which preserves the property the determinism
was there to protect.

Then the model was measured, first on twelve held-out items and later on 320.

| Held out | 12 items | 320 items |
|---|---|---|
| Deterministic lexicon only | 0.167 | **0.138** |
| Lexicon + `claude-haiku-4-5` | 1.000 | **0.897** |

**Twelve items could not have told you that.** Twelve successes out of twelve
put the 95 percent lower bound at 0.78, so "1.000" was always consistent with a
true rate near 0.8, and the true rate turned out to be 0.897. Certifying a 0.99
gate takes 299 consecutive successes, which is why the held-out crisis split now
holds 320 crisis turns and 156 near misses.

**The gate is still not met, and now for the third distinct reason.** Not
because the approach cannot reach it, and no longer because the corpus is too
small. Because the screen misses about one crisis turn in ten, and most of its
misses are self-harm items of the kind clinical risk assessment treats as
highest-risk: giving away possessions, arranging care for a child, a note, a
goodbye, a prior attempt.

So the prompt was rewritten from the clinical taxonomy, and validated on a
second held-out split written for the purpose, because a prompt written by
somebody who has seen a split's failures cannot be judged on that split.

| On 500 fresh items | Prompt V1 | Prompt V2 |
|---|---|---|
| Self-harm | 0.481 | **0.685** |
| Detention | **0.963** | 0.778 |
| Overall | 0.844 | 0.841 |

**It improved the category it was aimed at by a fifth and broke a different one
by a fifth.** The overall number did not move. That is the honest result of the
fix, and the reason it is in the README rather than buried: a rewrite that
trades one category for another looks like progress in every summary that only
reports an average. What it actually calls for is in
[ADR-0008](docs/adr/ADR-0008-crisis-recall-needs-a-model.md).

**What exists.** The plan engine, a twenty-task Irish corpus across eight
verified sources, BM25 retrieval, the three-layer safety classifier, the crisis
screen and its directory, the compiled LangGraph with a durable SQLite
checkpointer, the human handoff, composition with a readability target, a CLI
and a FastAPI surface with a caseworker queue.

**What no model touches.** The ordering, every safety layer below the model
screen, and the crisis response. The ordering is derived from structure, so it
is the same every time and it can be asserted exactly. Four import-linter
contracts prove the purity rather than asserting it.

**What is unfinished** is listed at the end of [`HANDOFF.md`](HANDOFF.md). The
short version: the crisis eval corpus is 12 held-out items where certifying the
gate needs 299, and the Habitual Residence Condition itself is still not in the
corpus because the source pages return 403.

---

## The two things worth building

**The plan is a graph, not a list.** Ask a general model what to do after arriving
and you get a competent bulleted list that is close to useless, because it does
not tell you which items you cannot start yet and what specifically unblocks
them. Wayfinder models prerequisites as a DAG, computes the ordering rather than
generating it, and returns the **minimal unblocking set** for anything blocked.
See [`06-plan-graph-design.md`](docs/06-plan-graph-design.md).

**It refuses to make determinations, structurally.** A model asked "do I qualify
for X?" will produce a confident paragraph whether or not it knows. Here that is
somebody planning around money that is not coming. So eligibility determination
is out of scope by construction: there is no edge in the graph from a
determination question to a generated answer, and a test walks the compiled graph
to prove it. See [`07-safety-and-escalation.md`](docs/07-safety-and-escalation.md)
and [ADR-0004](docs/adr/ADR-0004-no-determinations.md).

The boundary in one line: **describing a rule is procedural, applying a rule to
this person is a determination.**

| Answerable | Not answerable |
|---|---|
| "What are the conditions for the habitual residence condition?" | "Do I satisfy the habitual residence condition?" |
| "What documents does a medical card need?" | "Are my documents enough?" |
| "How long does a PPSN usually take?" | "How long will mine take?" |

---

## Why LangGraph specifically

The human handoff is not a confirmation dialog. A caseworker may answer on
Thursday a question asked on Monday. `interrupt()` plus a durable checkpointer
means the graph pauses, the process can restart, and `Command(resume=...)` picks
up exactly where it stopped with the caseworker's determination injected into
state.

There is a test that kills the process mid-pause and resumes it. That is the
feature that earns the framework its place.

Supervisor pattern rather than swarm, and for a safety reason rather than
simplicity: the reachable path set has to be enumerable for the "no path to a
determination answer" claim to be checkable. See
[ADR-0002](docs/adr/ADR-0002-supervisor-not-swarm.md).

---

## What it will not do

- No eligibility determinations
- No legal advice
- No predictions about whether an application will succeed
- No actions taken on anyone's behalf
- No generated content in a crisis response, which comes from a static dated directory

Each is enforced structurally and each has a test. See
[`10-risk-and-ethics.md`](docs/10-risk-and-ethics.md).

---

## Documentation

| | |
|---|---|
| [00 Index](docs/00-INDEX.md) | Reading orders, claims, ADR list |
| [01 Research and analysis](docs/01-research-and-analysis.md) | LangGraph state of the art, the domain, what already exists |
| [02 PDD](docs/02-PDD.md) | Problem, goals, non-goals, users, scope, risks |
| [03 Requirements](docs/03-requirements.md) | Functional and non-functional, acceptance criteria |
| [04 HLD](docs/04-HLD.md) | The graph, and why it is shaped that way |
| [05 LLD](docs/05-LLD.md) | Modules, state, node contracts, corpus format, API |
| [06 Plan graph design](docs/06-plan-graph-design.md) | Core contribution one |
| [07 Safety and escalation](docs/07-safety-and-escalation.md) | Core contribution two |
| [08 Roadmap](docs/08-roadmap.md) | Milestones and estimates |
| [09 Test and eval plan](docs/09-test-and-eval-plan.md) | Corpus, gates, topology tests |
| [10 Risk and ethics](docs/10-risk-and-ethics.md) | Who can be harmed, and what stops it |
| [11 Interview pitch](docs/11-interview-pitch.md) | Pitch, demo, likely questions |
| [12 Changes from the design](docs/12-changes-from-design.md) | The nineteen things building it proved wrong |
| [ADRs](docs/adr/) | Eight decision records |

---

## Scope note

Jurisdiction for v1 is Ireland, deliberately. One jurisdiction with a real,
dated, hand-curated corpus is worth more than five with shallow coverage, and in
this domain shallow coverage is not merely less useful, it is harmful.

This is a portfolio project built to learn LangGraph and multi-agent
orchestration properly. It is not a deployed service, and
[`10-risk-and-ethics.md`](docs/10-risk-and-ethics.md) §5 is explicit about the gap
between the two.
