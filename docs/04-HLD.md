# 04. High-Level Design

**Project:** Wayfinder · **Version:** 1.0 · **Date:** 17 August 2026

---

## 1. What shapes this architecture

| # | Driver | Consequence |
|---|---|---|
| D1 | Some questions must never be answered by the system | Classification happens **before** routing, and the refusal path cannot be reached by the answering path |
| D2 | Crisis situations must bypass everything | A pre-graph deterministic check, not a node the supervisor might route around |
| D3 | Tasks have prerequisites | The planner emits a **DAG**, and ordering is computed rather than generated |
| D4 | A human handoff may take days | `interrupt()` plus a durable checkpointer, not a blocking call |
| D5 | Every claim needs a dated source | Generation is constrained to retrieved spans, and verified afterwards |

**The single most important structural decision:** the safety classifier sits
*outside and above* the agent graph. An LLM supervisor deciding whether to
escalate is a supervisor that can be talked out of escalating. The crisis check
and the determination check run first, deterministically, and the graph is only
entered if they pass.

---

## 2. System context

```mermaid
graph TB
    U["👤 Newly arrived person"]
    C["👤 Caseworker (NGO)"]

    W["<b>Wayfinder</b><br/>Plan, retrieve, refuse, escalate<br/><i>LangGraph agent team</i>"]

    CORPUS[("📚 Curated source corpus<br/>Citizens Information, IPO, IPAS,<br/>Irish Refugee Council, NASC, HSE<br/><i>dated, human-verified</i>")]
    LLM["🧠 LLM provider"]
    CRISIS["☎️ Crisis services directory<br/><i>static, never generated</i>"]

    U -->|"situation, questions"| W
    W -->|"ordered plan, cited answers,<br/>or an explicit refusal"| U
    W -->|"escalations with context"| C
    C -->|"determination, resumes the graph"| W
    W --> CORPUS
    W --> LLM
    W -->|"on crisis, immediately"| CRISIS

    classDef sys fill:#2a6f5f,stroke:#17453a,color:#fff
    classDef ext fill:#eef1f0,stroke:#b9c6c1,color:#12211d
    classDef person fill:#b4622a,stroke:#7d4119,color:#fff
    class W sys
    class CORPUS,LLM,CRISIS ext
    class U,C person
```

Note the arrow that does not exist: Wayfinder never contacts an agency on
someone's behalf. Actions with consequences stay with the person and their
caseworker (PDD NG4).

---

## 3. The graph

```mermaid
graph TD
    START([user turn]) --> GUARD

    subgraph PRE["Pre-graph guard. Deterministic, no LLM"]
        GUARD["<b>crisis screen</b><br/>pattern match on the raw turn"]
    end

    GUARD -->|"crisis detected"| CRISISOUT["<b>crisis response</b><br/>static directory, no generation<br/><i>terminal</i>"]
    GUARD -->|"clear"| CLASSIFY

    CLASSIFY["<b>classify</b><br/>PROCEDURAL / DETERMINATION /<br/>PLANNING / OUT_OF_SCOPE"]

    CLASSIFY -->|DETERMINATION| HANDOFF
    CLASSIFY -->|OUT_OF_SCOPE| DECLINE["<b>decline</b><br/>name who can help<br/><i>terminal</i>"]
    CLASSIFY -->|PLANNING| INTAKE
    CLASSIFY -->|PROCEDURAL| SUPERVISOR

    INTAKE["<b>intake</b><br/>structured situation interview<br/>asks only what changes the plan"]
    INTAKE --> PLANNER

    PLANNER["<b>plan builder</b><br/>select tasks, resolve prerequisites,<br/>topological sort, find blocked"]
    PLANNER --> SUPERVISOR

    SUPERVISOR{"<b>supervisor</b><br/>which domain owns this?"}

    SUPERVISOR --> D1["status &<br/>documentation"]
    SUPERVISOR --> D2["accommodation"]
    SUPERVISOR --> D3["income<br/>support"]
    SUPERVISOR --> D4["healthcare"]
    SUPERVISOR --> D5["education"]
    SUPERVISOR --> D6["banking"]

    D1 --> RETRIEVE
    D2 --> RETRIEVE
    D3 --> RETRIEVE
    D4 --> RETRIEVE
    D5 --> RETRIEVE
    D6 --> RETRIEVE

    RETRIEVE["<b>retrieve</b><br/>ReAct over the domain corpus"]
    RETRIEVE --> STALE{"any source<br/>stale?"}
    STALE -->|yes| DOWNGRADE["mark answer<br/>as needs-verifying"]
    STALE -->|no| COMPOSE
    DOWNGRADE --> COMPOSE

    COMPOSE["<b>compose</b><br/>citation-bound generation"]
    COMPOSE --> VERIFY{"every claim<br/>entailed by a<br/>cited span?"}
    VERIFY -->|no| STRIP["drop unsupported claims<br/><i>drop, never hedge</i>"]
    VERIFY -->|yes| PLAIN
    STRIP --> PLAIN

    PLAIN["<b>plain language pass</b>"] --> OUT([answer with citations])

    HANDOFF["<b>human handoff</b><br/>interrupt()<br/>graph pauses, checkpointed"]
    HANDOFF -.->|"caseworker responds,<br/>possibly days later"| RESUME["resume with<br/>determination in state"]
    RESUME --> COMPOSE

    classDef guard fill:#a8322b,stroke:#6d1f1a,color:#fff
    classDef safe fill:#b4622a,stroke:#7d4119,color:#fff
    classDef core fill:#2a6f5f,stroke:#17453a,color:#fff
    classDef term fill:#4a4a52,stroke:#2b2b30,color:#fff
    class GUARD,CLASSIFY guard
    class HANDOFF,DECLINE,CRISISOUT,STRIP,DOWNGRADE safe
    class INTAKE,PLANNER,SUPERVISOR,RETRIEVE,COMPOSE,PLAIN,D1,D2,D3,D4,D5,D6 core
    class OUT,RESUME term
```

