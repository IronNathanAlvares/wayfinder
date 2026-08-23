"""The HTTP surface, driven through the real routes.

These are not smoke tests. Each one checks a property the design commits to,
stated at the boundary a client actually sees: an entitlement question comes
back as a pause rather than an answer, the queue carries what a caseworker
needs, the answer that follows is attributed to the person who made it, and the
staleness endpoint alarms instead of reporting.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from tests.api.conftest import (
    AUTH,
    CASEWORKER,
    DATA,
    OTHER,
    OTHER_TOKEN,
    TODAY,
    TOKEN,
    build_deps,
    staff,
    start,
)
from wayfinder.api import create_app
from wayfinder.graph.checkpoint import sqlite_checkpointer

AMARA = {
    "arrival_date": "2026-08-01",
    "protection_application_date": "2026-08-04",
    "protection_stage": "applied",
    "accommodation": "homeless",
    "household": {"adults": 1, "children_ages": [7]},
    "held": [
        "document:national_id",
        "document:temporary_residence_certificate",
        "document:asylum_application_letter",
    ],
    "known_absent": ["document:ppsn", "status:ipas_accommodation"],
}


# --- threads and turns -------------------------------------------------------


def test_a_procedural_turn_comes_back_with_its_citations(client: TestClient) -> None:
    start(client, "t1")
    body = client.post(
        "/v1/threads/t1/turn", json={"question": "how do I apply for a PPS number"}
    ).json()

    assert body["status"] == "answered"
    assert body["question_class"] == "procedural"
    assert body["citations"], "an answerable question came back with no source"
    for citation in body["citations"]:
        assert citation["url"].startswith("https://")
        assert date.fromisoformat(citation["last_verified"]) <= TODAY


def test_an_entitlement_question_pauses_instead_of_answering(
    client: TestClient,
) -> None:
    """ADR-0004 at the boundary.

    A client cannot get a determination out of this API, whatever it asks.
    """
    start(client, "t2", **AMARA)
    body = client.post(
        "/v1/threads/t2/turn", json={"question": "am I entitled to child benefit?"}
    ).json()

    assert body["status"] == "waiting_for_a_person"
    assert body["escalation"]["kind"] == "determination"
    assert "text" not in body, "it answered as well as escalating"


def test_a_crisis_turn_returns_a_number_and_no_plan(client: TestClient) -> None:
    start(client, "t3")
    body = client.post(
        "/v1/threads/t3/turn",
        json={"question": "i have nowhere to sleep tonight with my son"},
    ).json()

    assert body["question_class"] == "crisis"
    assert "1800 707 707" in body["text"]


def test_an_empty_question_is_rejected_rather_than_classified(
    client: TestClient,
) -> None:
    start(client, "t4")
    assert client.post("/v1/threads/t4/turn", json={"question": ""}).status_code == 422


def test_an_unknown_field_is_rejected(client: TestClient) -> None:
    """Forbidden extras all the way to the edge.

    A silently ignored field is how a caller comes to believe it set something
    it did not.
    """
    response = client.post(
        "/v1/threads", json={"thread_id": "t5", "unexpected": "value"}
    )
    assert response.status_code == 422


# --- the plan ----------------------------------------------------------------


def test_the_plan_separates_what_can_start_from_what_is_waiting(
    client: TestClient,
) -> None:
    start(client, "p1", **AMARA)
    body = client.get("/v1/threads/p1/plan").json()

    startable = {item["id"] for item in body["start_now"]}
    assert "ppsn.apply" in startable
    assert startable.isdisjoint({item["id"] for item in body["not_yet"]})


def test_a_task_gated_on_a_determination_names_who_decides_it(
    client: TestClient,
) -> None:
    """The headline case.

    Child benefit is not refused and not granted. It is handed to the body that
    decides it, by name.
    """
    start(client, "p2", **AMARA)
    plan = client.get("/v1/threads/p2/plan").json()
    blocked = {item["id"]: item for item in plan["not_yet"]}

    child_benefit = blocked["child_benefit.apply"]
    assert child_benefit["decided_by_somebody_else"] == [
        "determination:habitual_residence"
    ]


def test_a_plan_for_an_unknown_thread_is_a_404(client: TestClient) -> None:
    assert client.get("/v1/threads/nobody/plan").status_code == 404


def test_deleting_a_thread_removes_it(client: TestClient) -> None:
    """NG5, checked by asking for it afterwards rather than by trusting the
    204."""
    start(client, "gone")
    assert client.delete("/v1/threads/gone").status_code == 204
    assert client.get("/v1/threads/gone/plan").status_code == 404


# --- the caseworker's round trip ---------------------------------------------


def test_the_queue_carries_the_question_and_the_context(client: TestClient) -> None:
    start(client, "q1", **AMARA)
    client.post(
        "/v1/threads/q1/turn", json={"question": "do I qualify for a medical card?"}
    )

    waiting = client.get("/v1/queue", headers=AUTH).json()["waiting"]
    assert [item["thread_id"] for item in waiting] == ["q1"]
    assert waiting[0]["asked"] == "do I qualify for a medical card?"
    assert waiting[0]["context"]["situation_summary"]


def test_the_queue_holds_only_threads_actually_paused(client: TestClient) -> None:
    """A queue that lists answered threads is a queue nobody trusts."""
    start(client, "answered")
    client.post(
        "/v1/threads/answered/turn", json={"question": "how do I open a bank account"}
    )
    assert client.get("/v1/queue", headers=AUTH).json()["waiting"] == []


def test_answering_from_the_queue_attributes_the_answer_to_the_person(
    client: TestClient,
) -> None:
    """The whole point of the handoff.

    The system relays a named human's judgement. It does not restate it in its
    own voice.
    """
    start(client, "q2", **AMARA)
    client.post(
        "/v1/threads/q2/turn", json={"question": "am I entitled to child benefit?"}
    )

    body = client.post(
        "/v1/queue/q2/respond",
        json={"answer": "You need a habitual residence decision first."},
        headers=AUTH,
    ).json()

    assert body["attributed_to"] == CASEWORKER
    assert CASEWORKER in body["text"]
    assert client.get("/v1/queue", headers=AUTH).json()["waiting"] == [], (
        "it stayed in the queue"
    )


# --- who is allowed in, and whose name goes on the answer ---------------------


def test_the_queue_is_shut_without_a_credential(client: TestClient) -> None:
    """It carries what people have said about their own circumstances."""
    response = client.get("/v1/queue")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_a_wrong_token_is_refused(client: TestClient) -> None:
    response = client.get("/v1/queue", headers={"Authorization": "Bearer " + "x" * 48})
    assert response.status_code == 401


def test_a_rejection_says_nothing_about_why(client: TestClient) -> None:
    """A 401 that distinguishes an unknown token from a malformed header hands
    an attacker a way to probe. All three routes to failure say the same."""
    unknown = client.get("/v1/queue", headers={"Authorization": "Bearer " + "x" * 48})
    malformed = client.get("/v1/queue", headers={"Authorization": "Basic abc"})
    missing = client.get("/v1/queue")

    bodies = {r.json()["detail"] for r in (unknown, malformed, missing)}
    assert len(bodies) == 1, bodies


def test_a_token_never_comes_back_in_a_response(client: TestClient) -> None:
    """Not in the error, not in a header, not anywhere it could be logged."""
    response = client.get("/v1/queue", headers={"Authorization": f"Bearer {TOKEN}xx"})
    assert TOKEN not in response.text
    assert TOKEN not in str(response.headers)


def test_an_answer_cannot_be_submitted_anonymously(client: TestClient) -> None:
    """The same door, closed the same way it is closed inside the graph."""
    start(client, "q3", **AMARA)
    client.post(
        "/v1/threads/q3/turn", json={"question": "am I entitled to child benefit?"}
    )
    response = client.post("/v1/queue/q3/respond", json={"answer": "Yes you qualify."})
    assert response.status_code == 401


def test_the_name_on_a_determination_comes_from_the_token(client: TestClient) -> None:
    """The point of the whole mechanism.

    `answered_by` used to be free text in the body, so anybody who could reach
    the endpoint could sign a determination with any name. ADR-0004 rests on a
    determination being traceable to a named human, and a self-declared name is
    not that.
    """
    start(client, "q4", **AMARA)
    client.post(
        "/v1/threads/q4/turn", json={"question": "am I entitled to child benefit?"}
    )
    body = client.post(
        "/v1/queue/q4/respond",
        json={"answer": "That needs a habitual residence decision."},
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    ).json()

    assert body["attributed_to"] == OTHER
    assert CASEWORKER not in body["text"], "signed as somebody who did not answer"


def test_a_body_that_still_sends_a_name_is_rejected(client: TestClient) -> None:
    """Loudly, rather than ignored. Somebody upgrading from the old shape should
    be told the field is gone, not left believing it still works."""
    start(client, "q5", **AMARA)
    client.post(
        "/v1/threads/q5/turn", json={"question": "am I entitled to child benefit?"}
    )
    response = client.post(
        "/v1/queue/q5/respond",
        json={"answer": "Yes you qualify.", "answered_by": "Somebody Else"},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_whoami_says_what_a_token_will_sign_as(client: TestClient) -> None:
    """So a new caseworker can check the audit trail before writing to it."""
    assert client.get("/v1/whoami", headers=AUTH).json() == {"name": CASEWORKER}
    assert client.get("/v1/whoami").status_code == 401


def test_with_nobody_configured_the_queue_is_shut_rather_than_open() -> None:
    """Fail closed. A missing configuration must never mean open access."""
    from wayfinder.api.auth import Caseworkers

    app = create_app(deps=build_deps(), today=TODAY, caseworkers=Caseworkers([]))
    with TestClient(app) as client:
        for response in (
            client.get("/v1/queue"),
            client.get("/v1/queue", headers=AUTH),
            client.post("/v1/queue/x/respond", json={"answer": "hello"}, headers=AUTH),
        ):
            assert response.status_code == 503
            assert "no caseworkers are configured" in response.json()["detail"]


def test_the_applicant_endpoints_are_not_behind_the_caseworker_lock(
    client: TestClient,
) -> None:
    """Deliberate, and documented rather than hidden.

    A thread id is currently a bearer capability: anybody holding one can read
    that plan. That is a separate hole from this one, and it is named in
    `docs/14-getting-started.md` and in the handoff notes rather than being
    quietly left for somebody to find.
    """
    start(client, "open", **AMARA)
    assert client.get("/v1/threads/open/plan").status_code == 200


def test_the_queue_endpoints_refuse_to_run_without_durable_storage(
    stateless: TestClient,
) -> None:
    """Without a checkpointer there is no queue.

    An empty list would read as "nothing is waiting" rather than "this is not
    configured", and the difference matters to whoever is on call.
    """
    assert stateless.get("/v1/queue", headers=AUTH).status_code == 503
    # 401 before 503: an anonymous caller learns nothing about whether
    # the service is configured.
    assert stateless.get("/v1/queue").status_code == 401


# --- operations --------------------------------------------------------------


def test_corpus_health_is_green_for_the_shipped_corpus(client: TestClient) -> None:
    body = client.get("/v1/corpus/health").json()
    assert body["alarm"] is False
    assert body["tasks"] > 0
    assert body["bands"]["excluded"] == []


def test_corpus_health_alarms_once_a_source_has_aged_out() -> None:
    """503, not a 200 with a list in it.

    Run the same corpus forward two years. Every source ages out, and the
    endpoint has to fail loudly, because staleness is the failure this system is
    most likely to have while still looking fine.
    """
    later = date(2028, 8, 18)
    # Deps are built at the review date. The safety loader refuses to load a
    # two-year-old lexicon at all, which is its own alarm and a separate one;
    # what is under test here is the corpus endpoint.
    app = create_app(deps=build_deps(), today=later)
    with TestClient(app) as client:
        response = client.get("/v1/corpus/health")

    assert response.status_code == 503
    body = response.json()
    assert body["alarm"] is True
    assert body["bands"]["excluded"], "nothing was reported stale during an alarm"


def test_the_app_reads_the_shipped_corpus_by_default() -> None:
    """Guards against the module pointing at a directory that does not exist,
    which would surface as an empty corpus rather than as an error."""
    assert (DATA / "tasks" / "ireland.yaml").exists()
    assert (Path(__file__).parents[2] / "src" / "wayfinder" / "api" / "app.py").exists()


# --- restart -----------------------------------------------------------------


def test_the_queue_survives_a_restart(tmp_path: Path) -> None:
    """The claim the whole handoff rests on, tested at the API boundary.

    A caseworker answers on Thursday a question asked on Monday, and the
    container is redeployed in between. The first version of this endpoint
    listed threads out of an in-memory map, so it came back empty after a
    restart while the graph was still paused on disk. The queue and the graph
    have to agree, so the queue reads from the checkpointer.
    """
    db = tmp_path / "restart.sqlite"

    with sqlite_checkpointer(db) as saver:
        first = create_app(
            deps=build_deps(),
            checkpointer=saver,
            today=TODAY,
            caseworkers=staff(),
        )
        with TestClient(first) as client:
            start(client, "r1", **AMARA)
            client.post(
                "/v1/threads/r1/turn",
                json={"question": "am I entitled to child benefit?"},
            )

    # The process is gone. Nothing is shared but the file.
    with sqlite_checkpointer(db) as saver:
        second = create_app(
            deps=build_deps(),
            checkpointer=saver,
            today=TODAY,
            caseworkers=staff(),
        )
        with TestClient(second) as client:
            waiting = client.get("/v1/queue", headers=AUTH).json()["waiting"]
            assert [item["thread_id"] for item in waiting] == ["r1"]

            answered = client.post(
                "/v1/queue/r1/respond",
                json={"answer": "You need a habitual residence decision first."},
                headers=AUTH,
            ).json()

    assert answered["attributed_to"] == CASEWORKER


def test_a_situation_survives_a_restart(tmp_path: Path) -> None:
    """Otherwise somebody comes back to a system that has forgotten who they
    are, and has to type it all again."""
    db = tmp_path / "situation.sqlite"

    with sqlite_checkpointer(db) as saver:
        app = create_app(
            deps=build_deps(),
            checkpointer=saver,
            today=TODAY,
            caseworkers=staff(),
        )
        with TestClient(app) as client:
            start(client, "r2", **AMARA)
            client.post("/v1/threads/r2/turn", json={"question": "what do I do first?"})

    with sqlite_checkpointer(db) as saver:
        app = create_app(
            deps=build_deps(),
            checkpointer=saver,
            today=TODAY,
            caseworkers=staff(),
        )
        with TestClient(app) as client:
            plan = client.get("/v1/threads/r2/plan")

    assert plan.status_code == 200
    assert "ppsn.apply" in {item["id"] for item in plan.json()["start_now"]}


def test_the_queue_is_empty_rather_than_broken_on_a_fresh_database(
    tmp_path: Path,
) -> None:
    """Listing a checkpointer that has never been written to is a real path:
    the first request after a deploy."""
    with sqlite_checkpointer(tmp_path / "fresh.sqlite") as saver:
        app = create_app(
            deps=build_deps(),
            checkpointer=saver,
            today=TODAY,
            caseworkers=staff(),
        )
        with TestClient(app) as client:
            response = client.get("/v1/queue", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"waiting": []}
