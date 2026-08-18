"""Twelve reference personas, asserted exactly.

These are the regression suite for the plan engine. They run against the
synthetic fixture corpus rather than the real one, deliberately: curating real
content in M2 must not be able to break M1's tests, and a change in the engine
must not be maskable by a change in the content.

Each persona names the property it exists to pin down. A persona that does not
distinguish this engine from a simpler one is not earning its place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from wayfinder.plan.refs import TaskId
from wayfinder.plan.situation import (
    Accommodation,
    DeterminationOutcome,
    DeterminationRecord,
    Household,
    ProtectionStage,
    Situation,
)

# Everything most people arrive without. Spelling it out is the point: the
# engine treats "not stated" as unknown, so a persona has to say what is absent
# rather than letting silence stand in for a fact.
NOTHING_YET = frozenset(
    {
        "document:permit",
        "document:card",
        "document:address_proof",
        "document:shelter_letter",
        "document:tenancy",
        "status:banked",
        "status:work_allowed",
    }
)

ARRIVED = date(2026, 8, 3)
LONG_AGO = date(2025, 1, 6)


@dataclass(frozen=True)
class Persona:
    name: str
    pins_down: str
    situation: Situation
    frontier: tuple[TaskId, ...]
    blocked: frozenset[TaskId] = frozenset()
    needs_info: frozenset[TaskId] = frozenset()
    done: frozenset[TaskId] = frozenset()
    absent: frozenset[TaskId] = frozenset()
    routes: dict[TaskId, tuple[TaskId, ...]] = field(default_factory=dict)
    unroutable: dict[TaskId, tuple[str, ...]] = field(default_factory=dict)
    open_questions: frozenset[str] | None = None


PERSONAS: tuple[Persona, ...] = (
    Persona(
        name="week_one_in_a_shelter",
        pins_down=(
            "The headline case. The shorter of two alternative routes is chosen, "
            "and the frontier is ordered by gated calendar time rather than by "
            "how many tasks each one unblocks."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=(7,)),
            held=frozenset({"document:identity"}),
            known_absent=NOTHING_YET,
        ),
        frontier=("shelter.letter_request", "language.enrol", "clinic.register"),
        blocked=frozenset(
            {
                "address.evidence",
                "permit.apply",
                "card.apply",
                "bank.open",
                "school.enrol",
                "work.apply",
                "benefit.apply",
            }
        ),
        absent=frozenset({"tenancy.obtain", "id.replace"}),
        routes={
            # The minimality claim. The long route through address.evidence also
            # works, and a naive ancestor closure would report it as well.
            "permit.apply": ("shelter.letter_request",),
            "address.evidence": ("shelter.letter_request",),
            "card.apply": ("permit.apply", "shelter.letter_request"),
            "school.enrol": ("address.evidence", "shelter.letter_request"),
            "bank.open": (
                "address.evidence",
                "permit.apply",
                "shelter.letter_request",
            ),
            "benefit.apply": ("permit.apply", "shelter.letter_request"),
            "work.apply": ("permit.apply", "shelter.letter_request"),
        },
        unroutable={
            "benefit.apply": ("determination:residence_test",),
            "work.apply": ("elapsed:arrival_date",),
        },
    ),
    Persona(
        name="private_tenancy",
        pins_down=(
            "applies_when removes the shelter route entirely, so the only way to "
            "an address proof is the tenancy, and the plan says so."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.PRIVATE,
            household=Household(adults=2, children_ages=()),
            held=frozenset({"document:identity"}),
            known_absent=NOTHING_YET,
        ),
        frontier=("tenancy.obtain", "language.enrol", "clinic.register"),
        blocked=frozenset(
            {
                "address.evidence",
                "permit.apply",
                "card.apply",
                "bank.open",
                "work.apply",
                "benefit.apply",
            }
        ),
        absent=frozenset({"shelter.letter_request", "school.enrol", "id.replace"}),
        routes={
            "address.evidence": ("tenancy.obtain",),
            "permit.apply": ("address.evidence", "tenancy.obtain"),
        },
    ),
    Persona(
        name="no_identity_document",
        pins_down=(
            "A missing primitive artefact becomes a task of its own, and that "
            "task leads the frontier because it gates the longest chain."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            known_absent=NOTHING_YET | {"document:identity"},
        ),
        frontier=(
            "id.replace",
            "shelter.letter_request",
            "language.enrol",
            "clinic.register",
        ),
        blocked=frozenset(
            {
                "address.evidence",
                "permit.apply",
                "card.apply",
                "bank.open",
                "work.apply",
                "benefit.apply",
            }
        ),
        absent=frozenset({"tenancy.obtain", "school.enrol"}),
        routes={"permit.apply": ("id.replace", "shelter.letter_request")},
    ),
    Persona(
        name="identity_not_asked_about",
        pins_down=(
            "The three-valued case. Nobody has been asked whether they hold an "
            "identity document, so the engine asks rather than assuming either "
            "way, and the tasks that depend on it wait for the answer."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            known_absent=NOTHING_YET,
        ),
        frontier=("shelter.letter_request", "language.enrol", "clinic.register"),
        # permit.apply is blocked rather than asked about: one of its
        # requirements is already known to be missing, so the answer to the
        # identity question cannot change its partition. id.replace is the task
        # the question actually moves, and that is the one that asks.
        needs_info=frozenset({"id.replace"}),
        blocked=frozenset(
            {
                "address.evidence",
                "permit.apply",
                "card.apply",
                "bank.open",
                "work.apply",
                "benefit.apply",
            }
        ),
        absent=frozenset({"tenancy.obtain", "school.enrol"}),
        open_questions=frozenset({"document:identity"}),
    ),
    Persona(
        name="knows_nothing_yet",
        pins_down=(
            "An empty situation produces questions, not a guessed plan. This is "
            "the intake entry point, and it must not invent facts to fill in."
        ),
        situation=Situation(),
        frontier=("clinic.register",),
        needs_info=frozenset(
            {
                "id.replace",
                "language.enrol",
                "shelter.letter_request",
                "tenancy.obtain",
                "address.evidence",
                "permit.apply",
                "school.enrol",
                "card.apply",
                "bank.open",
                "work.apply",
                "benefit.apply",
            }
        ),
    ),
    Persona(
        name="permit_already_held",
        pins_down=(
            "A task whose every product is already held is done, not repeated. "
            "Holding the permit is the same fact as having done permit.apply."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            held=frozenset({"document:identity", "document:permit"}),
            known_absent=NOTHING_YET - {"document:permit"},
        ),
        frontier=(
            "card.apply",
            "shelter.letter_request",
            "language.enrol",
            "clinic.register",
        ),
        blocked=frozenset(
            {"address.evidence", "bank.open", "work.apply", "benefit.apply"}
        ),
        absent=frozenset(
            {"permit.apply", "tenancy.obtain", "school.enrol", "id.replace"}
        ),
        unroutable={
            "benefit.apply": ("determination:residence_test",),
            "work.apply": ("elapsed:arrival_date",),
        },
    ),
    Persona(
        name="here_long_enough_to_work",
        pins_down=(
            "An elapsed prerequisite is satisfied by the calendar rather than by "
            "anything the person does, and it clears on its own."
        ),
        situation=Situation(
            arrival_date=LONG_AGO,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            held=frozenset({"document:identity", "document:permit"}),
            known_absent=NOTHING_YET - {"document:permit"},
        ),
        frontier=(
            "work.apply",
            "card.apply",
            "shelter.letter_request",
            "language.enrol",
            "clinic.register",
        ),
        blocked=frozenset({"address.evidence", "bank.open", "benefit.apply"}),
        absent=frozenset(
            {"permit.apply", "tenancy.obtain", "school.enrol", "id.replace"}
        ),
        unroutable={"benefit.apply": ("determination:residence_test",)},
    ),
    Persona(
        name="determination_granted",
        pins_down=(
            "A determination can only unblock a task when a record from outside "
            "says so, and that record has to name who decided it."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            held=frozenset({"document:identity", "document:permit"}),
            known_absent=NOTHING_YET - {"document:permit"},
            determinations={
                "determination:residence_test": DeterminationRecord(
                    outcome=DeterminationOutcome.GRANTED,
                    authority="the Fictional Benefits Office",
                    recorded_on=date(2026, 8, 14),
                )
            },
        ),
        frontier=(
            "benefit.apply",
            "card.apply",
            "shelter.letter_request",
            "language.enrol",
            "clinic.register",
        ),
        blocked=frozenset({"address.evidence", "bank.open", "work.apply"}),
        absent=frozenset(
            {"permit.apply", "tenancy.obtain", "school.enrol", "id.replace"}
        ),
        unroutable={"work.apply": ("elapsed:arrival_date",)},
    ),
    Persona(
        name="determination_refused",
        pins_down=(
            "A refusal is a hard block rather than an open question. The engine "
            "reports it without commenting on whether it was correct."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            held=frozenset({"document:identity", "document:permit"}),
            known_absent=NOTHING_YET - {"document:permit"},
            determinations={
                "determination:residence_test": DeterminationRecord(
                    outcome=DeterminationOutcome.REFUSED,
                    authority="the Fictional Benefits Office",
                    recorded_on=date(2026, 8, 14),
                )
            },
        ),
        frontier=(
            "card.apply",
            "shelter.letter_request",
            "language.enrol",
            "clinic.register",
        ),
        blocked=frozenset(
            {"address.evidence", "bank.open", "work.apply", "benefit.apply"}
        ),
        absent=frozenset(
            {"permit.apply", "tenancy.obtain", "school.enrol", "id.replace"}
        ),
        unroutable={
            "benefit.apply": ("determination:residence_test",),
            "work.apply": ("elapsed:arrival_date",),
        },
    ),
    Persona(
        name="no_children",
        pins_down="A situation predicate removes a task from the plan entirely.",
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=()),
            held=frozenset({"document:identity"}),
            known_absent=NOTHING_YET,
        ),
        frontier=("shelter.letter_request", "language.enrol", "clinic.register"),
        blocked=frozenset(
            {
                "address.evidence",
                "permit.apply",
                "card.apply",
                "bank.open",
                "work.apply",
                "benefit.apply",
            }
        ),
        absent=frozenset({"school.enrol", "tenancy.obtain", "id.replace"}),
    ),
    Persona(
        name="child_too_old_for_school",
        pins_down="The age range on a predicate is inclusive and is actually applied.",
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=(20,)),
            held=frozenset({"document:identity"}),
            known_absent=NOTHING_YET,
        ),
        frontier=("shelter.letter_request", "language.enrol", "clinic.register"),
        blocked=frozenset(
            {
                "address.evidence",
                "permit.apply",
                "card.apply",
                "bank.open",
                "work.apply",
                "benefit.apply",
            }
        ),
        absent=frozenset({"school.enrol", "tenancy.obtain", "id.replace"}),
    ),
    Persona(
        name="already_did_some_of_it",
        pins_down=(
            "Self-reported completion counts, and a completed task drops out of "
            "the routes reported for everything downstream of it."
        ),
        situation=Situation(
            arrival_date=ARRIVED,
            protection_stage=ProtectionStage.APPLIED,
            accommodation=Accommodation.EMERGENCY,
            household=Household(adults=1, children_ages=(7,)),
            held=frozenset({"document:identity", "document:shelter_letter"}),
            known_absent=NOTHING_YET - {"document:shelter_letter"},
            tasks_completed=frozenset({"shelter.letter_request", "clinic.register"}),
        ),
        frontier=("permit.apply", "address.evidence", "language.enrol"),
        blocked=frozenset(
            {"card.apply", "bank.open", "school.enrol", "work.apply", "benefit.apply"}
        ),
        done=frozenset({"shelter.letter_request", "clinic.register"}),
        absent=frozenset({"tenancy.obtain", "id.replace"}),
        routes={
            "card.apply": ("permit.apply",),
            "school.enrol": ("address.evidence",),
        },
    ),
)
