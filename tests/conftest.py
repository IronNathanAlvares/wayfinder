"""Shared fixtures.

`TODAY` is frozen. A plan test that reads the wall clock starts failing
overnight for reasons that have nothing to do with the code, and the whole
point of the engine being pure is that it does not do that.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from wayfinder.corpus.loader import load_corpus
from wayfinder.corpus.models import Corpus

TODAY = date(2026, 8, 17)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return load_corpus(FIXTURES / "corpus", today=TODAY)


@pytest.fixture(scope="session")
def today() -> date:
    return TODAY
