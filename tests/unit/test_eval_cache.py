"""The eval verdict cache.

It exists because two paid runs were lost to interruptions. What it has to get
right is narrow: never serve a verdict that was produced by a different prompt
or model, never persist a failure, and keep what was already paid for when the
process dies partway.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from wayfinder.eval.cache import CachedScreen
from wayfinder.safety.escalation import ModelVerdict
from wayfinder.safety.models import CrisisCategory


class Counting:
    """A screen that records how often it was actually called."""

    def __init__(
        self,
        verdict: ModelVerdict = ModelVerdict.CRISIS,
        category: CrisisCategory | None = CrisisCategory.SELF_HARM,
    ) -> None:
        self.calls = 0
        self._verdict = verdict
        self._category = category

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        self.calls += 1
        return self._verdict, self._category


class Exploding:
    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        msg = "the model declined to screen this turn"
        raise ValueError(msg)


def screen(inner: object, tmp_path: Path, **kwargs: str) -> CachedScreen:
    return CachedScreen(
        inner,
        path=kwargs.pop("path_", None) or tmp_path / "cache.json",  # type: ignore[arg-type]
        model=kwargs.pop("model", "m1"),
        prompt=kwargs.pop("prompt", "p1"),
    )


def test_a_repeated_turn_is_not_paid_for_twice(tmp_path: Path) -> None:
    inner = Counting()
    cache = screen(inner, tmp_path)

    first = cache("i have nowhere to sleep")
    second = cache("i have nowhere to sleep")

    assert first == second
    assert inner.calls == 1
    assert cache.hits == 1


def test_the_verdict_survives_a_new_process(tmp_path: Path) -> None:
    """The whole point. A run that dies partway keeps what it paid for."""
    inner = Counting()
    first = screen(inner, tmp_path)
    first("something")
    first.flush()

    second = screen(Counting(), tmp_path)
    verdict, category = second("something")

    assert verdict is ModelVerdict.CRISIS
    assert category is CrisisCategory.SELF_HARM
    assert second.calls_made == 0


def test_a_different_prompt_never_reads_the_old_answer(tmp_path: Path) -> None:
    """The failure that would quietly invalidate an A/B: the new prompt served
    the old prompt's verdicts and scoring identically to it."""
    inner = Counting()
    screen(inner, tmp_path, prompt="v1")("same turn")

    other = screen(inner, tmp_path, prompt="v2")
    other("same turn")

    assert inner.calls == 2
    assert other.hits == 0


def test_a_different_model_never_reads_the_old_answer(tmp_path: Path) -> None:
    inner = Counting()
    screen(inner, tmp_path, model="haiku")("same turn")

    other = screen(inner, tmp_path, model="opus")
    other("same turn")

    assert inner.calls == 2


def test_editing_a_prompt_without_renaming_it_is_still_a_new_key(
    tmp_path: Path,
) -> None:
    """The prompt is hashed in full rather than named. Somebody who edits `v2`
    in place gets fresh calls rather than last week's answers."""
    inner = Counting()
    screen(inner, tmp_path, prompt="you are a screen")("turn")
    screen(inner, tmp_path, prompt="you are a screen.")("turn")

    assert inner.calls == 2


def test_a_failure_is_never_remembered(tmp_path: Path) -> None:
    """A degraded screen is a transient condition. Caching it would turn one
    network blip into a permanent hole in every later measurement."""
    cache = screen(Exploding(), tmp_path)
    with pytest.raises(ValueError, match="declined"):
        cache("turn")
    cache.flush()

    inner = Counting()
    recovered = screen(inner, tmp_path)
    recovered("turn")

    assert inner.calls == 1, "a failure was served from the cache"


def test_a_no_opinion_verdict_round_trips(tmp_path: Path) -> None:
    """The common case by volume, and the one where a category of None has to
    survive the JSON round trip as None rather than as a string."""
    inner = Counting(ModelVerdict.NO_OPINION, None)
    first = screen(inner, tmp_path)
    first("a calm question")
    first.flush()

    verdict, category = screen(Counting(), tmp_path)("a calm question")
    assert verdict is ModelVerdict.NO_OPINION
    assert category is None


def test_a_missing_cache_file_is_a_cold_start_rather_than_an_error(
    tmp_path: Path,
) -> None:
    cache = CachedScreen(
        Counting(), path=tmp_path / "deep" / "nope.json", model="m", prompt="p"
    )
    assert cache("turn")
    cache.flush()
    assert (tmp_path / "deep" / "nope.json").is_file()


def test_verdicts_are_flushed_before_the_run_finishes(tmp_path: Path) -> None:
    """Ten calls in, there is already something on disk. Waiting until the end
    is what lost the first two runs."""
    path = tmp_path / "cache.json"
    cache = CachedScreen(Counting(), path=path, model="m", prompt="p")
    for i in range(12):
        cache(f"turn {i}")

    assert path.is_file(), "nothing was written until the run ended"


def test_an_empty_salt_does_not_change_the_key(tmp_path: Path) -> None:
    """Adding the salt parameter must not invalidate what is already cached.

    Hashing an empty salt as an empty string changes every digest, which would
    silently re-pay for a thousand calls the next time anything ran. Pinned
    against a literal so a future refactor of the key cannot do it again.
    """
    from wayfinder.eval.cache import _key

    assert _key("m", "p", "t") == _key("m", "p", "t", "")
    assert _key("m", "p", "t") != _key("m", "p", "t", "1")
    assert _key("m", "p", "t", "1") != _key("m", "p", "t", "2")
    # The historical three-part digest, recomputed rather than pasted, so a
    # refactor of the key cannot quietly invalidate an existing cache again.
    historical = hashlib.sha256()
    for part in ("m", "p", "t"):
        historical.update(part.encode())
        historical.update(bytes([0]))
    assert _key("m", "p", "t") == historical.hexdigest()


def test_samples_of_the_same_turn_are_kept_apart(tmp_path: Path) -> None:
    """Repeated sampling asks the same model the same question deliberately.
    Without the salt the second sample would read the first one's answer and
    the union would be over one verdict repeated N times."""
    inner = Counting()
    first = CachedScreen(inner, path=tmp_path / "c.json", model="m", prompt="p")
    second = CachedScreen(
        inner, path=tmp_path / "c.json", model="m", prompt="p", salt="1"
    )
    first("same turn")
    first.flush()
    second("same turn")

    assert inner.calls == 2
    assert second.hits == 0
