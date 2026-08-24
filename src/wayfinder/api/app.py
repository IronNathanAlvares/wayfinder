"""The API. Threads, turns, the caseworker queue, and the corpus alarm.

Two design points carry over from everything below.

**The queue is the product.** PDD section 4 says Clare the caseworker is the user
this design optimises for, and her endpoint is the one that has to be good: an
escalation arrives with the question, a short situation summary, and the sources
already found, so she can answer in two minutes rather than twenty.

**`/v1/corpus/health` is not an afterthought.** Source staleness is the most
likely silent failure in this system, and an endpoint that returns 200 with a
list of rotting sources nobody reads is not an alarm. It returns 503 when a
source has aged out, so a monitor notices without anybody remembering to look.

Personal data is not persisted beyond the thread's checkpoint (PDD NG5). There is
a delete endpoint, and it is expected to be used.
"""

from __future__ import annotations

import secrets
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from wayfinder.api.auth import Caseworker, Caseworkers, load_caseworkers
from wayfinder.corpus.loader import load_corpus
from wayfinder.corpus.models import StalenessBand, staleness
from wayfinder.graph.build import compile_graph
from wayfinder.graph.checkpoint import thread
from wayfinder.graph.nodes import Deps
from wayfinder.graph.state import HumanDetermination, WayfinderState
from wayfinder.plan.situation import Situation
from wayfinder.retrieval.index import Index
from wayfinder.safety.escalation import ModelScreen
from wayfinder.safety.loader import load_directory, load_lexicon

DATA = Path(__file__).resolve().parent.parent / "corpus" / "data"


class StartThread(BaseModel):
    """Starting a thread. Deliberately no `thread_id`.

    The id is the credential. Applicants have no account, on purpose: asking
    somebody in an emergency accommodation queue to register before they can
    find out where the nearest GP is defeats the point of the project. That
    makes a thread id a bearer capability, and a capability the caller chooses
    is a capability anybody can guess. `amara` was a valid id until now.

    So the server mints it. `extra="forbid"` means a client still sending one is
    refused loudly rather than having it quietly ignored, which would leave
    somebody believing they had chosen an id that was really something else.
    """

    model_config = ConfigDict(extra="forbid")

    situation: Situation = Field(default_factory=Situation)


class SendTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


