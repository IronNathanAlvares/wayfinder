"""Fixtures for the API tests.

The app is built with the same stub composer the graph tests use and a real
SQLite checkpointer in a temp directory. Stubbing the composer keeps the
assertions exact; using a real checkpointer keeps the queue honest, because an
in-memory one would make the caseworker round trip pass without ever proving
the pause is durable.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.graph.conftest import stub_composer
from wayfinder.api import create_app
from wayfinder.api.auth import Caseworker, Caseworkers, hash_token
from wayfinder.corpus.loader import load_corpus
from wayfinder.graph.checkpoint import sqlite_checkpointer
from wayfinder.graph.nodes import Deps
from wayfinder.retrieval.index import Index
from wayfinder.safety.loader import load_directory, load_lexicon

TODAY = date(2026, 8, 18)
DATA = Path(__file__).parents[2] / "src" / "wayfinder" / "corpus" / "data"

# Fixed rather than minted, so a failing test is reproducible. Long enough to
# clear the minimum length the real loader enforces.
CASEWORKER = "Clare Nolan, Irish Refugee Council"
TOKEN = "test-token-for-clare-nolan-not-a-real-credential"
OTHER = "Aoife Byrne, Citizens Information"
OTHER_TOKEN = "test-token-for-aoife-byrne-not-a-real-credential"

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def staff() -> Caseworkers:
    return Caseworkers(
        [
            Caseworker(name=CASEWORKER, token_sha256=hash_token(TOKEN)),
            Caseworker(name=OTHER, token_sha256=hash_token(OTHER_TOKEN)),
        ]
    )


def build_deps(on: date = TODAY) -> Deps:
    corpus = load_corpus(DATA, today=on)
    return Deps(
        lexicon=load_lexicon(today=on),
        directory=load_directory(today=on),
        index=Index(corpus, today=on),
        tasks=corpus.tasks,
        composer=stub_composer,
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with sqlite_checkpointer(tmp_path / "api.sqlite") as saver:
        app = create_app(
            deps=build_deps(), checkpointer=saver, today=TODAY, caseworkers=staff()
        )
        with TestClient(app) as c:
            yield c


@pytest.fixture
def stateless() -> Iterator[TestClient]:
    """No checkpointer. The queue endpoints must say so rather than pretend."""
    app = create_app(deps=build_deps(), today=TODAY, caseworkers=staff())
    with TestClient(app) as c:
        yield c


def start(client: TestClient, thread_id: str, **situation: Any) -> None:
    response = client.post(
        "/v1/threads", json={"thread_id": thread_id, "situation": situation}
    )
    assert response.status_code == 201, response.text
