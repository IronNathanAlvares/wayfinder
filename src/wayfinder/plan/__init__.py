"""The plan engine. Pure Python: no I/O, no framework, no model.

That purity is enforced by an import-linter contract rather than described,
because the claim decays the first time somebody needs "just one" import.
"""

from wayfinder.plan.builder import build_plan
from wayfinder.plan.conditions import Condition, parse_condition
from wayfinder.plan.diff import PlanDiff, diff_plans
from wayfinder.plan.errors import CycleError, PlanError, SearchExhaustedError
from wayfinder.plan.models import Domain, Prerequisite, Severity, SourceSpan, Task
from wayfinder.plan.plan import ItemStatus, Plan, PlanItem
from wayfinder.plan.refs import ArtefactKind, ArtefactRef, TaskId, artefact_kind
from wayfinder.plan.situation import (
    Accommodation,
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)
from wayfinder.plan.truth import Truth

__all__ = [
    "Accommodation",
    "ArtefactKind",
    "ArtefactRef",
    "Condition",
    "CycleError",
    "DeterminationOutcome",
    "DeterminationRecord",
    "Domain",
    "Household",
    "ItemStatus",
    "Plan",
    "PlanDiff",
    "PlanError",
    "PlanItem",
    "Prerequisite",
    "ProtectionStage",
    "SearchExhaustedError",
    "Severity",
    "Situation",
    "SourceSpan",
    "Task",
    "TaskId",
    "Truth",
    "artefact_kind",
    "build_plan",
    "diff_plans",
    "parse_condition",
]
