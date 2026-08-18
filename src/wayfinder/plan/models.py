"""The task model: what a task is, what it needs, and what it yields.

`produces` is what makes the graph resolvable. A task is not just a step, it
yields artefacts, so prerequisites are declared against artefacts rather than
hard-wired to task ids. Adding a second route to the same document links every
dependent automatically instead of requiring a rewiring pass.

`requires` is an AND of ORs. Each `Prerequisite` is one requirement which may be
met by any one of several artefacts. The original design expressed alternatives
with a flat `optional: true` flag, which cannot say *which* alternatives belong
together, and the minimal unblocking computation needs exactly that.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from enum import Enum
from typing import Annotated, Final

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from wayfinder.plan.conditions import ALWAYS, Condition
from wayfinder.plan.refs import (
    ArtefactKind,
    ArtefactRef,
    TaskId,
    artefact_kind,
    artefact_name,
    task_artefact,
)
from wayfinder.plan.situation import Situation
from wayfinder.plan.truth import Truth, disjunction


class Domain(Enum):
    STATUS = "status"
    ACCOMMODATION = "accommodation"
    INCOME = "income"
    HEALTH = "health"
    EDUCATION = "education"
    BANKING = "banking"


class Severity(Enum):
    """How much it costs to have this task blocked.

    The rank orders ties in the topological sort. Lower sorts first.
    """

    CRITICAL = "critical"
    IMPORTANT = "important"
    ROUTINE = "routine"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: Final[Mapping[Severity, int]] = {
    Severity.CRITICAL: 0,
    Severity.IMPORTANT: 1,
    Severity.ROUTINE: 2,
}


class SourceSpan(BaseModel):
    """A pointer into the source corpus. The loader resolves it to a dated source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    span: str = Field(min_length=1)


def _normalise_prerequisite(raw: object) -> object:
    """Accept a bare artefact reference as shorthand for a one-option requirement."""
    if isinstance(raw, str):
        return {"any_of": (raw,)}
    if isinstance(raw, Mapping) and "ref" in raw:
        rest = {k: v for k, v in raw.items() if k != "ref"}
        return {"any_of": (raw["ref"],), **rest}
    return raw


class Prerequisite(BaseModel):
    """One reason a task cannot start yet, satisfied by any one of `any_of`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    any_of: tuple[ArtefactRef, ...] = Field(min_length=1)
    after: timedelta | None = None
    note: str = ""

    @model_validator(mode="after")
    def _elapsed_needs_a_duration(self) -> Prerequisite:
        has_elapsed = any(artefact_kind(r) is ArtefactKind.ELAPSED for r in self.any_of)
        if has_elapsed and self.after is None:
            msg = f"elapsed prerequisite {self.any_of} needs an `after` duration"
            raise ValueError(msg)
        if self.after is not None and not has_elapsed:
            msg = "`after` only means something alongside an elapsed: reference"
            raise ValueError(msg)
        return self

    @property
    def blocked_on_determination(self) -> bool:
        """True when every route through this requirement runs through an authority.

        If even one option is clearable by the person, the requirement is not a
        determination wall, and the plan should say so.
        """
        return all(artefact_kind(r) is ArtefactKind.DETERMINATION for r in self.any_of)

    def satisfied(self, situation: Situation, *, today: date) -> Truth:
        return disjunction(
            self._option_satisfied(ref, situation, today=today) for ref in self.any_of
        )

    def _option_satisfied(
        self, ref: str, situation: Situation, *, today: date
    ) -> Truth:
        if artefact_kind(ref) is not ArtefactKind.ELAPSED:
            return situation.holds(ref)

        # elapsed:<field> means "this long since the date in that situation field".
        anchor_field = artefact_name(ref)
        anchor = getattr(situation, anchor_field, None)
        if not isinstance(anchor, date):
            return Truth.UNKNOWN
        assert self.after is not None  # guaranteed by the validator above
        return Truth.TRUE if today - anchor >= self.after else Truth.FALSE

    def unknowns(self, situation: Situation, *, today: date) -> frozenset[str]:
        """Facts we could learn by asking, which would change this verdict.

        A determination with no record is never one of them. "Do you satisfy the
        residence test?" is precisely the question this system must not put to
        somebody, and listing it as an open question would invite exactly that:
        an answer supplied by the person, or by a model, standing in for a
        decision only an authority can make. An undecided determination is a
        blocker to be named, not a gap to be filled. See ADR-0004.
        """
        if self.satisfied(situation, today=today) is not Truth.UNKNOWN:
            return frozenset()
        out: set[str] = set()
        for ref in self.any_of:
            kind = artefact_kind(ref)
            if kind is ArtefactKind.DETERMINATION:
                continue
            if kind is ArtefactKind.ELAPSED:
                if getattr(situation, artefact_name(ref), None) is None:
                    out.add(artefact_name(ref))
            elif situation.holds(ref) is Truth.UNKNOWN:
                out.add(ref)
        return frozenset(out)


class Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: TaskId
    title: str = Field(min_length=1)
    domain: Domain
    why: str = Field(min_length=1)
    requires: tuple[
        Annotated[Prerequisite, BeforeValidator(_normalise_prerequisite)], ...
    ] = ()
    produces: tuple[ArtefactRef, ...] = ()
    applies_when: Condition = ALWAYS
    where: tuple[SourceSpan, ...] = Field(min_length=1)
    typical_wait: timedelta | None = None
    blocking_severity: Severity

    @model_validator(mode="after")
    def _produces_nothing_an_authority_owns(self) -> Task:
        """A task cannot produce a determination or a waiting period.

        This is ADR-0004 pushed down into the corpus. If a contributor could
        write `produces: [determination:habitual_residence]`, the planner would
        happily mark a legal determination as satisfied by somebody filling in a
        form, which is exactly the claim this system must never make.
        """
        forbidden = {
            r: artefact_kind(r)
            for r in self.produces
            if artefact_kind(r)
            in {ArtefactKind.DETERMINATION, ArtefactKind.ELAPSED, ArtefactKind.TASK}
        }
        if forbidden:
            msg = (
                f"task {self.id} claims to produce {sorted(forbidden)}. "
                "Determinations are made by authorities, elapsed time passes on its own, "
                "and task: artefacts are implicit."
            )
            raise ValueError(msg)
        return self

    @property
    def yields(self) -> frozenset[str]:
        """Everything completing this task satisfies, including its own task reference."""
        return frozenset(self.produces) | {task_artefact(self.id)}

    def applies(self, situation: Situation) -> Truth:
        return self.applies_when.evaluate(situation)


__all__: Final = [
    "Domain",
    "Prerequisite",
    "Severity",
    "SourceSpan",
    "Task",
]
