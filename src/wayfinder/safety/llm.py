"""A model-backed crisis screen, constrained so it can only ever escalate.

ADR-0008 measured the deterministic screen at 0.167 recall on held-out data
against a gate of 0.99, so a model becomes load-bearing here. This is the
adapter. The constraint that makes it acceptable is not in this file: it is in
`escalation.full_screen`, which runs the lexicon first and returns before this
is consulted. Nothing written here can clear a lexicon hit.

Three deliberate choices.

**The schema is closed.** The response is constrained to a two-field object with
an enumerated category. A model that returns prose, or a category nobody
defined, produces a validation failure rather than a guess, and a validation
failure is a degraded screen rather than a silent miss.

**It fails loudly.** No exception is swallowed. `full_screen` turns any failure
into a visibly degraded screen that surfaces the directory unprompted. A crisis
screen that quietly stops working is worse than one that is visibly off,
because the first one is still trusted.

**The timeout is short.** This runs before anything else on every turn. A screen
that hangs delays somebody in an emergency, and a degraded screen that says so
is better than a slow one that does not.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Final

from wayfinder.safety.escalation import ModelVerdict
from wayfinder.safety.models import CrisisCategory

DEFAULT_MODEL: Final = "claude-opus-5"

# This screen runs before every other check on every turn, so latency is part
# of its safety story. Low effort is the right setting for a bounded
# classification against an enumerated schema, and it is a tuning decision
# rather than a downgrade: the deterministic lexicon has already run, and this
# layer exists to catch phrasing the patterns missed.
DEFAULT_EFFORT: Final = "low"

DEFAULT_TIMEOUT_SECONDS: Final = 8.0

_CATEGORIES: Final = tuple(c.value for c in CrisisCategory)

RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "crisis": {
            "type": "boolean",
            "description": (
                "true if this turn describes an immediate risk to somebody's "
                "safety, shelter, or health."
            ),
        },
        "category": {
            "type": "string",
            "enum": [*_CATEGORIES, "none"],
            "description": "The category, or 'none' when crisis is false.",
        },
    },
    "required": ["crisis", "category"],
    "additionalProperties": False,
}

# The original prompt, kept so the change to it can be measured rather than
# asserted. Written from the category definitions in docs/07 section 3.1.
#
# It scored 0.897 overall and 0.750 on self-harm against the 320-item crisis
# holdout. Note what it says about self-harm: "thoughts of suicide or self-harm",
# which describes a state of mind rather than anything a person writes down.
SYSTEM_PROMPT_V1: Final = """\
You are a screening layer in a service used by people who have recently arrived \
in a country and are navigating housing, healthcare, welfare and legal status. \
A deterministic pattern match has already run on this message and did not fire. \
Your only job is to catch what it missed.

Decide one thing: does this message describe an immediate risk to somebody's \
safety, shelter, or health? The categories are:

- rough_sleeping: nowhere to sleep tonight, being put out, sleeping outside
- violence: being hurt or threatened by somebody, sexual violence, trafficking, \
being controlled or having documents taken
- child_protection: a child at risk, or the person writing is under 18 and alone
- medical: somebody needs medical help now
- self_harm: thoughts of suicide or self-harm
- detention: detained, arrested, or facing imminent removal from the country

Judge what the message describes, not the words it uses. "The hostel say I must \
go before lunch and I have a small baby" is rough sleeping. "They say the plane \
is booked for Friday" is detention. "My boss holds my passport until I finish \
the debt" is violence. None of those contain an obvious keyword, and all three \
are what you are here for.

Say yes when you are unsure. A false positive shows somebody a list of \
helplines they did not need. A false negative is somebody sleeping outside. \
Those costs are not comparable and you should not treat them as though they are.

Questions *about* a process are not a crisis. "What happens if somebody is \
evicted?" is asking how a rule works. "I am being evicted tomorrow" is not.

