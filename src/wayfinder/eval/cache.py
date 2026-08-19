"""An on-disk cache of model verdicts, for evaluation runs only.

A full comparison is a thousand API calls and a quarter of an hour. Twice now a
run has been interrupted partway and the work paid for was lost, which is a bad
way to spend somebody's credits and a worse way to lose a measurement.

So verdicts are written to disk as they arrive, keyed by the exact inputs that
produced them, and a rerun skips whatever it already has. An interrupted run
resumes for the price of what is left.

**This is eval-only and it must stay that way.** A cached crisis screen in a
running system would answer today's turn with last month's verdict, and a
verdict is not a fact about a sentence: it is a fact about a sentence, a model
and a prompt at a moment. The key includes all three so a changed prompt or a
changed model never reads a stale entry, but that guards correctness of the
measurement, not of a live screen. `wayfinder.safety` does not import this and
the import-linter contract keeps it that way.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from wayfinder.safety.escalation import ModelVerdict
from wayfinder.safety.models import CrisisCategory

# Written after this many new verdicts. Small, because the whole point is that
# an interrupted run keeps what it paid for, and a flush every entry costs
# nothing next to an API call.
FLUSH_EVERY: Final = 10


def _key(model: str, prompt: str, text: str) -> str:
    """Everything that can change the verdict, and nothing that cannot.

    The prompt is hashed in full rather than named, so editing a prompt without
    renaming it cannot silently reuse the old prompt's answers.
    """
    digest = hashlib.sha256()
    for part in (model, prompt, text):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


class CachedScreen:
    """Wraps a `ModelScreen` and remembers what it said.

    Failures are never cached. A degraded screen is a transient condition and
    recording it would turn one network blip into a permanent hole in every
    later measurement.
    """

    __slots__ = ("_hits", "_inner", "_misses", "_model", "_path", "_prompt", "_seen")

    def __init__(
        self,
        inner: Any,
        *,
        path: Path,
        model: str,
        prompt: str,
    ) -> None:
        self._inner = inner
        self._path = path
        self._model = model
        self._prompt = prompt
        self._seen: dict[str, list[Any]] = {}
        self._hits = 0
        self._misses = 0
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._seen = loaded

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def calls_made(self) -> int:
        return self._misses

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        key = _key(self._model, self._prompt, text)
        cached = self._seen.get(key)
        if cached is not None:
            self._hits += 1
            verdict, category = cached
            return (
                ModelVerdict(verdict),
                CrisisCategory(category) if category else None,
            )

        verdict, category = self._inner(text)
        self._misses += 1
        self._seen[key] = [verdict.value, category.value if category else None]
        if self._misses % FLUSH_EVERY == 0:
            self.flush()
        return verdict, category

    def flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._seen, indent=0, sort_keys=True), encoding="utf-8"
        )
