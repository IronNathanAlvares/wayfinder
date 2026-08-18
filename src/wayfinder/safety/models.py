"""The data the safety layer matches on, and the verdict it produces.

`reviewed_on` is mandatory on both the lexicon and the directory, and load fails
without it (FR-S10). These are treated like the corpus and more strictly: a
stale helpline number is worse than a stale procedure, because somebody dials it
during an emergency and nobody answers.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wayfinder.safety.taxonomy import Layer, QuestionClass


class CrisisCategory(Enum):
    """The six categories from the design. Each maps to a dated directory entry."""

    ROUGH_SLEEPING = "rough_sleeping"
    VIOLENCE = "violence"
    CHILD_PROTECTION = "child_protection"
    MEDICAL = "medical"
    SELF_HARM = "self_harm"
    DETENTION = "detention"


class CrisisPattern(BaseModel):
    """One phrase that fires a category.

    Matched with word boundaries by default. Without them "kill" fires on
    "skills", and a crisis screen that cries wolf on ordinary sentences trains
    people to ignore it, which costs exactly the lives it exists to protect.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phrase: str = Field(min_length=1)
    regex: bool = False

    def compile(self) -> re.Pattern[str]:
        if self.regex:
            return re.compile(self.phrase)
        return re.compile(rf"(?<!\w){re.escape(self.phrase)}(?!\w)")


class LexiconCategory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: CrisisCategory
    patterns: tuple[CrisisPattern, ...] = Field(min_length=1)


class CrisisLexicon(BaseModel):
    """Reviewed on a schedule, like the directory. Never generated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewed_on: date
    reviewed_by: str = Field(min_length=1)
    categories: tuple[LexiconCategory, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_duplicate_categories(self) -> CrisisLexicon:
        seen = [c.id for c in self.categories]
        if len(set(seen)) != len(seen):
            msg = "a crisis category appears twice in the lexicon"
            raise ValueError(msg)
        return self


class DirectoryEntry(BaseModel):
    """A real service with a real number, verified against its own publisher.

    `hours` is not decoration. The Dublin homeless freephone closes at 10pm, and
    "I have nowhere to sleep tonight" is most often typed after that. Showing a
    number without its hours sends somebody to a phone that will not be answered.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    contact: str = Field(min_length=1)
    hours: str = Field(min_length=1)
    covers: str = ""
    url: str = Field(min_length=1)
    last_verified: date
    verified_by: str = Field(min_length=1)


class DirectorySection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: CrisisCategory
    lead_line: str = Field(min_length=1)
    entries: tuple[DirectoryEntry, ...] = Field(min_length=1)


class CrisisDirectory(BaseModel):
    """Static, dated, and never generated. A model cannot mis-type a number it
    looked up rather than composed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewed_on: date
    reviewed_by: str = Field(min_length=1)
    sections: tuple[DirectorySection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _every_category_is_covered(self) -> CrisisDirectory:
        """A category the lexicon can fire but the directory cannot answer would
        show somebody an empty response during an emergency."""
        covered = {s.category for s in self.sections}
        missing = sorted(c.value for c in CrisisCategory if c not in covered)
        if missing:
            msg = f"the directory has no entries for {missing}"
            raise ValueError(msg)
        return self

    def section(self, category: CrisisCategory) -> DirectorySection:
        for section in self.sections:
            if section.category is category:
                return section
        msg = f"no directory section for {category}"  # pragma: no cover
        raise KeyError(msg)  # pragma: no cover


class CrisisHit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    category: CrisisCategory
    matched: str


class Classification(BaseModel):
    """The verdict, plus enough to reconstruct why.

    `layer` matters as much as `question_class`. A class assigned by the
    tie-break is a different thing from one a deterministic marker was certain
    about, and the eval reports them separately.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_class: QuestionClass
    layer: Layer
    reason: str = ""
    crisis: CrisisHit | None = None

    @model_validator(mode="after")
    def _crisis_is_consistent(self) -> Classification:
        is_crisis = self.question_class is QuestionClass.CRISIS
        if is_crisis and self.crisis is None:
            msg = "a CRISIS classification must carry the hit that caused it"
            raise ValueError(msg)
        if not is_crisis and self.crisis is not None:
            msg = "only a CRISIS classification may carry a crisis hit"
            raise ValueError(msg)
        return self


STALE_AFTER_DAYS: Final = 180
