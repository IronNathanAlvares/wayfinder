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

# Written from the category definitions in docs/07 section 3.1, deliberately
# not from the turns the deterministic screen was measured failing on. Fitting
# the prompt to a held-out split would burn it, and the whole reason ADR-0008
# exists is that the first holdout got burned that way.
SYSTEM_PROMPT: Final = """\
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
        effort: str = DEFAULT_EFFORT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if client is None:
            client = _default_client(timeout)
        self._client = client
        self._model = model
        self._effort = effort

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
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


def _read(response: Any) -> tuple[ModelVerdict, CrisisCategory | None]:
    """Parse the constrained response.

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

    payload = json.loads(text)

    # A missing `crisis` field is a malformed response, not a negative one.
    # Reading absence as False would turn every schema failure into a silent
    # clearance, which is the one outcome this screen must never produce.
    if "crisis" not in payload:
        msg = f"the model response has no `crisis` field: {sorted(payload)}"
        raise ValueError(msg)
    if not payload["crisis"]:
        return (ModelVerdict.NO_OPINION, None)

    raw = payload.get("category")
    if raw in (None, "none"):
        # It said crisis without naming a category. Escalating without a
        # category is still better than not escalating, so pick the broadest
        # response rather than discarding the verdict.
        return (ModelVerdict.CRISIS, None)
    return (ModelVerdict.CRISIS, CrisisCategory(raw))
