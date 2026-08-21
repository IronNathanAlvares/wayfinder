"""One call per category, instead of one call holding all six.

Three rounds of prompt work established the shape of the problem. Expanding a
category fixed that category and cost the others: detention went 0.796 to 1.000
when it got a section of its own (p=0.0010), and expanding the remaining four
then cost self-harm (p=0.0156). Attention behaves like a budget, and the
categories were spending each other's.

If that competition is an artefact of one call being asked to hold six
categories at once, giving each its own call removes it. This is that screen.

**The content is V4's, redistributed.** Each per-category prompt carries the
category section from `SYSTEM_PROMPT_V4` byte for byte, plus V4's negative
guidance and its instruction about uncertainty. The sections are sliced out of
V4 at import rather than copied, so "same words, different packaging" is a
property of the code. Only the framing sentences differ, because a call about
one category cannot be asked which of six it is; those are the few lines below
and they are the honest caveat on the comparison.

**What it costs.** Six requests per turn rather than one. The token cost is
close to V4's, since each prompt carries one section rather than six, and the
latency is close to one call's because the six run concurrently. The real price
is six times the request count and six independent chances to say yes, which is
a precision risk rather than a latency one and is what `crisis-holdout-v4` was
built to measure.

**The safety property is unchanged.** `full_screen` runs the lexicon first and
returns before this is consulted, so nothing here can clear a lexicon hit. Six
calls that can only add a detection still only add.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

from wayfinder.safety.escalation import ModelVerdict
from wayfinder.safety.llm import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    SYSTEM_PROMPT_V4,
    _default_client,
    _read_bool,
)
from wayfinder.safety.models import CrisisCategory

# A boolean, because the category is already fixed by which call this is.
# Keeping the category field would ask the model to answer a question it was not
# given the options for.
BOOLEAN_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "crisis": {
            "type": "boolean",
            "description": (
                "true if this message describes the situation named above, "
                "happening now or imminently."
            ),
        }
    },
    "required": ["crisis"],
    "additionalProperties": False,
}

_PREAMBLE: Final = """\
You are one of six screening layers in a service used by people who have \
recently arrived in a country and are navigating housing, healthcare, welfare \
and legal status. Many are in the protection process, waiting on decisions that \
take years. A deterministic pattern match has already run on this message and \
did not fire.

You are responsible for exactly one category and nothing else. Another layer is \
reading this message for each of the others, so a message that belongs to a \
different category is not your problem and answering false about it costs \
nothing. Do not hedge toward yes because a message sounds serious in some other \
way.

Almost nobody announces an emergency. They ask what time an office opens and \
mention halfway through that they are outside. Judge the situation the message \
describes, not the words it uses to describe it.

Your category is:
"""

_CLOSING: Final = """\
Answer one question: does this message describe the situation above, now or \
imminently?

If you are unsure and it is your category, say yes. A false positive shows \
somebody a list of helplines they did not need. A false negative is somebody \
sleeping outside, or somebody who wrote the only sentence they were going to \
write. Those costs are not comparable.

Reply only with the structured object.
"""


def _split_on_headings(prompt: str) -> Mapping[str, str]:
    """Every `## heading` section of a prompt, keyed by heading.

    Used to lift V4's sections out rather than restate them, so the claim that
    this screen carries the same words is checkable instead of asserted.
    """
    sections: dict[str, str] = {}
    heading: str | None = None
    body: list[str] = []
    for line in prompt.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections[heading] = "\n".join(body).strip()
            heading = line[3:].strip()
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections[heading] = "\n".join(body).strip()
    return sections


_V4_SECTIONS: Final[Mapping[str, str]] = _split_on_headings(SYSTEM_PROMPT_V4)

_NOT_A_CRISIS: Final = "What is not a crisis"


def _build_prompts() -> Mapping[CrisisCategory, str]:
    missing = [c.value for c in CrisisCategory if c.value not in _V4_SECTIONS]
    if missing or _NOT_A_CRISIS not in _V4_SECTIONS:
        msg = (
            f"cannot build the per-category prompts: V4 is missing sections for "
            f"{missing or [_NOT_A_CRISIS]}. Every category must have its own "
            "section in V4 for this screen to carry the same words."
        )
        raise RuntimeError(msg)
    return {
        category: (
            f"{_PREAMBLE}\n## {category.value}\n\n{_V4_SECTIONS[category.value]}\n\n"
            f"## {_NOT_A_CRISIS}\n\n{_V4_SECTIONS[_NOT_A_CRISIS]}\n\n{_CLOSING}"
        )
        for category in CrisisCategory
    }


PROMPTS: Final[Mapping[CrisisCategory, str]] = _build_prompts()

# Fixed, so the reported category is the same every time a turn fires on more
# than one. Ordered by how little the answer can be recovered from being wrong.
ORDER: Final[tuple[CrisisCategory, ...]] = (
    CrisisCategory.SELF_HARM,
    CrisisCategory.MEDICAL,
    CrisisCategory.VIOLENCE,
    CrisisCategory.CHILD_PROTECTION,
    CrisisCategory.DETENTION,
    CrisisCategory.ROUGH_SLEEPING,
)


class PerCategoryScreen:
    """A `ModelScreen` that asks each category separately and takes the union.

    Failures are not swallowed. If any of the six cannot be read, the whole
    screen raises and `full_screen` turns that into a visibly degraded result.
    Returning the five that did answer would be a screen that quietly stopped
    checking one category, which is worse than one that says it is off.
    """

    __slots__ = ("_client", "_model", "_prompts", "_workers")

    def __init__(
        self,
        client: Any = None,
        *,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        prompts: Mapping[CrisisCategory, str] | None = None,
    ) -> None:
        if client is None:
            client = _default_client(timeout)
        self._client = client
        self._model = model
        self._prompts = prompts or PROMPTS
        self._workers = len(ORDER)

    def _ask(self, category: CrisisCategory, text: str) -> bool:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=64,
            system=self._prompts[category],
            output_config={"format": {"type": "json_schema", "schema": BOOLEAN_SCHEMA}},
            messages=[{"role": "user", "content": text}],
        )
        return _read_bool(response)

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        # Concurrent, because six sequential calls would put this screen's
        # latency at six times a turn and latency here is part of the safety
        # story. Six parallel calls cost about what one costs in wall clock.
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            fired = dict(
                zip(
                    ORDER,
                    pool.map(lambda c: self._ask(c, text), ORDER),
                    strict=True,
                )
            )

        for category in ORDER:
            if fired[category]:
                return ModelVerdict.CRISIS, category
        return ModelVerdict.NO_OPINION, None
