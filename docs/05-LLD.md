# 05. Low-Level Design

**Project:** Wayfinder · **Version:** 1.0 · **Date:** 17 August 2026

---

## 1. Repository layout

```
wayfinder/
├─ src/wayfinder/
│  ├─ safety/                  # ── runs BEFORE the graph. No LLM in here.
│  │  ├─ crisis.py             #    deterministic lexicon match
│  │  ├─ crisis_lexicon.yaml   #    data, reviewed on a schedule
│  │  ├─ directory.yaml        #    crisis services. Dated. Never generated
│  │  ├─ markers.py            #    deterministic determination markers
│  │  └─ classify.py           #    layered classifier, LLM only as layer 3
│  ├─ plan/                    # ── pure. No I/O, no LLM. BUILT in M1.
│  │  ├─ truth.py              #    Kleene three-valued logic
│  │  ├─ refs.py               #    TaskId, ArtefactRef, kind from the prefix
│  │  ├─ situation.py          #    Situation, Household, DeterminationRecord
│  │  ├─ conditions.py         #    applies_when, evaluated three-valued
│  │  ├─ models.py             #    Task, Prerequisite, Domain, Severity
│  │  ├─ plan.py               #    Plan, PlanItem, the four partitions
│  │  ├─ builder.py            #    select, close, resolve, validate, sort
│  │  ├─ unblock.py            #    unblocking routes and next actions
│  │  ├─ critical_path.py      #    gated calendar time
│  │  ├─ diff.py               #    replanning diffs
│  │  └─ errors.py
│  ├─ corpus/                  # ── BUILT in M1, content seeded only
│  │  ├─ data/tasks/*.yaml     #    the task graph, hand-curated
│  │  ├─ data/sources/*.yaml   #    dated citations
│  │  ├─ data/artefacts/*.yaml #    the declared artefact vocabulary
│  │  ├─ models.py             #    Source, Artefact, Corpus, staleness bands
│  │  └─ loader.py             #    validates integrity at load
│  ├─ retrieval/
│  │  ├─ index.py              #    hybrid BM25 + embeddings
│  │  └─ staleness.py
│  ├─ graph/                   # ── LangGraph assembly
│  │  ├─ state.py              #    WayfinderState
│  │  ├─ nodes/                #    intake, planner, supervisor, domains,
│  │  │                        #    compose, verify, handoff, plain
│  │  ├─ build.py              #    graph construction and edges
│  │  └─ checkpoint.py
│  ├─ compose/
│  │  ├─ generate.py           #    citation-bound generation
│  │  ├─ verify.py             #    entailment check, drops failures
│  │  └─ plain.py              #    reading-level pass
│  ├─ eval/                    #    the safety gate
│  ├─ api/                     #    FastAPI, caseworker queue, plan view
│  └─ cli/
├─ tests/
│  ├─ corpus/                  #    labelled safety eval splits
│  ├─ fixtures/corpus/         #    synthetic corpus. personas assert against
│  │                           #    this, so M2 content work cannot break M1
│  ├─ personas/                #    reference plans, asserted exactly
│  └─ unit/ integration/
└─ docs/
```

`plan/` and `safety/markers.py` are pure and have no LLM or I/O dependency. That
is enforced by an import-linter contract, because the claim decays otherwise.
The contract is live as of M1 and forbids `plan/` from importing any framework,
any HTTP client, `yaml`, `sqlite3`, `os`, `io`, `pathlib` or `subprocess`.

**Two corpora, deliberately.** Reference personas assert exact plans against the
synthetic corpus in `tests/fixtures/`, not against `corpus/data/`. Curating real
content in M2 therefore cannot break M1's tests, and an engine regression cannot
be masked by a content change. See `12` for the reasoning.

---

## 2. Graph state

