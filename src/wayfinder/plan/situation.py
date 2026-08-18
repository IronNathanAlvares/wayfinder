"""What we know about a person, including what we know we do not know.

Two things here are load-bearing.

`held` and `known_absent` are separate sets rather than one set plus an
absence rule. Anything in neither is genuinely UNKNOWN, which is what lets the
planner say "I cannot place this task until you tell me X" instead of assuming.
It is also what makes "ask only the questions that change the plan" computable
rather than guessed.

`determinations` can only hold a record that names the authority who decided.
The planner has no code path that writes to it, and no record can be
constructed without an attributed decider. That is requirement FR-S9 expressed
as a type rather than as a comment.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wayfinder.plan.refs import ArtefactKind, ArtefactRef, TaskId, artefact_kind
from wayfinder.plan.truth import Truth


class ProtectionStage(Enum):
    PRE_APPLICATION = "pre_application"
    APPLIED = "applied"
    APPEAL = "appeal"
    GRANTED = "granted"
    REFUSED = "refused"
    NOT_APPLICABLE = "not_applicable"


class Accommodation(Enum):
    IPAS = "ipas"
    EMERGENCY = "emergency"
    PRIVATE = "private"
    STAYING_WITH_OTHERS = "staying_with_others"
    HOMELESS = "homeless"


class DeterminationOutcome(Enum):
    GRANTED = "granted"
    REFUSED = "refused"
    PENDING = "pending"


class Household(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    adults: int = Field(ge=0)
    children_ages: tuple[int, ...] = ()


class DeterminationRecord(BaseModel):
    """An outcome decided by somebody, recorded from outside this system.

    `authority` is mandatory and non-empty so that a determination cannot exist
    in state without a named decider. There is deliberately no default: the
    system cannot record one of these without explicitly naming who decided,
    which it has no way to do honestly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: DeterminationOutcome
    authority: str = Field(min_length=1)
    recorded_on: date
    note: str = ""


class Situation(BaseModel):
    """Everything the planner is allowed to reason from.

    Every field is optional because intake asks for a field only when it changes
    the plan. Somebody in distress should not face twenty questions before
    getting anything useful.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arrival_date: date | None = None

    # Distinct from arrival_date on purpose. Waiting periods in this domain run
    # from the day the application was made, and somebody can arrive weeks
    # before they apply. Collapsing the two would produce a date that is wrong
    # in the direction that costs somebody an entitlement.
    protection_application_date: date | None = None

    protection_stage: ProtectionStage | None = None
    accommodation: Accommodation | None = None
    household: Household | None = None

    held: frozenset[ArtefactRef] = frozenset()
    known_absent: frozenset[ArtefactRef] = frozenset()
    tasks_completed: frozenset[TaskId] = frozenset()
    determinations: Mapping[ArtefactRef, DeterminationRecord] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def _check_artefact_sets(self) -> Situation:
        holdable = {ArtefactKind.DOCUMENT, ArtefactKind.STATUS}
        for name, refs in (("held", self.held), ("known_absent", self.known_absent)):
            wrong = [r for r in refs if artefact_kind(r) not in holdable]
            if wrong:
                msg = (
                    f"{name} may only contain document: or status: references, got {wrong}. "
                    "Determinations belong in `determinations`, which requires a named authority."
                )
                raise ValueError(msg)

        both = self.held & self.known_absent
        if both:
            msg = f"cannot be both held and known absent: {sorted(both)}"
            raise ValueError(msg)

        wrong_keys = [
            r
            for r in self.determinations
            if artefact_kind(r) is not ArtefactKind.DETERMINATION
        ]
        if wrong_keys:
            msg = f"determinations keys must be determination: references, got {wrong_keys}"
            raise ValueError(msg)
        return self

    def holds(self, ref: str) -> Truth:
        """Whether the person has this artefact, three-valued.

        Documents and statuses are UNKNOWN unless we have been told either way.
        Task completion is not: a task we have not been told about is not done.
        """
        kind = artefact_kind(ref)

        if kind is ArtefactKind.DETERMINATION:
            record = self.determinations.get(ref)
            if record is None or record.outcome is DeterminationOutcome.PENDING:
                return Truth.UNKNOWN
            return (
                Truth.TRUE
                if record.outcome is DeterminationOutcome.GRANTED
                else Truth.FALSE
            )

        if kind is ArtefactKind.TASK:
            task_id = ref.split(":", 1)[1]
            return Truth.TRUE if task_id in self.tasks_completed else Truth.FALSE

        if kind is ArtefactKind.ELAPSED:
            msg = (
                f"{ref!r} is a waiting period, not something a person holds. "
                "Elapsed prerequisites are evaluated against a date, not a set."
            )
            raise ValueError(msg)

        if ref in self.held:
            return Truth.TRUE
        if ref in self.known_absent:
            return Truth.FALSE
        return Truth.UNKNOWN