Reply only with the structured object.
"""

# V2. The self-harm section is written from the published clinical taxonomy
# rather than from the category name.
#
# Sources, read 19 August 2026: the Columbia-Suicide Severity Rating Scale for
# the ideation ladder and the behaviour categories, the American Association of
# Suicidology's IS PATH WARM for the proximal signs, and the standard
# preparatory-behaviour list carried by Samaritans, the Zero Suicide Alliance
# and Mersey Care NHS.
#
# Two things from that reading shaped this beyond the list itself.
#
# IS PATH WARM's own authors concede its sensitivity and specificity are "not
# great", so it is used here as a list of things people write that should raise
# the screen, never as a checklist that settles the answer.
#
# The same sources note that most of these behaviours have ordinary
# explanations on their own and matter when they are sudden, out of character,
# or accompanied by distress. That is why this prompt spends as much space on
# what is *not* a crisis as on what is. A screen that fires on every mention of
# a death teaches people to ignore it, and an ignored screen protects nobody.
#
# Written from the taxonomy above and not from the 33 turns V1 was measured
# missing. The overlap between the two is the taxonomy being correct, not the
# prompt being fitted, and the only way to tell those apart is a split this
# prompt has never seen. That is what `crisis-holdout-v2` is for.
SYSTEM_PROMPT_V2: Final = """\
You are a screening layer in a service used by people who have recently arrived \
in a country and are navigating housing, healthcare, welfare and legal status. \
Many are in the protection process, waiting on decisions that take years. A \
deterministic pattern match has already run on this message and did not fire. \
Your only job is to catch what it missed.

Decide one thing: does this message describe an immediate risk to somebody's \
safety, shelter, or health?

## What people actually write

Almost nobody announces an emergency. They ask what time an office opens and \
mention halfway through that they are outside. They ask about a form and say \
their husband broke their nose on Sunday. Judge the situation the message \
describes, not the words it uses to describe it.

- rough_sleeping: nowhere to sleep tonight, being put out, sleeping outside, a \
place that ends today, being refused a bed, locked out, moved with nowhere to \
arrive at
- violence: being hurt or threatened, sexual violence, trafficking, being \
controlled, watched or isolated, documents or wages held, debt that never ends, \
being afraid to go home
- child_protection: a child at risk, a child alone or unaccounted for, or the \
person writing is under 18 without a parent here
- medical: somebody needs medical help now, or is deteriorating, or has run out \
of medication that keeps them well
- self_harm: see below. This is the category most often missed.
- detention: detained, arrested, held at a port, officers present, or a removal \
with a named date close enough to matter

## self_harm

People almost never say "I want to kill myself". Treat any of the following as \
self_harm, whether or not distress is stated anywhere in the message:

Thoughts, at any point on the scale: wishing to be dead, not wanting to wake \
up, not wanting to exist, wanting it all to stop permanently, thoughts of \
killing themselves with or without a method, having a method in mind, having \
obtained one, or asking how a method works or how long something takes.

A previous attempt, especially described as recurring or returning. A previous \
attempt is the single strongest predictor there is; do not read it as history.

Preparation and putting affairs in order: writing a note or a letter to be \
passed on, giving away possessions, settling things, asking who would care for \
their child if something happened to them.

Leave-taking: saying goodbye, thanking you as though for the last time, \
apologising for everything, asking that a message reach somebody.

A future that stops: appointments they say they will not need, plans that end \
at a date, saying they will not be there when a decision arrives.

Resolution: sudden calm, relief, or peace after distress, or saying they have \
decided. Having stopped struggling with the decision is not improvement.

Self-injury of any kind, including cutting or burning, and including when it is \
described as coping rather than as wanting to die.

Hopelessness, purposelessness, feeling trapped, or believing others would be \
better off without them, when it comes with any of the above or with a decision \
that has just gone against them.

## What is not a crisis

Precision matters here for a safety reason, not a tidiness one. Somebody who \
gets a list of helplines every time they mention a death stops reading them.

