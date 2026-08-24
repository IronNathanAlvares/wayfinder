"""Turning a plan into something a person under stress can read.

The tone rules from the design are not decoration. No cheerfulness, no
exclamation marks, no false reassurance. Somebody reading this may have just
been told they cannot do the thing they came to do.

The determination paragraph is the project in miniature: name the blocker, name
the authority, refuse to assess it, and still be useful. A refusal that leaves
somebody stuck is a failure, not a safety win, so every blocked task ends with
something the reader can act on, even when that is only who to ask.
"""

from __future__ import annotations

from datetime import date, timedelta

from wayfinder.corpus.models import Corpus
from wayfinder.plan.deadlines import DeadlineState, DeadlineStatus
from wayfinder.plan.models import Prerequisite
from wayfinder.plan.plan import Plan, PlanItem
from wayfinder.plan.refs import ArtefactKind, artefact_kind, artefact_name
from wayfinder.plan.situation import Situation


def _humanise(wait: timedelta) -> str:
    days = wait.days
    if days <= 0:
        return "no waiting time"
    if days < 14:
        return f"about {days} days"
    if days < 90:
        return f"about {round(days / 7)} weeks"
    return f"about {round(days / 30)} months"


def _title(corpus: Corpus, ref: str) -> str:
    artefact = corpus.artefact(ref)
    return artefact.title if artefact else artefact_name(ref).replace("_", " ")


def _authority(corpus: Corpus, ref: str) -> str:
    artefact = corpus.artefact(ref)
    if artefact is not None and artefact.decided_by:
        return artefact.decided_by
    return "the deciding authority"


def _elapsed_phrase(requirement: Prerequisite, situation: Situation, ref: str) -> str:
    """When the waiting period ends, in a date rather than a duration.

    "150 days from arrival" makes somebody do arithmetic under stress. A date
    does not.
    """
    anchor_field = artefact_name(ref)
    anchor = getattr(situation, anchor_field, None)
    if requirement.after is None or not isinstance(anchor, date):
        return "a waiting period has to pass first"
    ends = anchor + requirement.after
    return f"the waiting period runs until {ends.isoformat()}"


def _blocker_lines(corpus: Corpus, item: PlanItem, situation: Situation) -> list[str]:
    lines: list[str] = []
    for requirement in item.outstanding:
        if requirement.blocked_on_determination:
            names = " or ".join(_title(corpus, r) for r in requirement.any_of)
            deciders = sorted({_authority(corpus, r) for r in requirement.any_of})
            lines.append(
                f"waiting on {names}. That is decided by "
                f"{' and '.join(deciders)}, not by you and not by this system."
            )
            continue

        elapsed = [
            r for r in requirement.any_of if artefact_kind(r) is ArtefactKind.ELAPSED
        ]
        if elapsed and len(elapsed) == len(requirement.any_of):
            lines.append(_elapsed_phrase(requirement, situation, elapsed[0]))
            continue

        options = " or ".join(_title(corpus, r) for r in requirement.any_of)
        lines.append(f"needs {options}")
    return lines


def _deadline_line(state: DeadlineState) -> str:
    """One sentence about a closing window, worded by how sure we are.

    The wording carries the whole safety argument of `plan/deadlines.py`. The
    strongest thing said here is "may have closed", followed by an instruction
    to go and ask, because the cost of wrongly telling somebody their right has
    expired is not comparable to the cost of a wasted phone call.
    """
    # Exact days, never `_humanise`. A statutory window of 60 days rendered as
    # "about 9 weeks" is both wrong and dangerous: an approximation somebody
    # rounds down costs them days they actually had, and rounding up costs them
    # the appeal. Waits can be approximate. Deadlines cannot.
    days = state.within.days
    window = "1 day" if days == 1 else f"{days} days"

    if state.status is DeadlineStatus.UNKNOWN_START:
        return (
            f"Time limit: {window} from {state.described_as}. "
            "Tell a caseworker that date and they can say how long is left."
        )

    closes = state.closes_on.isoformat() if state.closes_on else ""
    left = state.days_remaining if state.days_remaining is not None else 0

    if state.status is DeadlineStatus.MAY_HAVE_CLOSED:
        # Ends on the instruction, not on the bad news. The last clause is what
        # a person skimming takes away, and "it is too late" is the one thing
        # this must not leave them with.
        return (
            f"Time limit: {window} from {state.described_as}, which by our "
            f"reckoning was up on {closes}. That date may be wrong, and late "
            "ones are often still accepted. Ask a caseworker to check it."
        )
    if state.status is DeadlineStatus.CLOSING:
        if left == 0:
            return f"Time limit: today is the last day ({closes}). Do this first."
        remaining = "1 day" if left == 1 else f"{left} days"
        return f"Time limit: {remaining} left, closing {closes}. Do this first."
    return f"Time limit: {window} from {state.described_as}, closing {closes}."


