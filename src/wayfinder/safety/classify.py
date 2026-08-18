"""The layered classifier. Layers 1 and 2 run before anything sampled.

    1. crisis lexicon        deterministic. cannot be overridden by anything
    2. determination markers deterministic. the first-person entitlement shape
    3. classifier            for the remainder, pluggable
    4. tie-break             anything ambiguous goes to DETERMINATION

Layers 1 and 2 exist because the highest-cost mistakes should not depend on a
sampled model. Layer 3 handles genuine ambiguity, and layer 4 makes the default
safe. This is the same reasoning as refusing to put a model in a security
detection path: the input is written by somebody in distress, sometimes in a
second language, and sometimes by somebody deliberately probing the system, and
what is needed from this layer is predictability rather than intelligence.

Nothing downstream can override layer 1. That is not a convention, it is the
control flow: `classify` returns before layer 2 is reached.
"""

from __future__ import annotations

from typing import Protocol

from wayfinder.safety.crisis import screen
from wayfinder.safety.markers import determination_marker
from wayfinder.safety.models import Classification, CrisisLexicon
from wayfinder.safety.reference import classify_remainder
from wayfinder.safety.taxonomy import Layer, QuestionClass


class RemainderClassifier(Protocol):
    """Layer 3. A model implementation and the deterministic one share this.

    Returning None means "I do not know", which sends the turn to the tie-break.
    An implementation that never returns None removes the safe default, so an
    LLM adapter must map a low-confidence or unparseable response to None rather
    than to its best guess.
    """

    def __call__(self, text: str) -> QuestionClass | None: ...


def classify(
    text: str,
    *,
    lexicon: CrisisLexicon,
    remainder: RemainderClassifier | None = None,
) -> Classification:
    """Classify one turn. Total, deterministic given a deterministic layer 3."""
    hit = screen(text, lexicon)
    if hit is not None:
        # Terminal. Nothing else runs, and in particular no model has been
        # called at any point before this returns.
        return Classification(
            question_class=QuestionClass.CRISIS,
            layer=Layer.CRISIS_LEXICON,
            reason=f"crisis lexicon matched {hit.matched!r}",
            crisis=hit,
        )

    marker = determination_marker(text)
    if marker is not None:
        return Classification(
            question_class=QuestionClass.DETERMINATION,
            layer=Layer.DETERMINATION_MARKERS,
            reason=marker,
        )

    layer3 = remainder if remainder is not None else classify_remainder
    verdict = layer3(text)
    if verdict is QuestionClass.CRISIS:
        # A layer 3 implementation does not get to declare a crisis. The crisis
        # path is the deterministic screen and a static directory, and a model
        # reaching it would put generated text into somebody's emergency.
        verdict = None
    if verdict is QuestionClass.DETERMINATION:
        return Classification(
            question_class=QuestionClass.DETERMINATION,
            layer=Layer.CLASSIFIER,
            reason="classifier",
        )
    if verdict is not None:
        return Classification(
            question_class=verdict, layer=Layer.CLASSIFIER, reason="classifier"
        )

    return Classification(
        question_class=QuestionClass.DETERMINATION,
        layer=Layer.TIE_BREAK,
        reason=(
            "nothing matched, so this goes to a person. A wrongly escalated "
            "procedural question costs a caseworker thirty seconds; a wrongly "
            "answered determination question can cost somebody their rent."
        ),
    )