- Questions about how a process works. "What happens if somebody is evicted?" \
is asking about a rule. "I am being evicted tomorrow" is not.
- Asking for a number to keep, or how a service is accessed, while calm.
- Things that are over: a violent relationship left years ago, sleeping rough \
last winter, an illness recovered from, a deportation that happened to somebody \
else in the past.
- Grief and bereavement, including a death by suicide, when the person is \
describing loss rather than their own risk.
- Ordinary despair about paperwork and delay. "This process is killing me", "I \
am fed up", "I could scream", "I am dying to get this sorted", "my phone died". \
These are how people write. They are not disclosures.

Somebody can be exhausted, angry and hopeless about a system without being at \
risk, and treating those as the same thing is what makes a screen useless.

## When you are unsure

Say yes. A false positive shows somebody a list of helplines they did not need. \
A false negative is somebody sleeping outside, or somebody who wrote the only \
sentence they were going to write. Those costs are not comparable and you \
should not treat them as though they are.

Reply only with the structured object.
"""

# V3. V2 with one line changed and nothing else.
#
# Measured on `crisis-holdout-v2`, V2 took self-harm from 0.481 to 0.685 and
# dropped detention from 0.963 to 0.778, netting to nothing. The suspect is this
# line, identified from the diff rather than from which turns were missed: V1
# said detention covers "facing imminent removal from the country" and V2
# replaced that with "a removal with a named date close enough to matter", which
# swaps a fact for a judgement the model then makes conservatively.
#
# So this is a revert of that phrase and not a new idea. It keeps the two cases
# V2 usefully added, "held at a port" and "officers present". The only thing it
# takes from the V2 measurement is one per-category number, which is the least
# that can be learned from a run and still act on it.
#
# Derived from V2 by substitution rather than written out again, so "exactly one
# line differs" is a property of the code instead of something a reader has to
# check by eye. `_ONE_LINE_CHANGED` fails at import if the substitution ever
# stops matching, which is what would otherwise happen silently the first time
# somebody edits V2.
_V2_DETENTION: Final = (
    "- detention: detained, arrested, held at a port, officers present, or a "
    "removal with a named date close enough to matter"
)
_V3_DETENTION: Final = (
    "- detention: detained, arrested, held at a port, officers present, or "
    "facing imminent removal from the country"
)
SYSTEM_PROMPT_V3: Final = SYSTEM_PROMPT_V2.replace(_V2_DETENTION, _V3_DETENTION)


def _one_line_changed() -> None:
    """A prompt that silently equals the one it was meant to differ from would
    produce an A/B where both arms are the same prompt, and a difference of
    zero that reads as a finding."""
    if SYSTEM_PROMPT_V3 == SYSTEM_PROMPT_V2:
        msg = (
            "SYSTEM_PROMPT_V3 is identical to V2: the detention line it means to "
            "replace no longer matches. Update _V2_DETENTION to the current "
            "wording rather than leaving the two prompts the same."
        )
        raise RuntimeError(msg)


_one_line_changed()


# --- the emphasis experiment -------------------------------------------------
#
# V2 gives self-harm about twenty-five lines and its own heading, and gives
# every other category one bullet. V1 gave all six a bullet. Measured, self-harm
# gained eleven turns and detention lost eleven, and reverting the detention
# wording did nothing, so the phrasing was not the cause.
#
# The hypothesis left standing is that attention follows emphasis: the category
# that got expanded gained, and the ones left at a line lost. Two arms test it,
# both built from V2 by substitution so that what differs between them is
# exactly what is written below and nothing else.
#
#   V5 = V2 with detention expanded, and nothing else touched.
#   V4 = V5 with the remaining four expanded as well.
#
# **V5 is the arm that makes the answer interpretable.** If per-category
# emphasis is what matters, detention recovers in V5 while the other four stay
# where V2 left them. If instead a longer prompt dilutes attention across the
# board, V5 will not recover detention and V4 will be worse everywhere. Running
# only V4 could not separate those: it would produce a number and no reason.
#
# Written from how people in this position describe these situations, in the
# same voice as the self-harm section, and not from the turns any prompt has
# been measured missing.

_DETENTION_SECTION: Final = """
## detention

