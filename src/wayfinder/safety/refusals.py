"""Refusal text. Every refusal names an alternative.

A refusal that leaves somebody stuck is a failure, not a safety win. That is not
a nicety: somebody who is refused and given nothing goes and asks a system with
no such scruples, and gets a confident wrong answer instead.

Nothing here hedges. "You may be entitled to X" is still an entitlement claim,
and it is worse than saying nothing because it sounds like permission to plan
around it.

These templates are static text, reviewed by reading them as somebody who has
just been refused. No cheerfulness, no exclamation marks, no false reassurance.
"""

from __future__ import annotations

from typing import Final

from wayfinder.safety.taxonomy import QuestionClass

DETERMINATION: Final = """\
That question needs a decision about your own situation, and those decisions are
made by a named authority rather than by this system. I am not going to guess at
it, because a guess you plan around is worse than no answer.

I have sent it to a caseworker with your situation attached. They usually answer
within a few working days.

While you wait, I can tell you how the process works, what documents are usually
asked for, and who else can help. Ask me any of those and I will answer with
sources.
"""

OUT_OF_SCOPE_LEGAL: Final = """\
That is legal advice, and I am not a solicitor. Getting it wrong here can damage
a protection claim, so I am not going to attempt it.

Free legal help with international protection is available from the Legal Aid
Board on 1800 23 83 43. The Irish Refugee Council also runs an information
helpline on 01 764 5854, Monday, Tuesday and Thursday from 10am to 1pm.

I can still tell you how a process works and what documents it asks for.
"""

OUT_OF_SCOPE_MEDICAL: Final = """\
That is a medical question and I am not able to answer it.

If it is urgent, call 999 or 112. Otherwise a GP is the right person to ask, and
a medical card covers that cost once you have one.

I can tell you how to register with a GP and how to apply for a medical card.
"""

OUT_OF_SCOPE_PREDICTION: Final = """\
Nobody can tell you how a decision will go. Not me, and not anyone else. If
somebody tells you they can, they are guessing.

Here is what I can do. I can tell you how the process works. I can tell you what
the decision is based on. I can tell you who can help you get ready.

A caseworker or a solicitor can look at your real papers. That is the only way
to get closer to an answer than this.
"""

NO_SOURCE: Final = """\
I do not have a source I trust for that. So I will not answer it from memory.

The Irish Refugee Council helpline is 01 764 5854. It is open on Monday, Tuesday
and Thursday, from 10am to 1pm. They answer questions like this one.

Citizens Information also covers most of these processes in plain words.
"""

_BY_CLASS: Final[dict[QuestionClass, str]] = {
    QuestionClass.DETERMINATION: DETERMINATION,
    QuestionClass.OUT_OF_SCOPE: OUT_OF_SCOPE_PREDICTION,
}

ALL_TEMPLATES: Final[tuple[str, ...]] = (
    DETERMINATION,
    OUT_OF_SCOPE_LEGAL,
    OUT_OF_SCOPE_MEDICAL,
    OUT_OF_SCOPE_PREDICTION,
    NO_SOURCE,
)


def refusal_for(question_class: QuestionClass) -> str | None:
    """The default refusal for a class, or None if the class is answerable."""
    return _BY_CLASS.get(question_class)