```python
class WayfinderState(BaseModel):
    """Everything the graph carries. Personal data lives here and only here."""

    # conversation
    messages: Annotated[list[AnyMessage], add_messages]
    current_question: str = ""
    question_class: QuestionClass | None = None

    # situation, built incrementally by intake
    situation: Situation = Field(default_factory=Situation)
    situation_complete: bool = False

    # planning
    plan: Plan | None = None
    previous_plan: Plan | None = None  # for replanning diffs

    # retrieval
    active_domain: Domain | None = None
    retrieved: list[RetrievedSpan] = Field(default_factory=list)
    staleness: StalenessVerdict | None = None

    # human in the loop
    handoff_reason: str | None = None
    human_determination: HumanDetermination | None = None

    # audit. every turn must be reconstructable
    trace: list[TraceEvent] = Field(default_factory=list)
```

Three notes.

`messages` uses `add_messages` so history accumulates; everything else is
replaced per turn, which keeps stale retrieval from leaking into a later answer.

`human_determination` is a distinct type rather than a string, so composition can
attribute it and never restate it as system knowledge.

`trace` is not debugging. It is the record of why a turn was classified and
answered the way it was, needed for eval and for anyone reviewing a bad answer.

---

## 3. Node contracts

| Node | In | Out | Can it call an LLM? |
|---|---|---|---|
| `crisis_screen` | raw turn | hit or clear | **No. Ever** |
| `classify` | turn, situation | `question_class` | Layer 3 only |
| `intake` | situation | updated situation, or a question | Yes |
| `planner` | situation, corpus | `Plan` | **No** |
| `supervisor` | question | `Command(goto=domain)` | Yes |
| `domain_*` | question, domain corpus | `retrieved` | Yes, ReAct |
| `staleness` | retrieved | verdict | **No** |
| `compose` | retrieved, determination | `Answer` | Yes, constrained |
| `verify` | answer, spans | answer with failures removed | Yes, entailment |
| `plain` | answer | rewritten answer | Yes |
| `handoff` | question, situation | `interrupt()` | **No** |

The "no LLM" nodes are the ones whose behaviour must be identical every time.

### 3.1 Edges that deliberately do not exist

```python
# In build.py, stated as an assertion rather than a comment, and tested.
FORBIDDEN_EDGES = [
    ("classify", "compose"),  # a determination must pass through handoff
    ("classify", "supervisor"),  # ... for DETERMINATION specifically
    ("crisis_screen", "compose"),  # crisis output is never generated
]
```

A test walks the compiled graph and asserts no path exists from a
`DETERMINATION` classification to `compose` that does not include `handoff`.
That test is the safety claim, expressed as code.

---

## 4. Supervisor routing

```python
def supervisor(state: WayfinderState) -> Command[Literal[*DOMAINS, "compose"]]:
    """Route to the domain that owns this question.

    Supervisor rather than swarm, because the set of reachable paths has to be
    enumerable. See HLD section 4.
    """
    if state.question_class is QuestionClass.PLANNING:
        return Command(goto="planner")
    domain = _route(state.current_question, state.situation)
    if domain is None:
        return Command(goto="compose", update={"retrieved": []})  # no source, say so
    return Command(goto=f"domain_{domain}", update={"active_domain": domain})
```

Returning `compose` with empty `retrieved` is a supported outcome, not a failure.
It produces "I do not have a reliable source for that, here is who to ask", which
is a correct answer.

---

## 5. Domain subgraphs

Each domain is a small ReAct loop over its own corpus slice, with a bounded step
count. They do not route to each other; cross-domain questions are decomposed by
the planner instead, which keeps the path set small.

```python
def build_domain(domain: Domain) -> CompiledGraph:
    g = StateGraph(DomainState)
    g.add_node("think", make_thinker(domain))
    g.add_node("search", make_searcher(domain))
    g.add_conditional_edges("think", should_search, {"search": "search", "done": END})
    g.add_edge("search", "think")
    g.set_entry_point("think")
    return g.compile()  # step cap enforced via recursion_limit
```

---

## 6. Persistence and threads

| Concern | Choice |
|---|---|
| Checkpointer | `SqliteSaver` for dev, `PostgresSaver` for deploy |
| Thread id | One per person per session |
| Retention | State purged on completion. Escalations retain only what the caseworker needs |
| Resume | `Command(resume=HumanDetermination(...))` |
| Restart safety | Tested by killing the process mid-interrupt and resuming |

---

## 7. Corpus format

**Revised in M1, see `12` §6.**

