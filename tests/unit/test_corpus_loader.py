"""Corpus integrity, which fails the build rather than warning.

A corpus that loads with a warning is a corpus that ships with the warning
ignored. The failure mode at the far end is somebody making a journey they
cannot afford on a prerequisite that was wrong.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import FIXTURES
from wayfinder.corpus.loader import CorpusError, load_corpus
from wayfinder.corpus.models import Corpus, Source, StalenessBand, staleness


def test_a_broken_corpus_reports_every_problem_at_once(today: date) -> None:
    """One error at a time turns editing YAML into a game of whack-a-mole."""
    with pytest.raises(CorpusError) as caught:
        load_corpus(FIXTURES / "broken_corpus", today=today)
    problems = caught.value.problems
    assert len(problems) >= 5
    joined = "\n".join(problems)
    assert "last_verified" in joined
    assert "future" in joined
    assert "unknown source" in joined
    assert "undeclared artefact" in joined
    assert "must name `decided_by`" in joined
    assert "Determinations are made by authorities" in joined


def test_a_source_without_a_date_fails_to_load(today: date) -> None:
    """An undated source is indistinguishable from a stale one."""
    with pytest.raises(CorpusError, match="last_verified"):
        load_corpus(FIXTURES / "broken_corpus", today=today)


def test_a_good_corpus_loads(corpus: Corpus) -> None:
    assert len(corpus.tasks) == 12
    assert "synthetic.handbook" in corpus.sources
    assert corpus.artefact("determination:residence_test") is not None


def test_every_task_cites_a_source_that_exists(corpus: Corpus) -> None:
    for task in corpus.tasks:
        assert task.where
        for span in task.where:
            assert corpus.source_for(span.source_id) is not None


def test_every_referenced_artefact_is_declared(corpus: Corpus) -> None:
    """Catches the typo class of bug, which is otherwise silent.

    `document:pps_number` against `document:ppsn` produces a task that never
    links to anything and a plan that is quietly missing an edge.
    """
    declared = set(corpus.artefacts)
    for task in corpus.tasks:
        for requirement in task.requires:
            for ref in requirement.any_of:
                if ref.startswith(("elapsed:", "task:")):
                    continue
                assert ref in declared, f"{task.id} references {ref}"


def test_every_determination_names_its_authority(corpus: Corpus) -> None:
    for ref, artefact in corpus.artefacts.items():
        if ref.startswith("determination:"):
            assert artefact.decided_by


@pytest.mark.parametrize(
    ("age_days", "expected"),
    [
        (0, StalenessBand.NORMAL),
        (89, StalenessBand.NORMAL),
        (90, StalenessBand.VERIFY),
        (179, StalenessBand.VERIFY),
        (180, StalenessBand.DOWNGRADE),
        (364, StalenessBand.DOWNGRADE),
        (365, StalenessBand.EXCLUDED),
        (900, StalenessBand.EXCLUDED),
    ],
)
def test_staleness_bands_are_table_driven(
    age_days: int, expected: StalenessBand
) -> None:
    today = date(2026, 8, 17)
    source = Source(
        id="s",
        title="t",
        publisher="p",
        url="https://example.invalid/x",
        last_verified=today - timedelta(days=age_days),
        verified_by="test",
    )
    assert staleness(source, today=today) is expected


def test_corpus_health_groups_every_source(corpus: Corpus, today: date) -> None:
    health = corpus.health(today=today)
    counted = sum(len(ids) for ids in health.values())
    assert counted == len(corpus.sources)
