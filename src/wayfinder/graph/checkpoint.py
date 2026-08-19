"""The checkpointer. This is what makes the handoff real rather than decorative.

When `interrupt()` fires, the executor serialises the full state snapshot under
the thread id and unwinds cleanly. The process can restart. The caseworker can
answer on Thursday a question asked on Monday. `Command(resume=...)` picks up
exactly where it stopped.

SQLite for development, Postgres for deployment. The file path matters more than
it looks: an in-memory checkpointer makes every test pass and makes the durable
pause a fiction, because the state never has to survive anything.

**The deserialisation allowlist.** LangGraph's default is to deserialise any
type it finds in a checkpoint and warn, and its own docstring says an attacker
who can write to the checkpoint database may be able to trigger code execution.
That is a live concern here: the database holds paused threads containing what
somebody said about their own situation, and it outlives the process by days.
So the types that may come back out are listed, by class rather than by name so
a typo is an import error. `tests/graph/test_checkpoint_allowlist.py` fails if a
state field starts carrying a type this list does not name.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from wayfinder.corpus.models import StalenessBand
from wayfinder.graph.state import Answer, HumanDetermination, TraceEvent, Turn
from wayfinder.plan.conditions import (
    AllOf,
    Always,
    AnyOf,
    ChildAged,
    FieldEquals,
    FieldIn,
    Holds,
    Negation,
)
from wayfinder.plan.models import Domain, Prerequisite, Severity, SourceSpan, Task
from wayfinder.plan.plan import ItemStatus, Plan, PlanItem
from wayfinder.plan.refs import ArtefactKind
from wayfinder.plan.situation import (
    Accommodation,
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)
from wayfinder.retrieval.index import RetrievedSpan
from wayfinder.safety.models import Classification, CrisisCategory, CrisisHit
from wayfinder.safety.taxonomy import Layer, QuestionClass

CHECKPOINTED_TYPES: Final[tuple[type, ...]] = (
    # What the turn produced
    Turn,
    TraceEvent,
    Answer,
    HumanDetermination,
    RetrievedSpan,
    StalenessBand,
    # What the safety layers decided
    QuestionClass,
    Layer,
    Classification,
    CrisisHit,
    CrisisCategory,
    # What the person told us
    Situation,
    Household,
    ProtectionStage,
    Accommodation,
    DeterminationRecord,
    DeterminationOutcome,
    # The plan and everything hanging off it
    Plan,
    PlanItem,
    ItemStatus,
    Task,
    Prerequisite,
    SourceSpan,
    Domain,
    Severity,
    ArtefactKind,
    Always,
    AllOf,
    AnyOf,
    Negation,
    FieldEquals,
    FieldIn,
    Holds,
    ChildAged,
)


def serializer() -> JsonPlusSerializer:
    """The serialiser every checkpointer in this project uses."""
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINTED_TYPES)


@contextmanager
def sqlite_checkpointer(path: Path | str) -> Iterator[Any]:
    """A checkpointer backed by a file on disk.

    `check_same_thread=False` because the saver is used from whichever thread
    the executor happens to be on, and the connection is owned by this context
    manager rather than shared.
    """
    try:
        connection = sqlite3.connect(str(path), check_same_thread=False)
    except sqlite3.OperationalError as exc:
        # SQLite says "unable to open database file" and does not say which one,
        # which is a bad message for the thing holding the caseworker queue.
        msg = f"could not open the checkpoint database at {path}: {exc}"
        raise sqlite3.OperationalError(msg) from exc
    try:
        yield SqliteSaver(connection, serde=serializer())
    finally:
        connection.close()


def thread(thread_id: str) -> dict[str, Any]:
    """The config every call needs. One thread per person per session."""
    return {"configurable": {"thread_id": thread_id}}