class Respond(BaseModel):
    """A caseworker's answer.

    There is deliberately no `answered_by`. The name a determination is signed
    with comes from the credential that posted it, so an answer cannot be
    attributed to somebody who did not give it. `extra="forbid"` means a body
    that still sends the old field is rejected loudly rather than having it
    quietly ignored, which would look like it still worked.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    source: str = ""


def create_app(
    *,
    deps: Deps | None = None,
    checkpointer: Any = None,
    today: date | None = None,
    model_screen: ModelScreen | None = None,
    caseworkers: Caseworkers | None = None,
) -> FastAPI:
    """Build the app.

    Dependencies are injected so a test drives the real routes with a stub
    composer and a fixed date. An app that can only be exercised against a live
    model is an app whose routes are untested.
    """
    on = today or date.today()  # noqa: DTZ011 - a calendar date is the right unit

    corpus = load_corpus(DATA, today=on)
    resolved = deps or Deps(
        lexicon=load_lexicon(today=on),
        directory=load_directory(today=on),
        index=Index(corpus, today=on),
        tasks=corpus.tasks,
        # ADR-0008: the lexicon alone caught 2 of 12 held-out crisis turns.
        # Serving without this is serving a screen known not to work.
        model_screen=model_screen,
    )
    graph = compile_graph(resolved, checkpointer=checkpointer)
    staff = caseworkers if caseworkers is not None else load_caseworkers()

    def signed_in(authorization: str = Header(default="")) -> Caseworker:
        """The caseworker behind this request, or a 401.

        Fails closed. With nobody registered the queue is shut rather than
        open, because a misconfiguration that silently unlocks a door is worse
        than one that stops the service: only one of them gets noticed.
        """
        if not staff.configured:
            raise HTTPException(
                status_code=503,
                detail=(
                    "no caseworkers are configured, so the queue is closed. "
                    "Set WAYFINDER_CASEWORKERS. See docs/14-getting-started.md."
                ),
            )

        scheme, _, token = authorization.partition(" ")
        person = staff.authenticate(token) if scheme.lower() == "bearer" else None
        if person is None:
            # Says a token was rejected and nothing about which, or why.
            raise HTTPException(
                status_code=401,
                detail="a valid caseworker token is required",
                headers={"WWW-Authenticate": 'Bearer realm="wayfinder"'},
            )
        return person

    app = FastAPI(
        title="Wayfinder",
        description=(
            "An ordered plan with prerequisites, and a refusal to answer the "
            "questions that need a human."
        ),
    )
    # Situations for threads that have not taken a turn yet. Once a turn runs,
    # the checkpoint is the record and this map is only a cache: see
    # `_situation_for`, which reads through to the checkpointer so a restart
    # does not silently reset somebody to knowing nothing about themselves.
    situations: dict[str, Situation] = {}

    def _known_thread_ids() -> list[str]:
        """Every thread the checkpointer has heard of, plus any started here.

        Read from the checkpointer rather than from `situations`, because
        `situations` is empty after a restart and a queue that empties on
        redeploy is the one failure this design cannot have.
        """
        seen = set(situations)
        if checkpointer is not None:
            seen.update(
                tup.config["configurable"]["thread_id"]
                for tup in checkpointer.list(None)
            )
        return sorted(seen)

    def _situation_for(thread_id: str) -> Situation | None:
        if thread_id in situations:
            return situations[thread_id]
        if checkpointer is None:
            return None
        values = graph.get_state(thread(thread_id)).values
        stored = values.get("situation") if values else None
        return stored if isinstance(stored, Situation) else None

    @app.post("/v1/threads", status_code=201)
    def start_thread(body: StartThread) -> dict[str, str]:
        """Mint an unguessable id and hand it back once.

        256 bits from `secrets`. Nothing about the person goes into it: an id
        derived from a name or a date of birth would be a capability that leaks
        what it protects, which for this population is the category of data
        whose disclosure can reach the authorities somebody left.
        """
        thread_id = secrets.token_urlsafe(32)
        situations[thread_id] = body.situation
        return {
            "thread_id": thread_id,
            "keep_this": (
                "This id is how you get back to your plan, and anybody who has "
                "it can read it. Keep it like a password."
            ),
        }

    @app.post("/v1/threads/{thread_id}/turn")
    def send_turn(thread_id: str, body: SendTurn) -> dict[str, Any]:
        state = WayfinderState(
            current_question=body.question,
            situation=_situation_for(thread_id) or Situation(),
            today=on,
        )
        result = graph.invoke(state, thread(thread_id))

        if "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            return {
                "status": "waiting_for_a_person",
                "why": (
                    "That question needs a decision about your own situation. "
                    "It has gone to a caseworker."
                ),
                "escalation": payload,
            }

        answer = result.get("answer")
        return {
            "status": "answered",
            "question_class": result["question_class"].value,
            "text": answer.text if answer else "",
            "citations": [
                {
                    "source": s.source_title,
                    "url": s.url,
                    "last_verified": s.last_verified.isoformat(),
                    "staleness": s.staleness.value,
                }
                for s in (answer.citations if answer else ())
            ],
        }

    @app.get("/v1/threads/{thread_id}/plan")
    def get_plan(thread_id: str) -> dict[str, Any]:
        from wayfinder.plan.builder import build_plan

        situation = _situation_for(thread_id)
        if situation is None:
            raise HTTPException(status_code=404, detail="no such thread")

        plan = build_plan(corpus.tasks, situation, today=on)
        titles = {i.task.id: i.task.title for i in plan.items}

        def clock(task_id: str) -> dict[str, Any] | None:
            """A closing window, or nothing. Never a claim that one has shut.

            `status` is at worst `may_have_closed`, and a client must not render
            it as expired: the start date came from somebody's memory of a
            letter, and late applications are often accepted. See
            `plan/deadlines.py` for why that asymmetry decides the wording.
            """
            state = plan.deadlines.get(task_id)
            if state is None:
                return None
            return {
                "status": state.status.value,
                "within_days": state.within.days,
                "runs_from": state.described_as,
                "started_on": state.started_on.isoformat()
                if state.started_on
                else None,
                "closes_on": state.closes_on.isoformat() if state.closes_on else None,
                "days_remaining": state.days_remaining,
            }

        return {
            "start_now": [
                {
                    "id": t,
                    "title": titles[t],
                    "gates_days": plan.gated_wait[t].days,
                    "deadline": clock(t),
                }
                for t in plan.frontier_order
            ],
            "not_yet": [
                {
                    "id": i.task.id,
                    "title": i.task.title,
                    "next_actions": [
                        titles.get(a, a) for a in plan.next_actions.get(i.task.id, ())
                    ],
                    # Named, never assessed. This is the field the whole design
                    # is built around.
                    "decided_by_somebody_else": list(i.determination_refs),
                    # A blocked task can have a window running down while
                    # somebody waits for the thing that unblocks it, which is
                    # when it matters most.
                    "deadline": clock(i.task.id),
                }
                for i in plan.blocked
            ],
            "questions_for_you": sorted(plan.open_questions),
        }

    @app.delete("/v1/threads/{thread_id}", status_code=204)
    def delete_thread(thread_id: str) -> Response:
        """NG5. The less it retains, the less there is to leak."""
        situations.pop(thread_id, None)
        return Response(status_code=204)

    # --- the caseworker's endpoints -----------------------------------------

    @app.get("/v1/queue")
    def queue(caseworker: Caseworker = Depends(signed_in)) -> dict[str, Any]:
        """Everything waiting on a person, with the context to answer it.

        Reads paused threads out of the checkpointer rather than a second store,
        so the queue cannot drift out of step with what the graph is actually
        waiting on.
        """
        if checkpointer is None:
            raise HTTPException(
                status_code=503,
                detail="no checkpointer configured, so there is no durable queue",
            )
        items = []
        for thread_id in _known_thread_ids():
            snapshot = graph.get_state(thread(thread_id))
            if snapshot.next != ("handoff",):
                continue
            pending = snapshot.tasks[0].interrupts if snapshot.tasks else ()
            items.append(
                {
                    "thread_id": thread_id,
                    "asked": snapshot.values.get("current_question", ""),
                    "context": pending[0].value if pending else {},
                }
            )
        return {"waiting": items}

    @app.post("/v1/queue/{thread_id}/respond")
    def respond(
        thread_id: str,
        body: Respond,
        caseworker: Caseworker = Depends(signed_in),
    ) -> dict[str, Any]:
        """Resume the graph with this caseworker's answer, signed with their name.

        The name comes from the token rather than the body. A determination
        that could be signed with any name is not the audit trail ADR-0004
        assumes, and the whole handoff rests on it being one.
        """
        from langgraph.types import Command

        if checkpointer is None:
            raise HTTPException(status_code=503, detail="no checkpointer configured")

        determination = HumanDetermination(
            answer=body.answer,
            answered_by=caseworker.name,
            answered_on=on,
            source=body.source,
        )
        result = graph.invoke(
            Command(resume=determination.model_dump(mode="json")), thread(thread_id)
        )
        answer = result.get("answer")
        return {
            "status": "answered",
            "attributed_to": answer.attributed_to if answer else "",
            "text": answer.text if answer else "",
        }

    @app.get("/v1/whoami")
    def whoami(caseworker: Caseworker = Depends(signed_in)) -> dict[str, str]:
        """What a token signs as, without spending it on a real answer.

        Worth having because the name on a determination is not the poster's to
        choose: somebody with a new token should be able to check what it will
        put in the audit trail before they use it.
        """
        return {"name": caseworker.name}

    # --- operations ----------------------------------------------------------

    @app.get("/v1/corpus/health")
    def corpus_health(response: Response) -> dict[str, Any]:
        """Staleness as an alarm rather than a report.

        Returns 503 once a source has aged out of retrieval, because a page
        nobody has checked in a year is how this system starts being quietly
        wrong while looking fine.
        """
        bands: dict[str, list[dict[str, str]]] = {b.value: [] for b in StalenessBand}
        for source in corpus.sources.values():
            band = staleness(source, today=on)
            bands[band.value].append(
                {
                    "id": source.id,
                    "publisher": source.publisher,
                    "last_verified": source.last_verified.isoformat(),
                }
            )

        excluded = bands[StalenessBand.EXCLUDED.value]
        if excluded:
            response.status_code = 503
        return {
            "checked_on": on.isoformat(),
            "tasks": len(corpus.tasks),
            "sources": len(corpus.sources),
            "bands": bands,
            "alarm": bool(excluded),
        }

    return app
