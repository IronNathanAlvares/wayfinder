"""The corpus: hand-curated tasks, declared artefacts, and dated sources."""

from wayfinder.corpus.loader import CorpusError, load_corpus
from wayfinder.corpus.models import (
    Artefact,
    Corpus,
    Source,
    StalenessBand,
    staleness,
)

__all__ = [
    "Artefact",
    "Corpus",
    "CorpusError",
    "Source",
    "StalenessBand",
    "load_corpus",
    "staleness",
]
