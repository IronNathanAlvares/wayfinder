"""Sources, artefacts and the corpus that holds them.

`last_verified` is mandatory. An undated source is indistinguishable from a
stale one, and in this domain a page last reviewed two years ago looks exactly
like one updated last week. There is no default and no fallback, so a source
without a date fails the build rather than quietly becoming the oldest thing in
the corpus.

Artefacts are declared rather than inferred. The most likely corpus bug is a
typo in a reference, `document:pps_number` against `document:ppsn`, which
without a declared vocabulary produces a task that silently never links to
anything. Declaring them turns that into a load failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wayfinder.plan.models import Task
from wayfinder.plan.refs import ArtefactKind, ArtefactRef, artefact_kind


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    url: str = Field(min_length=1)
    last_verified: date
    verified_by: str = Field(min_length=1)
    language: str = "en"

    # `last_verified` is the day this project read the page. It is not the day
    # the publisher last reviewed it, and the two can be a year apart: a page
    # checked today and edited in 2025 is a different thing from one edited last
    # week, and only the publisher's date says which. Where the page states its
    # own, it goes here. The sources file has claimed this field exists since
    # the corpus was written; it did not until now.
    note: str = ""


class Artefact(BaseModel):
    """A document, status or determination the corpus knows how to talk about."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ArtefactRef
    title: str = Field(min_length=1)
    note: str = ""
    decided_by: str = ""

    @model_validator(mode="after")
    def _determinations_name_an_authority(self) -> Artefact:
        """A determination must name who decides it, and nothing else may.

        The output people need is "this is decided by *that* authority, here is
        how it is applied for". That sentence is only writable if the corpus
        carries the authority, so it is required here rather than hoped for at
        composition time.
        """
        is_determination = artefact_kind(self.ref) is ArtefactKind.DETERMINATION
        if is_determination and not self.decided_by:
            msg = f"{self.ref} is a determination and must name `decided_by`"
            raise ValueError(msg)
        if not is_determination and self.decided_by:
            msg = f"{self.ref} is not a determination, so `decided_by` does not apply"
            raise ValueError(msg)
        return self


class StalenessBand(Enum):
    """How much a source's age should change what we are willing to say from it."""

    NORMAL = "normal"
    VERIFY = "verify"
    DOWNGRADE = "downgrade"
    EXCLUDED = "excluded"


_BANDS: Sequence[tuple[int, StalenessBand]] = (
    (90, StalenessBand.NORMAL),
    (180, StalenessBand.VERIFY),
    (365, StalenessBand.DOWNGRADE),
)


def staleness(source: Source, *, today: date) -> StalenessBand:
    age = today - source.last_verified
    for days, band in _BANDS:
        if age < timedelta(days=days):
            return band
    return StalenessBand.EXCLUDED


class Corpus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tasks: tuple[Task, ...]
    sources: Mapping[str, Source]
    artefacts: Mapping[ArtefactRef, Artefact]

    def source_for(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def artefact(self, ref: str) -> Artefact | None:
        return self.artefacts.get(ref)

    def health(self, *, today: date) -> Mapping[StalenessBand, tuple[str, ...]]:
        """Source ids grouped by staleness band. The corpus maintenance alarm."""
        grouped: dict[StalenessBand, list[str]] = {b: [] for b in StalenessBand}
        for source in self.sources.values():
            grouped[staleness(source, today=today)].append(source.id)
        return {band: tuple(sorted(ids)) for band, ids in grouped.items()}