Somebody is being held, or is about to be moved, and the clock is short. Treat \
any of these as detention:

Being held now: in a cell, a van, a holding room, at a gate, at a port, or told \
by anybody in authority that they are not free to leave.

Officers present: at the door, in a reception, at a workplace, on a bus, asking \
for people by name or working through a list.

A named date, for a flight, a transfer, a charter, or an instruction to present \
themselves. Do not judge whether the date is close enough to matter. A date \
somebody has been given is the thing that matters, and by the time they write \
they have usually already decided that it does.

Instructions that precede a removal and little else: attend with luggage, bring \
one bag, bring a photograph, be ready in the morning, attend a travel document \
or re-documentation appointment at an embassy or consulate.

Papers that have landed: an order served or signed, removal directions, an \
appeal window closed, a case closed with an instruction to leave.

Somebody detained whose family cannot reach them, or who is without a \
solicitor, their medication, or an interpreter.
"""

_ROUGH_SLEEPING_SECTION: Final = """
## rough_sleeping

Nowhere to sleep tonight. People rarely use the word homeless about themselves. \
Treat any of these as rough_sleeping:

A place that ends today or has already ended: a notice dated today, a booking \
that finished, a host who has changed their mind, an agreement that ran out.

Being refused or shut out: no bed available, a key that stopped working, a name \
taken off a list, a door not opened, barred after an incident, arrears counted \
against them.

Already outside: a doorway, a station, a night bus, a car park, a tent, a \
launderette, an airport, a hospital corridor, or walking to stay awake.

Moved with nothing to arrive at: an address that does not exist, a transfer with \
no room at the other end, an offer too far away to reach before dark.

Everything closed: the office shut, the number ringing out, the last bus gone.

Any of the above with a child, a pregnancy, an illness, a disability or the cold \
on top of it, which is most of them.
"""

_VIOLENCE_SECTION: Final = """
## violence

Somebody is being hurt, or is controlled by a person who could hurt them. This \
is rarely stated plainly either. Treat any of these as violence:

Being hurt now or threatened with it, including "he said next time", and \
including when an apology or an explanation follows.

Afraid to go home, afraid to go back to a room, sleeping against a door, or \
writing from a bathroom, a library, or somebody else's phone.

Being controlled: money, bank card, phone, documents, medication, movement, who \
they may speak to, whether they may learn the language, whether they may attend \
an appointment alone.

Work that cannot be left: wages held or taken, a debt that never reduces, a \
bond, being told they owe for the journey, being kept in a house or on a farm \
or at a car wash until somebody else says otherwise.

Sexual violence, including being asked for it in exchange for a room, a job, or \
papers.

Threats that reach elsewhere: family at home, a sister, a child, a mother.

Being found, followed, watched, or having a new address discovered.

A marriage or a journey arranged for somebody without their agreement, and \
cutting arranged for a girl.
"""

_CHILD_PROTECTION_SECTION: Final = """
## child_protection

A child is at risk, or the person writing is one. Treat any of these as \
child_protection:

A child hurt, afraid of somebody at home, or with injuries that are being \
explained away.

A child alone: unaccompanied on arrival, unaccounted for, missing, waiting \
somewhere nobody has come for them, or left with people nobody can name.

The person writing is under eighteen without a parent here, whether or not they \
give their age directly. Somebody disputing an age assessment and saying they \
are a child belongs here.

A child working, carrying things for adults, paying off a debt, kept out of \
school, or being paid by an adult for something they will not describe.

A child being taken abroad, separated at a border, or removed on their own.

A baby not thriving: not feeding, not gaining, not registered, not seen by \
anybody.

A child saying they do not want to be alive. Their age does not make it less \
serious.
"""

_MEDICAL_SECTION: Final = """
## medical

Somebody needs medical help now, or is getting worse while they wait. Treat any \
of these as medical:

