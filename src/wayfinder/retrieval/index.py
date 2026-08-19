"""Retrieval over the corpus, scoped to one domain and filtered by staleness.

What is being retrieved is worth stating plainly, because it is smaller than
"retrieval" usually implies. The corpus is a task graph with citations, not a
document store: it holds what a task is, why it matters, and which dated source
says so. It does not hold the text of those sources. So this searches the task
records and returns them with their citations attached, and the composer works
from that.

That is a real limitation rather than a design flourish. Answering "what exactly
does the form ask for" needs the page text, and the honest response to such a
question today is that there is no reliable source for it in the corpus, which
is a supported outcome rather than a failure.

BM25 rather than embeddings, for two reasons that both come down to the corpus
being small and hand-written. Vocabulary here is controlled, so lexical matching
does most of the work an embedding would. And a scoring function somebody can
read beats one nobody can explain when the answer has to be defensible.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict

from wayfinder.corpus.models import Corpus, Source, StalenessBand, staleness
from wayfinder.plan.models import Domain, Task

# Standard BM25 parameters. k1 controls how fast term frequency saturates and b
# how much document length is penalised. The defaults are the usual ones and
# there is no tuning set here to justify moving them.
K1 = 1.5
B = 0.75

# A span must match at least this many distinct query terms to be returned at
# all. Without it, one incidental word in common is enough to attach a citation
# to a question the corpus knows nothing about, and a confident answer with a
# real-looking source on an unrelated topic is worse than no answer. Queries
# shorter than this fall back to requiring every term.
MINIMUM_MATCHED_TERMS = 2

_TOKEN = re.compile(r"[a-z0-9]+")

# Words that carry no signal in a corpus where every document is about applying
# for something. "apply" appearing in forty tasks does not discriminate between
# them, and neither does "you".
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    ]
)


def tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


class RetrievedSpan(BaseModel):
    """One task, with the dated citation that supports it.

    `staleness` travels with the span rather than being looked up later, so a
    composer physically cannot use a span without seeing how old its source is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    title: str
    why: str
    domain: Domain
    source_id: str
    source_title: str
    url: str
    last_verified: date
    staleness: StalenessBand
    score: float

    @property
    def citable(self) -> bool:
        """Whether a claim may rest on this at all.

        Past a year a source is excluded from retrieval entirely, so this is
        belt and braces for anything that builds a span by hand.
        """
        return self.staleness is not StalenessBand.EXCLUDED


class Index:
    """A BM25 index over the corpus, built once and queried per turn."""

    def __init__(self, corpus: Corpus, *, today: date) -> None:
        self._corpus = corpus
        self._today = today

        self._docs: list[tuple[Task, Source]] = []
        for task in corpus.tasks:
            for span in task.where:
                source = corpus.source_for(span.source_id)
                if source is None:  # pragma: no cover - the loader rejects this
                    continue
                # Excluded sources are dropped at index time rather than
                # filtered at query time. A source nobody has checked in a year
                # should not be reachable by any query, including one written
                # later that forgets to filter.
                if staleness(source, today=today) is StalenessBand.EXCLUDED:
                    continue
                self._docs.append((task, source))

        self._tokens = [
            tokenise(f"{t.title} {t.why} {t.domain.value}") for t, _ in self._docs
        ]
        self._lengths = [len(t) for t in self._tokens]
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        self._frequencies = [Counter(t) for t in self._tokens]

        document_count = len(self._docs)
        appearances: Counter[str] = Counter()
        for terms in self._frequencies:
            appearances.update(terms.keys())
        self._idf = {
            term: math.log(1 + (document_count - n + 0.5) / (n + 0.5))
            for term, n in appearances.items()
        }

    @property
    def size(self) -> int:
        return len(self._docs)

    def excluded_sources(self) -> tuple[str, ...]:
        """Sources dropped for age. The operational alarm, as a list."""
        return tuple(
            sorted(
                s.id
                for s in self._corpus.sources.values()
                if staleness(s, today=self._today) is StalenessBand.EXCLUDED
            )
        )

    def search(
        self,
        query: str,
        *,
        domain: Domain | None = None,
        limit: int = 5,
    ) -> tuple[RetrievedSpan, ...]:
        """Top matches, scoped to a domain when one is given.

        Scoping is not an optimisation. A supervisor routes a question to one
        domain, and letting retrieval wander outside it would let a banking
        answer cite a healthcare source, which is how a plausible wrong answer
        gets built.
        """
        terms = tokenise(query)
        if not terms:
            return ()

        distinct = set(terms)
        required = min(MINIMUM_MATCHED_TERMS, len(distinct))

        scored: list[tuple[float, int]] = []
        for i, (task, _source) in enumerate(self._docs):
            if domain is not None and task.domain is not domain:
                continue
            matched = sum(1 for term in distinct if self._frequencies[i].get(term))
            if matched < required:
                continue
            score = self._score(terms, i)
            if score > 0:
                scored.append((score, i))

        scored.sort(key=lambda pair: (-pair[0], self._docs[pair[1]][0].id))
        return tuple(self._span(i, score) for score, i in scored[:limit])

    def _score(self, terms: Sequence[str], doc: int) -> float:
        frequencies = self._frequencies[doc]
        length = self._lengths[doc]
        total = 0.0
        for term in terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            idf = self._idf.get(term, 0.0)
            denominator = frequency + K1 * (
                1 - B + B * length / (self._average_length or 1.0)
            )
            total += idf * (frequency * (K1 + 1)) / denominator
        return total

    def _span(self, doc: int, score: float) -> RetrievedSpan:
        task, source = self._docs[doc]
        return RetrievedSpan(
            task_id=task.id,
            title=task.title,
            why=task.why,
            domain=task.domain,
            source_id=source.id,
            source_title=source.title,
            url=source.url,
            last_verified=source.last_verified,
            staleness=staleness(source, today=self._today),
            score=score,
        )


def needs_verifying(spans: Iterable[RetrievedSpan]) -> tuple[RetrievedSpan, ...]:
    """Spans old enough that the answer has to say so."""
    return tuple(
        s
        for s in spans
        if s.staleness in {StalenessBand.VERIFY, StalenessBand.DOWNGRADE}
    )
