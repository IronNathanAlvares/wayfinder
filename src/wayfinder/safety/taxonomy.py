"""The question taxonomy. Five classes, and the value is in the boundaries.

The rule in one line: **describing a rule is procedural; applying a rule to this
person is a determination.**

| Answerable                          | Not answerable                  |
|-------------------------------------|---------------------------------|
| What are the conditions for X?      | Do I meet the conditions for X? |
| How is habitual residence assessed? | Am I habitually resident?       |
| What documents does X require?      | Are my documents enough?        |
| How long does X usually take?       | How long will mine take?        |

Ambiguity resolves to DETERMINATION. A wrongly escalated procedural question
costs a caseworker thirty seconds. A wrongly answered determination question can
cost somebody their rent.
"""

from __future__ import annotations

from enum import Enum


class QuestionClass(Enum):
    """Exactly one of these per turn."""

    CRISIS = "crisis"
    DETERMINATION = "determination"
    PROCEDURAL = "procedural"
    PLANNING = "planning"
    OUT_OF_SCOPE = "out_of_scope"

    @property
    def answered_by_the_system(self) -> bool:
        """Whether this class may reach generation at all.

        CRISIS is answered from a static directory, DETERMINATION by a human,
        OUT_OF_SCOPE by a decline that names somebody else. Only two classes
        leave here with the system answering.
        """
        return self in {QuestionClass.PROCEDURAL, QuestionClass.PLANNING}


class Layer(Enum):
    """Which layer decided, recorded on every classification.

    Not debugging. It is the record of why a turn was handled the way it was,
    and it is what makes the eval meaningful: a class assigned by the tie-break
    is a different thing from one a deterministic marker was certain about.
    """

    CRISIS_LEXICON = "crisis_lexicon"
    DETERMINATION_MARKERS = "determination_markers"
    CLASSIFIER = "classifier"
    TIE_BREAK = "tie_break"
