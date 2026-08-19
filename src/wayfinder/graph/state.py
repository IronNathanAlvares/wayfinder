"""Everything the graph carries. Personal data lives here and only here.

Three notes on the shape.

`trace` is not debugging. It is the record of why a turn was classified and
answered the way it was, and it is what somebody reviewing a bad answer reads.
Requirement NFR-6 says every turn must be reconstructable from it.

`human_determination` is its own type rather than a string, so composition can
attribute it to the person who made it and can never restate it as system
knowledge. Laundering a caseworker's judgement into the system's voice destroys
the audit trail that makes the handoff worth having.

Everything except `messages` and `trace` is replaced per turn. Retrieval from an
earlier question leaking into a later answer is a citation bug waiting to
happen.
"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from wayfinder.plan.plan import Plan
from wayfinder.plan.situation import Situation
from wayfinder.retrieval.index import RetrievedSpan
from wayfinder.safety.models import Classification, CrisisHit
from wayfinder.safety.taxonomy import QuestionClass


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    text: str


class HumanDetermination(BaseModel):
    """A caseworker's answer, with the caseworker named.

    `answered_by` is mandatory and non-empty. A determination with nobody's name
    on it is exactly what this system exists to avoid producing, and it should
    not be able to enter state through the resume path either.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1)
    answered_by: str = Field(min_length=1)
    answered_on: date
    source: str = ""


class TraceEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node: str
    detail: str
    at: datetime


class Answer(BaseModel):
    """Composed text plus the spans it rests on.

    An `Answer` with claims and no citations cannot be constructed. That is
    enforced in `compose/verify.py` by type rather than by review.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    citations: tuple[RetrievedSpan, ...] = ()
    needs_verifying: bool = False
    attributed_to: str = ""


class WayfinderState(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # conversation
    messages: Annotated[list[Turn], operator.add] = Field(default_factory=list)
    current_question: str = ""
    question_class: QuestionClass | None = None
    classification: Classification | None = None
    crisis: CrisisHit | None = None

    # situation, built incrementally by intake
    situation: Situation = Field(default_factory=Situation)
    open_questions: tuple[str, ...] = ()

    # planning
    plan: Plan | None = None

    # retrieval
    active_domain: str | None = None
    retrieved: tuple[RetrievedSpan, ...] = ()
    stale_sources: tuple[str, ...] = ()

    # human in the loop
    handoff_reason: str = ""
    human_determination: HumanDetermination | None = None

    # output
    answer: Answer | None = None

    # audit. every turn must be reconstructable
    trace: Annotated[list[TraceEvent], operator.add] = Field(default_factory=list)

    # injected rather than read from a clock, so a run is reproducible
    today: date = Field(default_factory=date.today)

    def traced(self, node: str, detail: str) -> list[TraceEvent]:
        return [TraceEvent(node=node, detail=detail, at=datetime.now(tz=UTC))]


def summarise_for_caseworker(
    situation: Situation, question: str, spans: Sequence[RetrievedSpan]
) -> str:
    """What travels with an escalation.

    Deliberately small. NFR-5 says escalations carry the minimum a caseworker
    needs, reviewed field by field, and a queue item that arrives with somebody's
    whole file attached is a privacy problem dressed as helpfulness.
    """
    lines = [f"Question: {question}", ""]
    if situation.protection_stage:
        lines.append(f"Protection stage: {situation.protection_stage.value}")
    if situation.protection_application_date:
        lines.append(f"Applied on: {situation.protection_application_date}")
    if situation.accommodation:
        lines.append(f"Accommodation: {situation.accommodation.value}")
    if situation.household:
        children = len(situation.household.children_ages)
        lines.append(
            f"Household: {situation.household.adults} adult(s), {children} child(ren)"
        )
    if situation.held:
        lines.append(f"Holds: {', '.join(sorted(situation.held))}")
    if spans:
        lines += ["", "Sources already found:"]
        lines += [
            f"  {s.source_title} ({s.url}), verified {s.last_verified}" for s in spans
        ]
    return "\n".join(lines)