def render_plan(plan: Plan, corpus: Corpus, situation: Situation) -> str:
    """The client-facing view: what to start, what is waiting, and on what."""
    out: list[str] = []
    titles = {i.task.id: i.task.title for i in plan.items}

    frontier = plan.frontier
    if frontier:
        out.append("Start now")
        for item in frontier:
            out.append(f"  {item.task.title}")
            clock = plan.deadlines.get(item.task.id)
            if clock is not None:
                out.append(f"    {_deadline_line(clock)}")
            out.append(f"    {item.task.why}")
        out.append("")

        lead = frontier[0]
        count = plan.waiting_on.get(lead.task.id, 0)
        if count:
            verb = "thing is" if count == 1 else "things are"
            gate = plan.gated_wait.get(lead.task.id)
            timing = f" It gates {_humanise(gate)}." if gate else ""
            out.append(
                f"Do this one first: {lead.task.title}. "
                f"{count} other {verb} waiting on it.{timing}"
            )
            out.append("")

    if plan.blocked:
        out.append("Not yet")
        for item in plan.blocked:
            out.append(f"  {item.task.title}")
            clock = plan.deadlines.get(item.task.id)
            if clock is not None:
                # Said here too, and first. A window running down while somebody
                # waits for the thing that unblocks it is the worst case there
                # is, and burying it under the blockers is how it gets missed.
                out.append(f"    {_deadline_line(clock)}")
            for line in _blocker_lines(corpus, item, situation):
                out.append(f"    {line}")

            actions = plan.next_actions.get(item.task.id, ())
            if actions:
                names = sorted(titles.get(a, a) for a in actions)
                out.append(f"    You can start now: {', '.join(names)}")

            outside = plan.unroutable.get(item.task.id, ())
            if item.determination_refs:
                # Two different sentences, and the difference matters to the
                # person reading it. If a determination is the only thing left,
                # there is genuinely nothing for them to do. If it is one of
                # several blockers, there is still work they can be getting on
                # with, and saying otherwise would be discouraging and wrong.
                out.append(
                    "    Nothing you do can decide this one."
                    if item.blocked_by_determination
                    else "    The rest of it is not yours to do."
                )
                out.append(
                    "    A caseworker can tell you how it is applied for and "
                    "who can help you with it."
                )
            elif not actions and not outside:
                out.append(
                    "    This corpus does not have a route for this yet, which is a "
                    "gap in the corpus rather than a fact about your situation."
                )
        out.append("")

    if plan.needs_info:
        out.append("I need to ask you a few things first")
        for question in sorted(plan.open_questions):
            out.append(f"  {_question(corpus, question)}")
        out.append("")

    if plan.done:
        out.append("Already done")
        for item in plan.done:
            out.append(f"  {item.task.title}")
        out.append("")

    if not plan.items:
        out.append("Nothing in this corpus applies to the situation as described.")

    return "\n".join(out).rstrip() + "\n"


def _question(corpus: Corpus, question: str) -> str:
    if ":" in question:
        return f"Do you have {_title(corpus, question)}?"
    return f"What is your {question.replace('_', ' ')}?"
