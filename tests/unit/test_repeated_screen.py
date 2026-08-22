"""Repeated sampling with a union, driven offline.

The arithmetic of a union is trivial. What these check is the part that is not:
that N samples really means N, that a failure does not quietly reduce it, and
that the category somebody is shown does not depend on which thread finished
first.
"""

from __future__ import annotations

import pytest

from wayfinder.safety.escalation import ModelVerdict, ScreenOutcome, full_screen
from wayfinder.safety.loader import load_lexicon
from wayfinder.safety.models import CrisisCategory, CrisisLexicon
from wayfinder.safety.repeated import DEFAULT_SAMPLES, RepeatedScreen


class _Says:
    """A screen with a scripted answer, and a count of how often it was asked."""

    def __init__(
        self,
        verdict: ModelVerdict,
        category: CrisisCategory | None = None,
        *,
        raises: bool = False,
    ) -> None:
        self.verdict = verdict
        self.category = category
        self.raises = raises
        self.calls = 0

    def __call__(self, text: str) -> tuple[ModelVerdict, CrisisCategory | None]:
        self.calls += 1
        if self.raises:
            msg = "this sample failed"
            raise ValueError(msg)
        return self.verdict, self.category


def _quiet() -> _Says:
    return _Says(ModelVerdict.NO_OPINION)


def _fires(category: CrisisCategory) -> _Says:
    return _Says(ModelVerdict.CRISIS, category)


@pytest.fixture(scope="module")
def lexicon() -> CrisisLexicon:
    return load_lexicon()


def test_one_sample_out_of_three_is_enough_to_escalate() -> None:
    """The whole point. A turn the screen usually misses but sometimes catches
    is a turn this converts into a catch."""
    verdict, category = RepeatedScreen(
        [_quiet(), _fires(CrisisCategory.SELF_HARM), _quiet()]
    )("i am giving my things away")

    assert verdict is ModelVerdict.CRISIS
    assert category is CrisisCategory.SELF_HARM


def test_no_sample_firing_is_no_opinion() -> None:
    verdict, category = RepeatedScreen([_quiet() for _ in range(3)])("how do i apply")
    assert verdict is ModelVerdict.NO_OPINION
    assert category is None


def test_every_sample_is_actually_asked() -> None:
    """N samples has to mean N calls. Short-circuiting on the first escalation
    would make the measured cost of this arm a fiction, and the whole question
    is whether the cost is worth it."""
    screens = [_quiet() for _ in range(3)]
    screens[0] = _fires(CrisisCategory.MEDICAL)
    RepeatedScreen(screens)("anything")

    assert [s.calls for s in screens] == [1, 1, 1]


def test_the_category_does_not_depend_on_which_thread_finished_first() -> None:
    """The category decides which phone number somebody is given. Taking
    whichever sample returned first would make that vary between identical
    runs."""
    screens = [
        _quiet(),
        _fires(CrisisCategory.DETENTION),
        _fires(CrisisCategory.ROUGH_SLEEPING),
    ]
    for _ in range(10):
        _, category = RepeatedScreen(screens)("anything")
        assert category is CrisisCategory.DETENTION


def test_a_single_failed_sample_fails_the_whole_screen() -> None:
    """Taking the union of the samples that answered would let a network blip
    quietly reduce N, and N is the only thing this class is for."""
    with pytest.raises(ValueError, match="this sample failed"):
        RepeatedScreen([_quiet(), _Says(ModelVerdict.NO_OPINION, raises=True)])("x")


def test_a_failure_degrades_the_screen_rather_than_clearing_it(
    lexicon: CrisisLexicon,
) -> None:
    result = full_screen(
        "how do i register with a gp",
        lexicon,
        model=RepeatedScreen([_quiet(), _Says(ModelVerdict.NO_OPINION, raises=True)]),
    )
    assert result.outcome is ScreenOutcome.DEGRADED
    assert not result.screening_was_complete


def test_a_failure_still_degrades_even_when_another_sample_escalated() -> None:
    """Escalating on the sample that answered would look like the safe
    direction and would hide that N was not what it claimed."""
    with pytest.raises(ValueError, match="failed"):
        RepeatedScreen(
            [
                _fires(CrisisCategory.VIOLENCE),
                _Says(ModelVerdict.NO_OPINION, raises=True),
            ]
        )("anything")


def test_the_lexicon_still_runs_first(lexicon: CrisisLexicon) -> None:
    """The property the design rests on. A union of screens that can only add a
    detection still only adds."""
    screens = [_quiet() for _ in range(3)]
    result = full_screen(
        "i want to kill myself", lexicon, model=RepeatedScreen(screens)
    )

    assert result.is_crisis
    assert result.outcome is ScreenOutcome.LEXICON
    assert [s.calls for s in screens] == [0, 0, 0], "the model was consulted at all"


def test_an_empty_repeat_is_refused() -> None:
    """Zero samples is a screen that never escalates, which would read as a
    perfectly precise one."""
    with pytest.raises(ValueError, match="at least one"):
        RepeatedScreen([])


def test_the_sample_count_is_fixed_in_advance() -> None:
    """Three, chosen from cost before the measurement rather than tuned to it.
    A default that moved after seeing a result would be a fitted parameter."""
    assert DEFAULT_SAMPLES == 3
    assert RepeatedScreen([_quiet() for _ in range(3)]).samples == 3


# --- how the runner names the arm --------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("union-3:v4", (3, "v4")),
        ("union-1:v5", (1, "v5")),
        ("union-12:v2", (12, "v2")),
        ("v4", None),
        ("per-category", None),
        ("union-3", None),
        ("union-0:v4", None),
        ("union-x:v4", None),
        ("union-3:nope", None),
    ],
)
def test_the_union_arm_name_is_parsed_strictly(
    name: str, expected: tuple[int, str] | None
) -> None:
    """A name that half-parses would run a different arm than the one written
    on the command line, and the label in the report would say the wrong thing.
    """
    from wayfinder.eval.compare import _is_union

    assert _is_union(name, {"v2": "", "v4": "", "v5": ""}) == expected
