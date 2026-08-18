"""The paths that only run when something is wrong.

These are the ones worth testing hardest. Everything in this engine is built to
fail loudly on bad data, and a failure path that has never run is a failure path
that does not work.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from wayfinder.cli.render import render_plan
from wayfinder.corpus.loader import CorpusError, load_corpus
from wayfinder.corpus.models import Corpus
from wayfinder.plan.builder import build_plan
from wayfinder.plan.models import Domain, Prerequisite, Severity, SourceSpan, Task
from wayfinder.plan.plan import ItemStatus, Plan, PlanItem
from wayfinder.plan.refs import artefact_kind, artefact_name
from wayfinder.plan.situation import Situation

# --- corpus loading ---------------------------------------------------------


def _corpus_dir(tmp_path: Path, **files: str) -> Path:
    for name in ("tasks", "sources", "artefacts"):
        (tmp_path / name).mkdir()
    for relative, content in files.items():
        target = tmp_path / f"{relative.replace('__', '/')}.yaml"
        target.write_text(content, encoding="utf-8")
    return tmp_path


def test_a_yaml_file_that_is_not_a_list_is_rejected(tmp_path: Path) -> None:
    root = _corpus_dir(tmp_path, sources__s="id: not-a-list")
    with pytest.raises(CorpusError, match="expected a list"):
        load_corpus(root)


def test_a_yaml_list_of_non_mappings_is_rejected(tmp_path: Path) -> None:
    root = _corpus_dir(tmp_path, sources__s="- just a string\n- another")
    with pytest.raises(CorpusError, match="expected mappings"):
        load_corpus(root)


def test_an_empty_yaml_file_is_skipped_rather_than_failing(tmp_path: Path) -> None:
    """An empty file is a file somebody has not written yet, not a broken one."""
    root = _corpus_dir(tmp_path, sources__s="", tasks__t="", artefacts__a="")
    corpus = load_corpus(root)
    assert corpus.tasks == ()


def test_duplicate_ids_are_reported(tmp_path: Path) -> None:
    source = (
        "- id: dup\n"
        "  title: t\n"
        "  publisher: p\n"
        "  url: https://example.invalid/x\n"
        "  last_verified: 2026-08-01\n"
        "  verified_by: test\n"
    )
    root = _corpus_dir(
        tmp_path,
        sources__s=source * 2,
        artefacts__a="- ref: document:x\n  title: x\n- ref: document:x\n  title: x\n",
    )
    with pytest.raises(CorpusError) as caught:
        load_corpus(root)
    joined = "\n".join(caught.value.problems)
    assert "duplicate source id dup" in joined
    assert "duplicate artefact document:x" in joined


def test_a_task_requiring_an_unknown_task_is_reported(tmp_path: Path) -> None:
    root = _corpus_dir(
        tmp_path,
        sources__s=(
            "- id: s\n  title: t\n  publisher: p\n"
            "  url: https://example.invalid/x\n"
            "  last_verified: 2026-08-01\n  verified_by: test\n"
        ),
        tasks__t=(
            "- id: a.task\n  title: T\n  domain: status\n  why: W\n"
            "  requires: [task:no.such_task]\n"
            "  blocking_severity: routine\n"
            "  where:\n    - source_id: s\n      span: x\n"
        ),
    )
    with pytest.raises(CorpusError, match="requires unknown task"):
        load_corpus(root)


def test_a_missing_corpus_directory_raises_rather_than_loading_nothing(
    tmp_path: Path,
) -> None:
    """A mistyped path used to report "0 tasks. No integrity problems."

    Which is the worst available answer, because it looks like success. The CLI
    reports this as could-not-evaluate rather than as a failing verdict.
    """
    with pytest.raises(NotADirectoryError, match="corpus directory not found"):
        load_corpus(tmp_path / "does_not_exist")


# --- references -------------------------------------------------------------


def test_a_malformed_artefact_reference_is_rejected() -> None:
    with pytest.raises(ValueError, match="malformed artefact reference"):
        artefact_kind("not-a-reference")


def test_artefact_name_strips_the_prefix() -> None:
    assert artefact_name("document:ppsn") == "ppsn"


def test_an_unknown_prefix_is_not_a_valid_reference() -> None:
    with pytest.raises(ValueError, match="malformed"):
        artefact_kind("invented:thing")


# --- prerequisites ----------------------------------------------------------


def test_an_elapsed_prerequisite_without_a_duration_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs an `after` duration"):
        Prerequisite(any_of=("elapsed:arrival_date",))


def test_a_duration_without_an_elapsed_reference_is_rejected() -> None:
    """Two ways to say the same thing is one way to say the wrong thing."""
    with pytest.raises(ValidationError, match="only means something alongside"):
        Prerequisite(any_of=("document:x",), after=timedelta(days=1))


def test_an_elapsed_prerequisite_with_no_anchor_date_is_unknown() -> None:
    """Not false. Nobody has said when they arrived, so nobody knows."""
    requirement = Prerequisite(
        any_of=("elapsed:arrival_date",), after=timedelta(days=10)
    )
    from wayfinder.plan.truth import Truth

    assert requirement.satisfied(Situation(), today=date(2026, 8, 17)) is Truth.UNKNOWN
    assert requirement.unknowns(Situation(), today=date(2026, 8, 17)) == frozenset(
        {"arrival_date"}
    )


def test_a_prerequisite_needs_at_least_one_option() -> None:
    with pytest.raises(ValidationError):
        Prerequisite(any_of=())


def test_a_task_needs_at_least_one_citation() -> None:
    """A task with no source is a claim with no source."""
    with pytest.raises(ValidationError):
        Task(
            id="a.task",
            title="T",
            domain=Domain.STATUS,
            why="W",
            blocking_severity=Severity.ROUTINE,
            where=(),
        )


def test_an_elapsed_reference_cannot_be_asked_about_as_a_holding() -> None:
    with pytest.raises(ValueError, match="not something a person holds"):
        Situation().holds("elapsed:arrival_date")


# --- plan invariants --------------------------------------------------------


def _item(task_id: str, status: ItemStatus) -> PlanItem:
    return PlanItem(
        task=Task(
            id=task_id,
            title="T",
            domain=Domain.STATUS,
            why="W",
            blocking_severity=Severity.ROUTINE,
            where=(SourceSpan(source_id="s", span="x"),),
        ),
        status=status,
    )


def test_a_plan_cannot_rank_a_task_that_is_not_startable() -> None:
    with pytest.raises(ValidationError, match="does not match the frontier"):
        Plan(
            built_on=date(2026, 8, 17),
            items=(_item("a.one", ItemStatus.BLOCKED),),
            frontier_order=("a.one",),
        )


def test_a_plan_cannot_leave_a_startable_task_unranked() -> None:
    """Silently falling back to unranked order would hide the bug that matters:
    somebody being told to do the wrong thing first."""
    with pytest.raises(ValidationError, match="does not match the frontier"):
        Plan(
            built_on=date(2026, 8, 17),
            items=(_item("a.one", ItemStatus.FRONTIER),),
            frontier_order=(),
        )


def test_a_plan_cannot_rank_the_same_task_twice() -> None:
    with pytest.raises(ValidationError, match="repeats a task"):
        Plan(
            built_on=date(2026, 8, 17),
            items=(_item("a.one", ItemStatus.FRONTIER),),
            frontier_order=("a.one", "a.one"),
        )


def test_an_empty_plan_is_valid() -> None:
    assert Plan(built_on=date(2026, 8, 17), items=()).frontier == ()


# --- rendering --------------------------------------------------------------


def test_an_empty_plan_says_so_rather_than_printing_nothing(
    corpus: Corpus, today: date
) -> None:
    """Silence would read as a failure. It is a real answer and it says so."""
    text = render_plan(Plan(built_on=today, items=()), corpus, Situation())
    assert "Nothing in this corpus applies" in text


def test_an_unknown_situation_renders_as_questions(corpus: Corpus, today: date) -> None:
    plan = build_plan(corpus.tasks, Situation(), today=today)
    text = render_plan(plan, corpus, Situation())
    assert "I need to ask you a few things first" in text
    assert "Do you have" in text
    assert "What is your" in text


def test_completed_tasks_are_shown_as_already_done(corpus: Corpus, today: date) -> None:
    situation = Situation(tasks_completed=frozenset({"clinic.register"}))
    plan = build_plan(corpus.tasks, situation, today=today)
    text = render_plan(plan, corpus, situation)
    assert "Already done" in text
    assert "Register with a clinic" in text


def test_a_waiting_period_with_no_anchor_still_reads_sensibly(
    corpus: Corpus, today: date
) -> None:
    """Somebody who has not given an arrival date should not see a broken date."""
    situation = Situation(
        held=frozenset({"document:identity", "document:permit"}),
        known_absent=frozenset({"document:address_proof", "document:shelter_letter"}),
    )
    plan = build_plan(corpus.tasks, situation, today=today)
    text = render_plan(plan, corpus, situation)
    assert "None" not in text
    assert "1970" not in text


def test_an_undeclared_artefact_still_renders_a_readable_name(
    corpus: Corpus, today: date
) -> None:
    """The loader stops this reaching production, so this is belt and braces:
    a rendering crash is a worse failure than a slightly plain noun."""
    from wayfinder.cli.render import _title

    assert _title(corpus, "document:never_declared") == "never declared"


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, "no waiting time"),
        (3, "about 3 days"),
        (21, "about 3 weeks"),
        (120, "about 4 months"),
    ],
)
def test_waiting_times_are_rounded_to_something_a_person_reads(
    days: int, expected: str
) -> None:
    """Nobody plans in units of 120 days."""
    from wayfinder.cli.render import _humanise

    assert _humanise(timedelta(days=days)) == expected


def test_a_malformed_child_aged_condition_is_rejected() -> None:
    from wayfinder.plan.conditions import parse_condition

    with pytest.raises(ValueError, match="expects a mapping"):
        parse_condition({"child_aged": 5})


def test_a_field_in_condition_needs_a_list() -> None:
    from wayfinder.plan.conditions import parse_condition

    with pytest.raises(ValueError, match="expects a list"):
        parse_condition({"field": "accommodation", "in": "ipas"})


def test_an_uninterpretable_condition_is_rejected() -> None:
    from wayfinder.plan.conditions import parse_condition

    with pytest.raises(ValueError, match="unrecognised keys"):
        parse_condition({"whenever": True})
