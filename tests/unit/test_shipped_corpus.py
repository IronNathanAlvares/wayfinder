"""The corpus that actually ships, checked for the properties content must have.

These are deliberately not exact-plan assertions. The reference personas assert
exact plans against the synthetic fixture corpus so that curating real content
in M2 cannot break the engine's tests. What is asserted here is the set of
things that must be true of any content, however much of it there is.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
import yaml

from wayfinder.cli.main import DEFAULT_CORPUS
from wayfinder.corpus.loader import load_corpus
from wayfinder.corpus.models import Corpus, StalenessBand
from wayfinder.plan.builder import build_plan
from wayfinder.plan.refs import ArtefactKind, artefact_kind
from wayfinder.plan.situation import Accommodation, ProtectionStage, Situation
from wayfinder.retrieval.index import Index

BUILT_ON = date(2026, 8, 18)


@pytest.fixture(scope="module")
def shipped() -> Corpus:
    return load_corpus(DEFAULT_CORPUS, today=BUILT_ON)


def test_the_shipped_corpus_loads_and_is_not_empty(shipped: Corpus) -> None:
    assert shipped.tasks
    assert shipped.sources


def test_every_shipped_source_was_verified_on_a_real_date(shipped: Corpus) -> None:
    for source in shipped.sources.values():
        assert source.last_verified <= BUILT_ON
        assert source.verified_by


def test_no_shipped_source_is_already_stale(shipped: Corpus) -> None:
    """A corpus that ships stale has nothing to say about staleness."""
    health = shipped.health(today=BUILT_ON)
    assert health[StalenessBand.DOWNGRADE] == ()
    assert health[StalenessBand.EXCLUDED] == ()


def test_no_task_states_an_amount(shipped: Corpus) -> None:
    """Amounts change most often and are what people plan around.

    A stale figure in this corpus does more damage than a missing one, so the
    tasks say a payment exists and where to ask, and never what it pays.
    """
    money = re.compile(r"[€$£]\s?\d|\b\d+(\.\d+)?\s*(euro|eur)\b", re.IGNORECASE)
    for task in shipped.tasks:
        text = f"{task.title} {task.why}"
        assert not money.search(text), f"{task.id} states an amount"


def test_no_task_asserts_an_entitlement(shipped: Corpus) -> None:
    """The corpus describes processes. It never applies a rule to a person."""
    banned = (
        "you are entitled",
        "you may be entitled",
        "you qualify",
        "you will receive",
        "you will get",
        "you are eligible",
        "you should receive",
    )
    for task in shipped.tasks:
        text = f"{task.title} {task.why}".lower()
        for phrase in banned:
            assert phrase not in text, f"{task.id}: {phrase}"


def test_every_determination_names_the_body_that_decides_it(shipped: Corpus) -> None:
    determinations = [
        a
        for ref, a in shipped.artefacts.items()
        if artefact_kind(ref) is ArtefactKind.DETERMINATION
    ]
    assert determinations, "the shipped corpus should model at least one determination"
    for artefact in determinations:
        assert artefact.decided_by


def test_no_shipped_task_claims_to_produce_a_determination(shipped: Corpus) -> None:
    """Enforced by the model too. Asserted here against the real content."""
    for task in shipped.tasks:
        for ref in task.produces:
            assert artefact_kind(ref) is not ArtefactKind.DETERMINATION


def test_the_demo_situation_produces_a_usable_plan(shipped: Corpus) -> None:
    situation = Situation(
        arrival_date=date(2026, 8, 1),
        protection_application_date=date(2026, 8, 4),
        protection_stage=ProtectionStage.APPLIED,
        accommodation=Accommodation.HOMELESS,
        held=frozenset(
            {
                "document:national_id",
                "document:temporary_residence_certificate",
                "document:asylum_application_letter",
            }
        ),
        known_absent=frozenset(
            {
                "document:ppsn",
                "document:proof_of_address",
                "document:medical_card",
                "status:labour_market_access",
            }
        ),
    )
    plan = build_plan(shipped.tasks, situation, today=BUILT_ON)
    assert plan.frontier_order[0] == "ppsn.apply"
    assert "accommodation.move_in" in plan.ids()
    assert plan.unroutable["accommodation.move_in"] == (
        "determination:ipas_accommodation_offer",
    )


def test_the_corpus_readme_is_honest_about_what_is_missing() -> None:
    """The README claims three sources were unreachable. Check it still says so.

    If somebody later adds those sources without updating the README, the
    corpus starts overstating its own coverage, which is the quiet failure this
    project is most exposed to.
    """
    readme = (DEFAULT_CORPUS / "README.md").read_text(encoding="utf-8")
    assert "not advice" in readme
    assert "Habitual Residence Condition is not" in readme


def test_shipped_task_files_parse_as_lists_of_mappings() -> None:
    for path in sorted((DEFAULT_CORPUS / "tasks").glob("*.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, list)
        assert all(isinstance(record, dict) for record in loaded)


# --- retrieving by task rather than by query ---------------------------------


def test_spans_for_returns_the_tasks_asked_for_in_that_order() -> None:
    """A planning turn's answer follows the plan's ordering, so retrieval has to
    preserve the order it was given rather than impose a relevance one."""
    today = date(2026, 8, 18)
    index = Index(load_corpus(DEFAULT_CORPUS, today=today), today=today)

    wanted = ["gp.register", "ppsn.apply", "school.enrol_primary"]
    spans = index.spans_for(wanted)

    assert [s.task_id for s in spans] == wanted


def test_spans_for_gives_one_source_per_task_by_default() -> None:
    """A task with three sources should not push the other tasks out of a
    plan-shaped answer."""
    today = date(2026, 8, 18)
    index = Index(load_corpus(DEFAULT_CORPUS, today=today), today=today)

    spans = index.spans_for(["ppsn.apply"])
    assert len(spans) == 1
    assert index.spans_for(["ppsn.apply"], limit_per_task=5)[0].task_id == "ppsn.apply"


def test_spans_for_skips_a_task_it_has_no_source_for() -> None:
    """Silently returning nothing for an unknown id is right: the alternative is
    an answer that cites a task the corpus cannot support."""
    today = date(2026, 8, 18)
    index = Index(load_corpus(DEFAULT_CORPUS, today=today), today=today)

    assert index.spans_for(["no.such.task"]) == ()
    assert len(index.spans_for(["no.such.task", "ppsn.apply"])) == 1