```yaml
# corpus/data/tasks/ireland.yaml
- id: ppsn.apply
  title: Apply for your PPS number
  domain: status
  why: You can ask for this at the same time as your protection application.
  requires:
    # A bare reference is a hard requirement.
    - document:asylum_application_letter
    # A list is an alternative: any one of these satisfies it.
    - any_of: [document:proof_of_address, document:shelter_letter]
      note: Either is usually accepted.
  produces: [document:ppsn]
  applies_when:
    not:
      holds: document:ppsn
  typical_wait: P4D
  blocking_severity: critical
  where:
    - source_id: irc.ppsn
      span: Application Process
```

The kind of a reference is carried by its prefix and validated at load. There is
no separate `kind:` field, because two places to state one fact is one place to
get it wrong.

```yaml
# corpus/data/artefacts/ireland.yaml
- ref: document:ppsn
  title: your PPS number

- ref: determination:ipas_accommodation_offer
  title: an offer of accommodation from IPAS
  decided_by: the International Protection Accommodation Service
```

Artefacts are **declared**, not inferred from use. The most likely corpus bug is
a typo in a reference, `document:pps_number` against `document:ppsn`, which
without a declared vocabulary produces a task that silently never links to
anything. Declaring them makes that a load failure.

A `determination:` artefact must name `decided_by`, and nothing else may. The
output people need is "this is decided by *that* authority, here is how it is
applied for", and that sentence is only writable if the corpus carries the name.

```yaml
# corpus/data/sources/ireland.yaml
- id: irc.ppsn
  title: PPSN information for international protection applicants
  publisher: Irish Refugee Council
  url: https://www.irishrefugeecouncil.ie/...
  last_verified: 2026-08-18
  verified_by: NA
  language: en
```

`last_verified` is mandatory and validated at load. A source without one fails
the build, because an undated source is indistinguishable from a stale one. A
`last_verified` in the future also fails, because it is always a typo.

Integrity problems are collected and reported together rather than one at a
time, since somebody editing YAML wants the whole list.

## 8. API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/threads` | Start a session |
| `POST` | `/v1/threads/{id}/turn` | Send a turn |
| `GET` | `/v1/threads/{id}/plan` | Current plan: frontier, blocked, unblocking sets |
| `DELETE` | `/v1/threads/{id}` | Forget the thread. NG5 |
| `GET` | `/v1/queue` | Caseworker queue of pending determinations |
| `POST` | `/v1/queue/{id}/respond` | Resume the graph with a determination |
| `GET` | `/v1/corpus/health` | Staleness. **503** once a source has aged out |

`/v1/corpus/health` is not an afterthought. Source staleness is the most likely
silent failure in this system, and an endpoint that returns 200 with a list of
rotting sources nobody reads is not an alarm. It returns 503.

**Built, with three corrections to this table.**

Turns are not streamed. A turn either completes or pauses at the handoff, and a
paused turn has nothing to stream. Streaming would only make the wait feel
shorter, which is not what is scarce here.

`DELETE /v1/threads/{id}` was missing from the design and is required by NG5.
Personal data that is not retained cannot leak, and an endpoint that does the
retaining without one that undoes it is a one-way door.

The queue and the situation lookup both read through to the checkpointer rather
than to process memory. The first version did not, which meant the queue came
back empty after a redeploy while the graph was still paused on disk. See change
17 in `12-changes-from-design.md`.

Both `/v1/queue` endpoints return 503 when no checkpointer is configured. An
empty list would read as "nothing is waiting" rather than "this is not set up",
and the difference matters to whoever is on call.

---

## 9. Testing

| Layer | Approach |
|---|---|
| `plan/` | Pure. Property tests for acyclicity, exact assertions against reference personas |
| `safety/` | Labelled corpus, CI gate, minimal-pair boundary split |
| Graph topology | Assert the forbidden paths do not exist in the compiled graph |
| Interrupt and resume | Kill the process mid-pause, resume, assert state identity by hash |
| Composition | No uncited claim can be constructed. Verified by type, then by test |
| Staleness | Table-driven across the age bands |
| End to end | Scripted persona journeys, including one that hits crisis and one that hits handoff |