### 3.1 Reading the graph

Three things are worth noticing.

**The guard is outside the graph.** `crisis screen` runs on the raw turn before
LangGraph is entered. It is deterministic pattern matching. If it fires, the
response comes from a static directory with no generation at all, because a
model improvising during someone's emergency is unacceptable and a model is not
needed to read out a phone number.

**`DETERMINATION` cannot reach `compose` without passing through `handoff`.**
There is no edge. The only route from a determination question to an answer runs
through a human, and that is a property of the graph rather than of a prompt.

**`compose` is the only node that generates prose**, and its output is verified
before it leaves. Unsupported claims are dropped rather than softened, because
"you may possibly be entitled to" is still an entitlement claim.

---

## 4. Why supervisor rather than swarm

Current guidance is to start with a supervisor: one routing node, clear control
flow, every decision visible in a trace. Swarms need budget limits, handoff
schemas, loop detection and tool isolation before they are safe to run.

For this domain the argument is stronger than "start simple". **In a swarm, any
agent can hand off to any other, which means the set of reachable paths is large
and hard to enumerate.** Here we need to be able to say with certainty that no
path exists from a determination question to a generated answer. A supervisor
with explicit edges makes that checkable. A swarm makes it an argument.

Domain agents are subgraphs rather than separate agents in a mesh: they retrieve
within their domain and return, and they never route to each other.

---

## 5. Components

| Component | Owns | Explicitly not its job |
|---|---|---|
| **Crisis screen** | Detecting emergencies in the raw turn | Anything else. It has one job and must be fast and dumb |
| **Classifier** | Deciding what kind of question this is | Answering it |
| **Intake** | Building a structured situation | Guessing missing facts. It asks |
| **Plan builder** | Task selection, prerequisites, ordering, blocked detection | Generating prose about tasks |
| **Supervisor** | Routing to a domain | Retrieval or generation |
| **Domain subgraphs** | ReAct retrieval within one domain | Cross-domain reasoning |
| **Composer** | Turning retrieved spans into an answer | Introducing facts not in the spans |
| **Verifier** | Checking every claim against its span | Fixing bad claims. It removes them |
| **Handoff** | Pausing, packaging context, resuming | Deciding the determination |
| **Corpus** | Dated, curated sources | Being complete. It is explicitly partial and says so |

---

## 6. State and persistence

LangGraph's checkpointer is what makes the human handoff real rather than
decorative. When `interrupt()` fires, the executor serialises the full state
snapshot under the thread id and unwinds cleanly. The process can restart. The
caseworker can respond on Thursday. `Command(resume=...)` picks up exactly where
it stopped.

```mermaid
sequenceDiagram
    autonumber
    participant A as Amara
    participant G as Graph
    participant CP as Checkpointer
    participant C as Caseworker

    A->>G: "am I entitled to the daily expenses allowance?"
    G->>G: crisis screen, clear
    G->>G: classify -> DETERMINATION
    Note over G: no edge to compose exists
    G->>G: handoff node calls interrupt()
    G->>CP: full state snapshot, thread_id
    G-->>A: "That is a determination only the Department can make.<br/>I have sent it to Clare with your situation attached.<br/>Meanwhile here is the process and what to bring."
    Note over G,CP: graph is paused. Process can restart.
    C->>G: Command(resume={determination, note, source})
    G->>CP: load snapshot
    G->>G: compose, with the human answer as the authority
    G-->>A: answer, attributed to Clare, not to the system
```

The final message attributes the determination to the named human. The system
does not launder a human judgement into its own voice.

---

## 7. Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph 1.x** | The gap this project exists to close. `interrupt()`, checkpointers and durable execution are exactly what the handoff needs |
| Checkpointer | `langgraph-checkpoint-sqlite` dev, `-postgres` deploy | Durable pause is the point |
| Language | Python 3.12 | |
| Models | Small fast model for classification, stronger model for supervisor routing and composition | Routing needs reasoning; classification needs consistency and low latency |
| Retrieval | Hybrid BM25 + embeddings over a curated corpus | The corpus is small and high-value, so precision beats recall |
| Validation | Pydantic v2 | State schemas, task model, citations |
| API/UI | FastAPI plus server-rendered pages | Same reasoning as any small tool: no build step, fewer places for escaping bugs |
| Quality | ruff, mypy --strict, pytest, plus a **safety eval gate in CI** | The classifier is a model and gets treated like one |

---

## 8. Cross-cutting

| Concern | Approach |
|---|---|
| **Personal data** | Not persisted by default. Situation lives in graph state for the thread and is purged on completion. Escalations carry the minimum a caseworker needs |
| **Citations** | A first-class type, not a string. `Citation(source_id, title, url, span, last_verified)` |
| **Staleness** | Every source dated. Past threshold, the answer is downgraded and says so |
| **Refusals** | Always name an alternative. A refusal that leaves someone stuck is a failure, not a safety win |
| **Tracing** | Every turn traceable: classification, route, sources, verification result. Needed for eval and for anyone reviewing a bad answer |
| **Reading level** | Measured, targeted, tested. Guidance nobody can read is not guidance |
| **Tone** | The output is read by someone under stress. No cheerfulness, no exclamation marks, no false reassurance |

---

## 9. What this design refuses to do

- No path from a determination question to a generated answer.
- No LLM in the crisis path.
- No generated content in a crisis response.
- No claim without a dated citation.
- No hedged version of a claim that failed verification. It is removed.
- No action taken on anyone's behalf.
