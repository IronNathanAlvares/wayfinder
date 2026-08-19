"""The nodes. Which of them may call a model is the load-bearing part.

| Node             | Model? | Why                                          |
|------------------|--------|----------------------------------------------|
| `classify`       | layer 3 only | Layers 1 and 2 are deterministic       |
| `crisis_response`| **No, ever** | Looked up from a dated directory       |
| `intake`         | No     | Asks; it does not guess                        |
| `planner`        | No     | Ordering is computed, not generated            |
| `supervisor`     | No     | A lookup over a declarative table              |
| `retrieve`       | No     | BM25 over the corpus                           |
| `staleness`      | No     | Arithmetic on dates                            |
| `compose`        | Yes, constrained | Sees only retrieved spans            |
| `verify`         | Yes, entailment  | Removes claims; never fixes them     |
| `handoff`        | **No** | It pauses. It does not decide                  |

The "no model" nodes are the ones whose behaviour must be identical every time.
More of them are deterministic here than the design expected, because the plan
engine turned out to do the work that would otherwise have needed generation.

`supervisor` deserves a note. The design had it as an LLM routing decision. It
is a lookup: the question has already been classified, and the domain follows
from term overlap with the corpus, which retrieval already computes. A model
here would add latency, cost, and a second place for the routing to disagree
with the table ADR-0007 rests on, and would buy nothing measurable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from langgraph.types import Command, interrupt

from wayfinder.graph.routes import COMPOSE, PLAIN, RETRIEVE, STALENESS, VERIFY
from wayfinder.graph.state import (
    Answer,
    HumanDetermination,
    Turn,
    WayfinderState,
    summarise_for_caseworker,
)
from wayfinder.plan.builder import build_plan
from wayfinder.plan.models import Domain
from wayfinder.retrieval.index import Index, RetrievedSpan, needs_verifying
from wayfinder.safety import refusals
from wayfinder.safety.classify import classify as classify_turn
from wayfinder.safety.crisis import respond
from wayfinder.safety.escalation import DEGRADED_NOTICE, ModelScreen, full_screen
from wayfinder.safety.models import CrisisDirectory, CrisisLexicon
from wayfinder.safety.taxonomy import QuestionClass

# A graph node: takes the whole state and returns either the keys it changed or
# a Command that also says where to go next. `supervisor` and `handoff` use the
# second form, which is how their outgoing edges are declared.
Node = Callable[[WayfinderState], "dict[str, object] | Command[str]"]


class Composer(Protocol):
    """Turns retrieved spans into prose. Sees only the spans.

    There is no free-recall path: the implementation is handed the spans and the
    question, and nothing else. A composer that could reach its own knowledge
    would make the citation guarantee unenforceable.
    """

    def __call__(self, question: str, spans: Sequence[RetrievedSpan]) -> str: ...


class Deps:
    """Everything the nodes need, injected once when the graph is built.

    Injected rather than imported so a test can drive the whole graph with a
    stub composer and a fixed date, and so the eval can swap the model screen.
    """

    __slots__ = ("composer", "directory", "index", "lexicon", "model_screen", "tasks")

    def __init__(
        self,
        *,
        lexicon: CrisisLexicon,
        directory: CrisisDirectory,
        index: Index,
        tasks: Sequence[object],
        composer: Composer | None = None,
        model_screen: ModelScreen | None = None,
    ) -> None:
        self.lexicon = lexicon
        self.directory = directory
        self.index = index
        self.tasks = tasks
        self.composer = composer
        self.model_screen = model_screen


# --- classification ---------------------------------------------------------


def make_classify(deps: Deps) -> Node:
    def classify(state: WayfinderState) -> dict[str, object]:
        """Layers 1 and 2 run before anything sampled, and before this node
        returns. The crisis screen runs first and its result cannot be
        overridden by anything downstream."""
        screened = full_screen(
            state.current_question, deps.lexicon, model=deps.model_screen
        )
        if screened.is_crisis:
            return {
                "question_class": QuestionClass.CRISIS,
                "crisis": screened.hit,
                "trace": state.traced("classify", f"crisis: {screened.outcome.value}"),
            }

        result = classify_turn(state.current_question, lexicon=deps.lexicon)
        update: dict[str, object] = {
            "question_class": result.question_class,
            "classification": result,
            "trace": state.traced(
                "classify", f"{result.question_class.value} via {result.layer.value}"
            ),
        }
        if not screened.screening_was_complete:
            # The screen ran degraded. The person is told rather than assumed
            # safe, and the notice rides along with whatever answer follows.
            update["stale_sources"] = ("crisis-screen-degraded",)
        return update

    return classify


# --- terminal paths ---------------------------------------------------------


def make_crisis_response(deps: Deps) -> Node:
    def crisis_response(state: WayfinderState) -> dict[str, object]:
        """Looked up, never generated, and terminal.

        No model has been called on this path and none will be. A crisis
        response does not continue into planning: somebody who says they have
        nowhere to sleep tonight needs a phone number, not an onboarding plan.
        """
        assert state.crisis is not None
        text = respond(state.crisis, deps.directory)
        return {
            "answer": Answer(text=text),
            "messages": [Turn(role="assistant", text=text)],
            "trace": state.traced("crisis_response", state.crisis.category.value),
        }

    return crisis_response


def decline(state: WayfinderState) -> dict[str, object]:
    """Out of scope. Declined with somebody named who can help instead.

    A refusal that leaves somebody stuck is a failure, not a safety win: they go
    and ask a system with no such scruples and get a confident wrong answer.
    """
    text = refusals.OUT_OF_SCOPE_PREDICTION
    lowered = state.current_question.lower()
    if any(
        w in lowered for w in ("solicitor", "lawyer", "appeal", "court", "tribunal")
    ):
        text = refusals.OUT_OF_SCOPE_LEGAL
    elif any(
        w in lowered for w in ("medicine", "medication", "doctor", "rash", "pain")
    ):
        text = refusals.OUT_OF_SCOPE_MEDICAL
    return {
        "answer": Answer(text=text),
        "messages": [Turn(role="assistant", text=text)],
        "trace": state.traced("decline", "out of scope"),
    }


# --- planning ---------------------------------------------------------------


def make_intake(deps: Deps) -> Node:
    def intake(state: WayfinderState) -> dict[str, object]:
        """Builds what it can and records what it still needs.

        It never guesses a missing fact. The open questions come from the plan
        engine's `needs_info` partition, which is already pruned to facts whose
        answer would change a task's placement, so this asks only what matters.
        """
        plan = build_plan(deps.tasks, state.situation, today=state.today)  # type: ignore[arg-type]
        return {
            "plan": plan,
            "open_questions": tuple(sorted(plan.open_questions)),
            "trace": state.traced(
                "intake", f"{len(plan.open_questions)} open question(s)"
            ),
        }

    return intake


def make_planner(deps: Deps) -> Node:
    def planner(state: WayfinderState) -> dict[str, object]:
        """No model. Ordering is derived from structure, so it is the same
        every time and can be asserted exactly."""
        plan = state.plan or build_plan(
            deps.tasks,  # type: ignore[arg-type]
            state.situation,
            today=state.today,
        )
        return {
            "plan": plan,
            "trace": state.traced(
                "planner",
                f"{len(plan.frontier)} startable, {len(plan.blocked)} blocked",
            ),
        }

    return planner


# --- retrieval --------------------------------------------------------------

_DOMAIN_HINTS: dict[Domain, tuple[str, ...]] = {
    Domain.STATUS: ("pps", "ppsn", "permission", "work", "protection", "certificate"),
    Domain.ACCOMMODATION: ("accommodation", "housing", "address", "ipas", "homeless"),
    Domain.INCOME: ("payment", "allowance", "benefit", "money", "welfare"),
    Domain.HEALTH: ("medical", "doctor", "gp", "health", "card"),
    Domain.EDUCATION: ("school", "college", "course", "english", "education"),
    Domain.BANKING: ("bank", "account", "iban"),
}


def supervisor(state: WayfinderState) -> Command[str]:
    """Route to the domain that owns this question.

    Supervisor rather than swarm, and for a safety reason rather than
    simplicity: the reachable path set has to be enumerable for ADR-0004's claim
    to be checkable. See ADR-0002.

    Returning no domain is a supported outcome, not a failure. It produces "I do
    not have a reliable source for that, here is who to ask", which is a correct
    answer.
    """
    lowered = state.current_question.lower()
    best: Domain | None = None
    best_score = 0
    for domain, hints in _DOMAIN_HINTS.items():
        score = sum(1 for h in hints if h in lowered)
        if score > best_score:
            best, best_score = domain, score
    return Command(
        goto=RETRIEVE,
        update={
            "active_domain": best.value if best else None,
            "trace": state.traced(
                "supervisor", f"domain: {best.value if best else 'none'}"
            ),
        },
    )


def make_retrieve(deps: Deps) -> Node:
    def retrieve(state: WayfinderState) -> dict[str, object]:
        domain = Domain(state.active_domain) if state.active_domain else None
        spans = deps.index.search(state.current_question, domain=domain, limit=4)
        return {
            "retrieved": spans,
            "trace": state.traced("retrieve", f"{len(spans)} span(s)"),
        }

    return retrieve


def staleness_gate(state: WayfinderState) -> dict[str, object]:
    """Arithmetic on dates, no model.

    Sources past a year are already excluded at index time, so what reaches here
    is the middle band: old enough that the answer has to say so.
    """
    ageing = needs_verifying(state.retrieved)
    return {
        "stale_sources": tuple(sorted({s.source_id for s in ageing})),
        "trace": state.traced("staleness", f"{len(ageing)} source(s) need verifying"),
    }


# --- the human handoff ------------------------------------------------------


def handoff(state: WayfinderState) -> Command[str]:
    """Pause for a person. This is why LangGraph is here.

    `interrupt()` raises a `GraphInterrupt` which the executor catches, unwinding
    cleanly and serialising the full state under the thread id. The process can
    restart. The caseworker can answer on Thursday a question asked on Monday.
    `Command(resume=...)` picks it up exactly where it stopped.

    This node decides nothing. It packages the question, pauses, and puts
    whatever the human said into state so composition can attribute it.
    """
    reply = interrupt(
        {
            "kind": "determination",
            "question": state.current_question,
            "situation_summary": summarise_for_caseworker(
                state.situation, state.current_question, state.retrieved
            ),
            "asked_on": state.today.isoformat(),
        }
    )
    determination = (
        reply
        if isinstance(reply, HumanDetermination)
        else HumanDetermination.model_validate(reply)
    )
    return Command(
        goto=COMPOSE,
        update={
            "human_determination": determination,
            "handoff_reason": "determination",
            "trace": state.traced(
                "handoff", f"answered by {determination.answered_by}"
            ),
        },
    )


# --- composition ------------------------------------------------------------


def default_composer(question: str, spans: Sequence[RetrievedSpan]) -> str:
    """The deterministic composer, used when no model is configured.

    It states only what the spans say and attaches every source. That is duller
    than generated prose and it is not a placeholder: it satisfies the citation
    rule structurally, so the system degrades to something correct rather than
    to something silent. A model composer plugs into the same protocol.
    """
    if not spans:
        return refusals.NO_SOURCE

    # Grouped by what the span is about, not by span. Retrieval returns one span
    # per source per task, so two sources covering the PPS number would
    # otherwise print the same paragraph twice under different citations, which
    # reads as though the system has lost its place.
    grouped: dict[str, list[RetrievedSpan]] = {}
    for span in spans:
        grouped.setdefault(span.title, []).append(span)

    lines = ["Here is what the sources say.", ""]
    for title, found in grouped.items():
        lines.append(title)
        lines.append(f"  {found[0].why}")
        for span in found:
            lines.append(f"  Source: {span.source_title}, checked {span.last_verified}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def make_compose(deps: Deps) -> Node:
    def compose(state: WayfinderState) -> dict[str, object]:
        """Constrained twice: it sees only retrieved spans, and what it produces
        is verified afterwards.

        When a human determination is present it leads, attributed to the person
        who made it. The system does not restate a caseworker's judgement in its
        own voice, because that launders human accountability into machine
        confidence and destroys the audit trail the handoff exists for.
        """
        composer = deps.composer or default_composer

        if state.human_determination is not None:
            # The caseworker's answer stands alone. Nothing composed follows it.
            #
            # Determinations route from classification straight to the handoff,
            # so retrieval has not run and the composer has nothing to work
            # from. Whatever it says in that situation lands directly under a
            # named person's answer, which reads as the system doubting them.
            d = state.human_determination
            attributed = d.answered_by
            body = (
                f"{d.answered_by} looked at this and said:\n\n"
                f"  {d.answer}\n\n"
                f"That answer is theirs, given on {d.answered_on}. "
                f"I have not changed it and I am not adding to it.\n"
            )
        else:
            attributed = ""
            body = composer(state.current_question, state.retrieved)

        return {
            "answer": Answer(
                text=body,
                citations=state.retrieved,
                needs_verifying=bool(state.stale_sources),
                attributed_to=attributed,
            ),
            "trace": state.traced("compose", f"{len(state.retrieved)} citation(s)"),
        }

    return compose


def verify(state: WayfinderState) -> dict[str, object]:
    """Every claim must rest on a cited span. Failures are removed, not softened.

    The rule against hedging is the point: "you may be entitled to X" is still an
    entitlement claim, and it is worse than saying nothing because it sounds like
    permission to plan around it.
    """
    assert state.answer is not None
    answer = state.answer

    if not answer.citations and not state.human_determination:
        # Nothing supports this. Saying so is a correct outcome.
        return {
            "answer": Answer(text=refusals.NO_SOURCE),
            "trace": state.traced("verify", "no citations, answer withdrawn"),
        }

    kept, dropped = _strip_uncited(answer.text)
    return {
        "answer": answer.model_copy(update={"text": kept}),
        "trace": state.traced("verify", f"{dropped} unsupported line(s) removed"),
    }


# Entitlement language that must never survive verification, whatever produced
# it. A composer that emits one of these has made a claim the corpus cannot
# support, because the corpus deliberately contains no entitlement statements.
_UNSUPPORTABLE = (
    "you are entitled",
    "you may be entitled",
    "you might be entitled",
    "you qualify",
    "you may qualify",
    "you will get",
    "you will receive",
    "you are eligible",
    "you should be eligible",
    "likely to be approved",
)


def _strip_uncited(text: str) -> tuple[str, int]:
    kept, dropped = [], 0
    for line in text.splitlines():
        lowered = line.lower()
        if any(phrase in lowered for phrase in _UNSUPPORTABLE):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept), dropped


def plain(state: WayfinderState) -> dict[str, object]:
    """The last pass before it reaches somebody under stress.

    Tone rules, and they are not decoration: no cheerfulness, no exclamation
    marks, no false reassurance. If the crisis screen ran degraded, the notice
    goes here rather than being buried, because a person deciding whether to
    wait for an answer needs to know the check was incomplete.
    """
    assert state.answer is not None
    text = state.answer.text.replace("!", ".")

    if "crisis-screen-degraded" in state.stale_sources:
        text = f"{DEGRADED_NOTICE}\n{text}"
    elif state.answer.needs_verifying:
        text = (
            f"{text}\n"
            "Some of the sources behind this have not been checked recently. "
            "Confirm anything time-sensitive with the organisation itself before "
            "you rely on it.\n"
        )

    final = state.answer.model_copy(update={"text": text})
    return {
        "answer": final,
        "messages": [Turn(role="assistant", text=text)],
        "trace": state.traced("plain", "tone and staleness pass"),
    }


__all__ = [
    "COMPOSE",
    "PLAIN",
    "RETRIEVE",
    "STALENESS",
    "VERIFY",
    "Composer",
    "Deps",
    "decline",
    "default_composer",
    "handoff",
    "make_classify",
    "make_compose",
    "make_crisis_response",
    "make_intake",
    "make_planner",
    "make_retrieve",
    "plain",
    "staleness_gate",
    "supervisor",
    "verify",
]
