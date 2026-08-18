# Wayfinder

A LangGraph agent team that turns "I have just arrived, what do I do?" into an
ordered plan with prerequisites, and refuses to answer the questions that need a
human.

**Status: M1 built.** The plan graph engine runs, with no model involved. M2 to
M6 are not started. Start with [`HANDOFF.md`](HANDOFF.md), and see
[`docs/12-changes-from-design.md`](docs/12-changes-from-design.md) for what
building M1 proved wrong about the design.

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
uv sync --all-groups
uv run wayfinder --today 2026-08-18 plan examples/amara-week-one.yaml
```

The date is an input rather than a clock read, so the same situation always
produces the same plan. That is also why the engine is testable.

```bash
uv run wayfinder corpus check     # integrity: dates, references, citations
uv run wayfinder corpus health    # staleness bands, the maintenance alarm
uv run pytest                     # unit, property and persona tests
uv run lint-imports               # proves plan/ imports nothing with I/O
```

**What exists so far.** The plan engine, the corpus loader, a ten-task seed
corpus for Ireland and a CLI. No model is involved anywhere, which is the part
worth defending: the ordering is derived from structure, so it is the same every
time and it can be asserted exactly.

**What does not exist yet.** The safety classifier, the crisis path, the
LangGraph assembly, the human handoff, retrieval and composition. M2 to M6.

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
| [12 Changes from the design](docs/12-changes-from-design.md) | What M1 proved wrong |
| [ADRs](docs/adr/) | Seven decision records |

---

## Scope note

Jurisdiction for v1 is Ireland, deliberately. One jurisdiction with a real,
dated, hand-curated corpus is worth more than five with shallow coverage, and in
this domain shallow coverage is not merely less useful, it is harmful.

This is a portfolio project built to learn LangGraph and multi-agent
orchestration properly. It is not a deployed service, and
[`10-risk-and-ethics.md`](docs/10-risk-and-ethics.md) §5 is explicit about the gap
between the two.
