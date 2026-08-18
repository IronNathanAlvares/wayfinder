"""Loading the lexicon and the directory, and refusing to load stale ones.

The staleness rule here is stricter than the corpus rule, and deliberately so.
A stale procedure wastes somebody a journey. A stale helpline number is dialled
during an emergency by somebody who then hears nothing, and there is no version
of that which is acceptable. Past the review window this raises rather than
downgrades.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from wayfinder.safety.models import STALE_AFTER_DAYS, CrisisDirectory, CrisisLexicon

DATA = Path(__file__).resolve().parent / "data"
LEXICON_FILE = "crisis_lexicon.yaml"
DIRECTORY_FILE = "directory.yaml"


class SafetyDataError(Exception):
    """The safety data could not be loaded, or is too old to be trusted."""


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        msg = f"safety data not found: {path}"
        raise SafetyDataError(msg)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"{path.name}: expected a mapping at the top level"
        raise SafetyDataError(msg)
    return loaded


def _check_age(what: str, reviewed_on: date, today: date | None) -> None:
    if today is None:
        return
    if reviewed_on > today:
        msg = f"{what} was reviewed in the future ({reviewed_on}), which is a typo"
        raise SafetyDataError(msg)
    age = today - reviewed_on
    if age > timedelta(days=STALE_AFTER_DAYS):
        msg = (
            f"{what} was last reviewed {reviewed_on}, which is more than "
            f"{STALE_AFTER_DAYS} days ago. This is an operational alarm, not a "
            "warning: somebody dials these numbers during an emergency."
        )
        raise SafetyDataError(msg)


def load_lexicon(
    root: Path | None = None, *, today: date | None = None
) -> CrisisLexicon:
    path = (root or DATA) / LEXICON_FILE
    try:
        lexicon = CrisisLexicon.model_validate(_read(path))
    except ValidationError as exc:
        msg = f"{path.name}: {exc}"
        raise SafetyDataError(msg) from exc
    _check_age("the crisis lexicon", lexicon.reviewed_on, today)
    return lexicon


def load_directory(
    root: Path | None = None, *, today: date | None = None
) -> CrisisDirectory:
    path = (root or DATA) / DIRECTORY_FILE
    try:
        directory = CrisisDirectory.model_validate(_read(path))
    except ValidationError as exc:
        msg = f"{path.name}: {exc}"
        raise SafetyDataError(msg) from exc
    _check_age("the crisis services directory", directory.reviewed_on, today)

    stale = [
        e.id
        for s in directory.sections
        for e in s.entries
        if today is not None
        and today - e.last_verified > timedelta(days=STALE_AFTER_DAYS)
    ]
    if stale:
        msg = (
            f"these directory entries have not been verified in "
            f"{STALE_AFTER_DAYS} days: {sorted(set(stale))}"
        )
        raise SafetyDataError(msg)
    return directory