Deteriorating rather than stable: worse today than yesterday, worse in the last \
hour, or a change that came on suddenly.

Out of medication that keeps them alive or well: insulin, heart tablets, \
epilepsy, HIV, TB, a missed dialysis session, psychiatric medication stopped.

The things that do not wait: bleeding that will not stop, difficulty breathing, \
chest pain, a head injury, weakness or drooping on one side, speech gone \
strange, a first seizure or one that will not end, a swelling throat.

Pregnancy and just after it: bleeding, severe pain, reduced movement, waters \
early, a fever afterwards.

A baby or small child who is floppy, very hot, not feeding, not waking, not \
producing wet nappies, or working hard to breathe.

Somebody who has taken too much of something, whether or not they meant to.

Somebody who is not going because of what it might cost.
"""

# Where the expanded sections are inserted: after self-harm, before the section
# on what is not a crisis, so the negative guidance stays last.
_NOT_A_CRISIS_HEADING: Final = "## What is not a crisis"

_EXPANSIONS: Final[tuple[tuple[str, str], ...]] = (
    ("detention", _DETENTION_SECTION),
    ("rough_sleeping", _ROUGH_SLEEPING_SECTION),
    ("violence", _VIOLENCE_SECTION),
    ("child_protection", _CHILD_PROTECTION_SECTION),
    ("medical", _MEDICAL_SECTION),
)

# The one-line bullets each expansion replaces, taken from V2 verbatim.
_V2_BULLETS: Final[dict[str, str]] = {
    "detention": _V2_DETENTION,
    "rough_sleeping": (
        "- rough_sleeping: nowhere to sleep tonight, being put out, sleeping "
        "outside, a place that ends today, being refused a bed, locked out, "
        "moved with nowhere to arrive at"
    ),
    "violence": (
        "- violence: being hurt or threatened, sexual violence, trafficking, "
        "being controlled, watched or isolated, documents or wages held, debt "
        "that never ends, being afraid to go home"
    ),
    "child_protection": (
        "- child_protection: a child at risk, a child alone or unaccounted for, "
        "or the person writing is under 18 without a parent here"
    ),
    "medical": (
        "- medical: somebody needs medical help now, or is deteriorating, or "
        "has run out of medication that keeps them well"
    ),
}


def _expand(prompt: str, names: Sequence[str]) -> str:
    """Give each named category the treatment self-harm already has.

    Its bullet becomes a pointer and it gains a section of its own, so the
    change is in emphasis and structure rather than only in wording. Every
    substitution is checked, because one that silently no-ops would produce an
    arm identical to its control and a difference of zero that reads as a
    finding.
    """
    sections = dict(_EXPANSIONS)
    for name in names:
        bullet = _V2_BULLETS[name]
        if bullet not in prompt:
            msg = (
                f"the {name} bullet is not in the prompt being expanded, so the "
                "arm would be identical to its control. Update _V2_BULLETS to "
                "match the current wording."
            )
            raise RuntimeError(msg)
        prompt = prompt.replace(bullet, f"- {name}: see below.")
        prompt = prompt.replace(
            _NOT_A_CRISIS_HEADING,
            sections[name].strip("\n") + "\n\n" + _NOT_A_CRISIS_HEADING,
            1,
        )
    return prompt


# Detention only. The diagnostic arm.
SYSTEM_PROMPT_V5: Final = _expand(SYSTEM_PROMPT_V2, ["detention"])

# All five. The candidate fix.
SYSTEM_PROMPT_V4: Final = _expand(SYSTEM_PROMPT_V5, [n for n, _ in _EXPANSIONS[1:]])


# What the adapter uses. Swapping this is a deliberate act with a measurement
# attached, not a default somebody drifts into.
#
# **V5 ships**, measured on `crisis-holdout-v3` on 22 August 2026. Against V2 it
# gains detention decisively, 0.796 to 1.000 with 11 turns caught only by V5 and
# none the other way (p=0.0010), and it loses nothing significantly anywhere.
#
# V4 scores higher overall, 0.925 against V5's 0.906, and it is not shipped. The
# extra comes with a significant self-harm loss against V2 (7 turns, p=0.0156),
# and self-harm is the category where a miss is least recoverable. Buying
# aggregate recall with the one category that cannot be asked twice is the
# trade this project has already refused once.
#
# Neither meets the 0.99 gate. V5's lower bound is 0.875.
SYSTEM_PROMPT: Final = SYSTEM_PROMPT_V5

PROMPTS: Final[dict[str, str]] = {
    "v1": SYSTEM_PROMPT_V1,
    "v2": SYSTEM_PROMPT_V2,
    "v3": SYSTEM_PROMPT_V3,
    "v4": SYSTEM_PROMPT_V4,
    "v5": SYSTEM_PROMPT_V5,
}


class AnthropicCrisisScreen:
    """A `ModelScreen` backed by the Anthropic API.

    The client is injected rather than constructed here so tests can drive the
    whole adapter, including the schema handling and the failure paths, without
    a network or a key.
    """

    def __init__(
        self,
        client: Any = None,
        *,
        model: str = DEFAULT_MODEL,
        effort: str | None = DEFAULT_EFFORT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if client is None:
            client = _default_client(timeout)
        self._client = client
        self._model = model
        self._effort = effort
        # Injectable so a prompt change can be measured against the one it
        # replaces in a single run, with nothing else different between them.
        self._system_prompt = system_prompt

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        # Not every model accepts `effort` — Haiku 4.5 rejects it with a 400 —
        # so it is omitted rather than sent as a default. A screen that only
        # works on one model tier is not a screen you can fall back with.
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
        }
        if self._effort is not None:
            output_config["effort"] = self._effort

        response = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            system=self._system_prompt,
            output_config=output_config,
            messages=[{"role": "user", "content": text}],
        )
        return _read(response)


def _default_client(timeout: float) -> Any:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        msg = (
            "the model crisis screen needs the anthropic package. "
            "Install it with: uv sync --extra llm"
        )
        raise RuntimeError(msg) from exc
    # Retries are bounded rather than disabled: one retry covers a transient
    # blip, and more than that turns a degraded screen into a slow one.
    return anthropic.Anthropic(timeout=timeout, max_retries=1)


def _payload(response: Any) -> dict[str, Any]:
    """The parsed body, or an exception.

    Anything unexpected raises. `full_screen` turns that into a visibly
    degraded screen, which is the honest outcome: we did not screen this turn,
    and the person should be told rather than assumed safe.
    """
    if getattr(response, "stop_reason", None) == "refusal":
        msg = "the model declined to screen this turn"
        raise ValueError(msg)

    text = next(
        (b.text for b in response.content if getattr(b, "type", None) == "text"),
        None,
    )
    if text is None:
        msg = "the model returned no text block to parse"
        raise ValueError(msg)

    payload: dict[str, Any] = json.loads(text)

    # A missing `crisis` field is a malformed response, not a negative one.
    # Reading absence as False would turn every schema failure into a silent
    # clearance, which is the one outcome this screen must never produce.
    if "crisis" not in payload:
        msg = f"the model response has no `crisis` field: {sorted(payload)}"
        raise ValueError(msg)
    return payload


def _read_bool(response: Any) -> bool:
    """For the per-category screen, where the category is fixed by the call."""
    return bool(_payload(response)["crisis"])


def _read(response: Any) -> tuple[ModelVerdict, CrisisCategory | None]:
    """Parse the constrained response into a verdict and a category."""
    payload = _payload(response)
    if not payload["crisis"]:
        return (ModelVerdict.NO_OPINION, None)

    raw = payload.get("category")
    if raw in (None, "none"):
        # It said crisis without naming a category. Escalating without a
        # category is still better than not escalating, so pick the broadest
        # response rather than discarding the verdict.
        return (ModelVerdict.CRISIS, None)
    return (ModelVerdict.CRISIS, CrisisCategory(raw))
