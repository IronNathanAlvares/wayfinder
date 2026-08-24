"""Fixtures for the graph tests.

The composer is a stub and the date is fixed. Neither is a shortcut: the graph's
claims are about control flow and durability, and a real composer would make
every one of these tests depend on a model's mood.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wayfinder.corpus.loader import load_corpus
from wayfinder.graph.build import compile_graph
from wayfinder.graph.nodes import Deps
from wayfinder.retrieval.index import Index, RetrievedSpan
from wayfinder.safety.loader import load_directory, load_lexicon

TODAY = date(2026, 8, 24)
DATA = Path(__file__).parents[2] / "src" / "wayfinder" / "corpus" / "data"


def stub_composer(question: str, spans: Sequence[RetrievedSpan]) -> str:
    """States only what the spans say. Nothing sampled, nothing invented."""
    if not spans:
        return "I do not have a reliable source for that."
    return "\n".join(f"{s.title}. Source: {s.source_title}." for s in spans)


@pytest.fixture(scope="session")
def deps() -> Deps:
    corpus = load_corpus(DATA, today=TODAY)
    return Deps(
        lexicon=load_lexicon(today=TODAY),
        directory=load_directory(today=TODAY),
        index=Index(corpus, today=TODAY),
        tasks=corpus.tasks,
        composer=stub_composer,
    )


@pytest.fixture(scope="session")
def compiled(deps: Deps) -> Any:
    """Compiled without a checkpointer. Topology only, no durability.

    Typed `Any` because `CompiledStateGraph` carries four type parameters that
    say nothing useful at a call site and change between LangGraph releases.
    """
    return compile_graph(deps)
