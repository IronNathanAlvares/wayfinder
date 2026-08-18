"""The crisis screen. Deterministic, no model, terminal.

Three properties, each deliberate.

**No model in the path.** A model cannot be talked out of a regex, and it cannot
mis-generate a phone number. The response is looked up, not composed.

**It over-triggers on purpose.** The cost matrix is not symmetric. A false
positive shows somebody a list of helplines they did not need. A false negative
is somebody sleeping outside. The eval gate requires recall of 0.99 and sets no
precision gate at all.

**It is terminal.** A crisis response does not continue into planning. If
somebody says they have nowhere to sleep tonight, the answer is a phone number,
not a forty-step onboarding plan.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache

from wayfinder.safety.models import (
    CrisisCategory,
    CrisisDirectory,
    CrisisHit,
    CrisisLexicon,
)
from wayfinder.safety.normalise import normalise

# Categories are checked in this order so that a turn matching two of them gets
# the one whose response is most urgent. Somebody describing violence and
# homelessness in the same sentence needs the violence numbers first.
_PRIORITY: tuple[CrisisCategory, ...] = (
    CrisisCategory.SELF_HARM,
    CrisisCategory.MEDICAL,
    CrisisCategory.VIOLENCE,
    CrisisCategory.CHILD_PROTECTION,
    CrisisCategory.DETENTION,
    CrisisCategory.ROUGH_SLEEPING,
)


@lru_cache(maxsize=8)
def _compiled(
    lexicon: CrisisLexicon,
) -> tuple[tuple[CrisisCategory, tuple[tuple[re.Pattern[str], str], ...]], ...]:
    """Compile once per lexicon. Frozen models make this safe to cache."""
    by_id = {c.id: c for c in lexicon.categories}
    out = []
    for category in _PRIORITY:
        entry = by_id.get(category)
        if entry is None:
            continue
        out.append((category, tuple((p.compile(), p.phrase) for p in entry.patterns)))
    return tuple(out)


def screen(text: str, lexicon: CrisisLexicon) -> CrisisHit | None:
    """Match the raw turn against the lexicon. Nothing else happens first."""
    haystack = normalise(text)
    for category, patterns in _compiled(lexicon):
        for pattern, phrase in patterns:
            if pattern.search(haystack):
                return CrisisHit(category=category, matched=phrase)
    return None


def respond(hit: CrisisHit, directory: CrisisDirectory) -> str:
    """Assemble the response from directory entries. Nothing here is generated.

    Every number, name and opening time in the output is a field copied verbatim
    from a dated entry. The only text this function contributes is fixed
    scaffolding, which is what makes "the response is looked up" checkable
    rather than merely intended.
    """
    section = directory.section(hit.category)
    lines = [section.lead_line, ""]
    for entry in section.entries:
        lines.append(entry.name)
        lines.append(f"  {entry.contact}")
        lines.append(f"  {entry.hours}")
        if entry.covers:
            lines.append(f"  {entry.covers}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def contacts(directory: CrisisDirectory) -> Sequence[str]:
    """Every contact string in the directory, for tests that check nothing was
    invented on the way out."""
    return [e.contact for s in directory.sections for e in s.entries]
