"""Loading the corpus, and refusing to load a broken one.

Every check here fails the build rather than warning. A corpus that loads with a
warning is a corpus that ships with the warning ignored, and the failure mode is
somebody making a journey they cannot afford on a prerequisite that was wrong.

Problems are collected rather than raised one at a time, because a person
editing YAML wants the whole list, not a game of whack-a-mole.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from wayfinder.corpus.models import Artefact, Corpus, Source
from wayfinder.plan.models import Task
from wayfinder.plan.refs import ArtefactKind, artefact_kind

TASKS_DIR = "tasks"
SOURCES_DIR = "sources"
ARTEFACTS_DIR = "artefacts"


class CorpusError(Exception):
    """The corpus could not be loaded, with every problem found listed."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        listed = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(f"{len(self.problems)} corpus problem(s):\n{listed}")


def _read_records(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every mapping in every YAML file under a directory, with its file for errors."""
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            continue
        if not isinstance(loaded, list):
            msg = f"{path.name}: expected a list of records at the top level"
            raise CorpusError([msg])
        for record in loaded:
            if not isinstance(record, dict):
                msg = f"{path.name}: expected mappings in the list, got {type(record)}"
                raise CorpusError([msg])
            out.append((path, record))
    return out


def load_corpus(root: Path, *, today: date | None = None) -> Corpus:
    """Load and validate a corpus directory.

    `today` is only used to reject a `last_verified` in the future, which is
    always a typo. It is injected rather than read from the clock so that a
    corpus test cannot start failing overnight.
    """
    problems: list[str] = []

    sources = _load_sources(root / SOURCES_DIR, problems, today=today)
    artefacts = _load_artefacts(root / ARTEFACTS_DIR, problems)
    tasks = _load_tasks(root / TASKS_DIR, problems)

    _check_references(tasks, sources, artefacts, problems)

    if problems:
        raise CorpusError(sorted(problems))

    return Corpus(
        tasks=tuple(sorted(tasks, key=lambda t: t.id)),
        sources={s.id: s for s in sources},
        artefacts={a.ref: a for a in artefacts},
    )


def _load_sources(
    directory: Path, problems: list[str], *, today: date | None
) -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()
    for path, record in _read_records(directory):
        try:
            source = Source.model_validate(record)
        except ValidationError as exc:
            problems.append(
                f"{path.name}: source {record.get('id', '?')}: {_brief(exc)}"
            )
            continue
        if source.id in seen:
            problems.append(f"{path.name}: duplicate source id {source.id}")
            continue
        if today is not None and source.last_verified > today:
            problems.append(
                f"{path.name}: source {source.id} has last_verified in the future "
                f"({source.last_verified})"
            )
        seen.add(source.id)
        sources.append(source)
    return sources


def _load_artefacts(directory: Path, problems: list[str]) -> list[Artefact]:
    artefacts: list[Artefact] = []
    seen: set[str] = set()
    for path, record in _read_records(directory):
        try:
            artefact = Artefact.model_validate(record)
        except ValidationError as exc:
            ref = record.get("ref", "?")
            problems.append(f"{path.name}: artefact {ref}: {_brief(exc)}")
            continue
        if artefact.ref in seen:
            problems.append(f"{path.name}: duplicate artefact {artefact.ref}")
            continue
        seen.add(artefact.ref)
        artefacts.append(artefact)
    return artefacts


def _load_tasks(directory: Path, problems: list[str]) -> list[Task]:
    tasks: list[Task] = []
    seen: set[str] = set()
    for path, record in _read_records(directory):
        try:
            task = Task.model_validate(record)
        except ValidationError as exc:
            problems.append(f"{path.name}: task {record.get('id', '?')}: {_brief(exc)}")
            continue
        if task.id in seen:
            problems.append(f"{path.name}: duplicate task id {task.id}")
            continue
        seen.add(task.id)
        tasks.append(task)
    return tasks


def _check_references(
    tasks: Iterable[Task],
    sources: Iterable[Source],
    artefacts: Iterable[Artefact],
    problems: list[str],
) -> None:
    known_sources = {s.id for s in sources}
    known_artefacts = {a.ref for a in artefacts}

    for task in tasks:
        for span in task.where:
            if span.source_id not in known_sources:
                problems.append(f"task {task.id} cites unknown source {span.source_id}")

        referenced = [
            ref for requirement in task.requires for ref in requirement.any_of
        ]
        for ref in [*referenced, *task.produces]:
            # elapsed: refs name a situation field rather than a corpus artefact,
            # so they have nothing to declare.
            if artefact_kind(ref) is ArtefactKind.ELAPSED:
                continue
            if artefact_kind(ref) is ArtefactKind.TASK:
                continue
            if ref not in known_artefacts:
                problems.append(f"task {task.id} references undeclared artefact {ref}")

        for requirement in task.requires:
            for ref in requirement.any_of:
                if artefact_kind(ref) is not ArtefactKind.TASK:
                    continue
                target = ref.split(":", 1)[1]
                if target not in {t.id for t in tasks}:
                    problems.append(f"task {task.id} requires unknown task {target}")


def _brief(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
    )
