"""The latency and cost harness, driven with a fake client.

The thing under test is the arithmetic and the honesty of the report, both of
which have to be right before the tool is allowed to spend money. In particular
a percentile from a small sample must not be presented as a measurement, and the
per-turn cost must not be the per-call cost, because the lexicon answers some
turns without a model call at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from wayfinder.eval.latency import (
    PRICES,
    Call,
    Reach,
    _Recorder,
    measure_reach,
    percentile,
    render,
    summarise,
    supports_percentile,
)
from wayfinder.safety.loader import load_lexicon

OPUS = "claude-opus-5"


def call(seconds: float, *, inp: int = 1450, out: int = 90, ok: bool = True) -> Call:
    return Call(
        seconds=seconds,
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=0,
        cache_write_tokens=0,
        ok=ok,
        text_chars=120,
    )


# --- percentiles --------------------------------------------------------------


def test_percentile_returns_an_observed_value_rather_than_an_interpolation() -> None:
    """Interpolating invents a number that was never measured and then reports
    it to three decimal places."""
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.5) in values
    assert percentile(values, 1.0) == 4.0
    assert percentile(values, 0.0) == 1.0


def test_percentile_of_nothing_is_not_zero() -> None:
    """Zero would read as an instantaneous call."""
    import math

    assert math.isnan(percentile([], 0.5))


@pytest.mark.parametrize(
    ("n", "fraction", "supported"),
    [
        (40, 0.90, True),  # 4 expected observations in the tail
        (40, 0.95, True),  # 2
        (40, 0.99, False),  # 0.4, so p99 would just be the maximum
        (100, 0.99, True),
        (0, 0.50, False),
        # Exactly on the boundary. `1.0 - 0.90` is 0.09999999999999998, so
        # without rounding this lands just under 1 and reports as unsupported.
        (10, 0.90, True),
        (20, 0.95, True),
        (9, 0.90, False),
    ],
)
def test_a_sample_only_speaks_to_percentiles_it_is_big_enough_for(
    n: int, fraction: float, supported: bool
) -> None:
    assert supports_percentile(n, fraction) is supported


def test_the_report_marks_a_percentile_the_sample_cannot_support() -> None:
    """The number is still printed, because hiding it is worse, but it is
    labelled as the maximum wearing a percentile's name."""
    calls = [call(1.0 + i / 10) for i in range(10)]  # supports p90, not p95
    text = render(summarise(calls, Reach(100, 90, 10), OPUS))
    assert "cannot speak to p95" in text
    assert "cannot speak to p90" not in text, "10 samples do support p90"


# --- cost ---------------------------------------------------------------------


def test_cost_per_call_is_priced_from_the_stated_table() -> None:
    price = PRICES[OPUS]
    result = summarise([call(1.0, inp=1000, out=100)], Reach(10, 10, 0), OPUS)
    expected = (1000 * price.input_per_mtok + 100 * price.output_per_mtok) / 1_000_000
    assert result.cost["per_call"] == pytest.approx(expected)


def test_cost_per_turn_is_lower_than_cost_per_call() -> None:
    """The distinction the whole harness exists for.

    The lexicon answers some turns without consulting the model, so those turns
    cost nothing. Reporting the call cost as the turn cost overstates the bill.
    """
    result = summarise(
        [call(1.0)], Reach(turns=100, reached_model=80, caught_by_lexicon=20), OPUS
    )
    assert result.cost["per_turn"] == pytest.approx(result.cost["per_call"] * 0.8)
    assert result.cost["per_1000_turns"] == pytest.approx(
        result.cost["per_turn"] * 1000
    )


def test_an_unpriced_model_reports_no_cost_rather_than_a_guess() -> None:
    result = summarise([call(1.0)], Reach(10, 10, 0), "some-model-nobody-priced")
    assert result.cost == {}
    assert "no cost is reported" in render(result)


def test_the_caching_projection_is_cheaper_and_labelled_as_a_projection() -> None:
    """The shipped code sends no cache_control, so this number is arithmetic
    about a change nobody has made. It must not read as measured."""
    result = summarise([call(1.0)], Reach(100, 100, 0), OPUS)
    assert result.cost["per_call_if_cached_projected"] < result.cost["per_call"]
    assert "Projected, not measured" in render(result)


# --- the timeout tail ---------------------------------------------------------


def test_calls_over_the_timeout_are_counted_and_explained() -> None:
    """A call over 8s is not an error, it is an unscreened turn, and the report
    has to say that rather than showing a tidy latency table."""
    calls = [call(1.0), call(9.5), call(2.0)]
    result = summarise(calls, Reach(10, 10, 0), OPUS)
    assert result.over_timeout == 1
    assert "went unscreened" in render(result)


# --- reach --------------------------------------------------------------------


def test_reach_counts_the_turns_the_lexicon_answers_on_its_own() -> None:
    from wayfinder.eval.corpus import LabelledTurn
    from wayfinder.safety import QuestionClass

    lexicon = load_lexicon()
    turns = (
        LabelledTurn(
            text="I am going to kill myself tonight", label=QuestionClass.CRISIS
        ),
        LabelledTurn(
            text="how do I apply for a PPS number", label=QuestionClass.PROCEDURAL
        ),
    )
    reach = measure_reach(turns, lexicon)

    assert reach.turns == 2
    assert reach.caught_by_lexicon == 1
    assert reach.reached_model == 1
    assert reach.rate == pytest.approx(0.5)


def test_the_report_says_the_reach_rate_is_a_floor() -> None:
    """Measured on a corpus built to be mostly crisis turns, which is where the
    lexicon fires. Live traffic is mostly procedural, so more of it pays."""
    assert "floor" in render(summarise([call(1.0)], Reach(100, 90, 10), OPUS))


# --- the recorder -------------------------------------------------------------


class _FakeMessages:
    def __init__(self, usage: Any, fail: bool = False) -> None:
        self._usage = usage
        self._fail = fail

    def create(self, **_: Any) -> Any:
        if self._fail:
            msg = "boom"
            raise RuntimeError(msg)
        return type("Response", (), {"usage": self._usage})()


class _FakeClient:
    def __init__(self, usage: Any, fail: bool = False) -> None:
        self.messages = _FakeMessages(usage, fail)


def test_the_recorder_captures_usage_from_the_real_call() -> None:
    usage = type(
        "Usage",
        (),
        {"input_tokens": 1400, "output_tokens": 80, "cache_read_input_tokens": 0},
    )()
    recorder = _Recorder(_FakeClient(usage))
    recorder.about_to_send("a turn")
    recorder.create(model="x")

    assert len(recorder.calls) == 1
    assert recorder.calls[0].input_tokens == 1400
    assert recorder.calls[0].output_tokens == 80
    assert recorder.calls[0].seconds >= 0
    assert recorder.calls[0].ok


def test_a_failed_call_is_recorded_rather_than_dropped() -> None:
    """A run where half the calls time out and the other half are fast has a
    very different meaning from a fast run, and dropping the failures makes the
    two look identical."""
    recorder = _Recorder(_FakeClient(None, fail=True))
    recorder.about_to_send("a turn")
    with pytest.raises(RuntimeError):
        recorder.create(model="x")

    assert len(recorder.calls) == 1
    assert not recorder.calls[0].ok

    result = summarise(recorder.calls, Reach(10, 10, 0), OPUS)
    assert result.failed == 1
    assert result.latency == {}


def test_failed_calls_do_not_enter_the_latency_distribution() -> None:
    """A call that raised after 0.2s did not take 0.2s to answer, it did not
    answer. Averaging it in makes the screen look faster than it is."""
    calls = [call(5.0), call(0.2, ok=False), call(5.0)]
    result = summarise(calls, Reach(10, 10, 0), OPUS)
    assert result.latency["min"] == 5.0
    assert result.failed == 1


def test_the_caching_projection_states_the_traffic_it_depends_on() -> None:
    """The projection assumes a warm cache on every call.

    A 5-minute cache write costs 1.25x base input against a read at 0.1x, so
    below a couple of calls per window every call pays the write premium and
    caching costs more than not caching. For a service as quiet as this one
    that is the likely case, so the number has to travel with its condition.
    """
    result = summarise([call(1.0)], Reach(100, 90, 10), OPUS)
    breakeven = result.cost["cache_breakeven_calls_per_window"]

    # 1.25x write, 0.1x read: (1.25 - 0.1) / (1 - 0.1)
    assert breakeven == pytest.approx(1.15 / 0.9)
    assert result.cost["cache_breakeven_calls_per_hour"] == pytest.approx(
        breakeven * 12
    )
    assert "calls per 5 minutes" in render(result)


def test_the_breakeven_is_the_point_where_caching_stops_costing_more() -> None:
    """Checked against the arithmetic it claims to summarise rather than
    against itself."""
    price = PRICES[OPUS]
    write = price.cache_write_5m_per_mtok / price.input_per_mtok
    read = price.cache_read_per_mtok / price.input_per_mtok
    breakeven = summarise([call(1.0)], Reach(10, 10, 0), OPUS).cost[
        "cache_breakeven_calls_per_window"
    ]

    just_below = breakeven - 0.05
    just_above = breakeven + 0.05
    for count, cached_should_win in ((just_below, False), (just_above, True)):
        cached = write + read * (count - 1)
        uncached = count
        assert (cached < uncached) is cached_should_win


# --- the command line, driven with a fake client ------------------------------
#
# This is the path that spends money, so it is the path that most needs to work
# before it is pointed at a real key.


class _FakeUsage:
    input_tokens = 2000
    output_tokens = 40
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _SchemaClient:
    """Returns the shape `AnthropicCrisisScreen` expects, so the real adapter
    parses a real response rather than being stubbed out."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        block = type("Block", (), {"type": "text", "text": '{"crisis": false}'})()
        return type(
            "Response",
            (),
            {"content": [block], "usage": _FakeUsage(), "stop_reason": "end_turn"},
        )()


def test_dry_run_makes_no_api_calls_at_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The point of the flag: price the run before paying for it. If this ever
    constructs a client, somebody gets billed for asking what it would cost."""
    from wayfinder.eval import latency

    def explode(_: str) -> Any:
        raise AssertionError("--dry-run built a client")

    monkeypatch.setattr(latency, "_client", explode)
    assert latency.main(["--dry-run"]) == latency.EXIT_OK

    out = capsys.readouterr().out
    assert "Reach rate" in out


def test_a_run_measures_the_shipped_adapter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    from wayfinder.eval import latency

    fake = _SchemaClient()
    monkeypatch.setattr(latency, "_client", lambda _: fake)
    saved = tmp_path / "records.json"

    assert latency.main(["--limit", "5", "--save", str(saved)]) == latency.EXIT_OK

    out = capsys.readouterr().out
    assert "Latency over 5 sequential calls" in out
    assert "per 1,000 turns" in out

    # Six calls were made and five were measured: the warm-up is discarded, so a
    # TLS handshake is not reported as a cost every turn pays.
    assert len(fake.sent) == 6

    import json

    records = json.loads(saved.read_text(encoding="utf-8"))
    assert len(records["calls"]) == 5


def test_the_system_prompt_actually_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the cost numbers. If the harness sent a shorter prompt than the
    shipped screen does, every token count and every dollar would be wrong."""
    from wayfinder.eval import latency
    from wayfinder.safety.llm import SYSTEM_PROMPT

    fake = _SchemaClient()
    monkeypatch.setattr(latency, "_client", lambda _: fake)
    latency.main(["--limit", "2"])

    assert fake.sent[0]["system"] == SYSTEM_PROMPT


def test_effort_none_is_omitted_rather_than_sent_as_a_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Haiku 4.5 returns a 400 when the effort parameter is present, so 'none'
    has to mean absent, not the word."""
    from wayfinder.eval import latency

    fake = _SchemaClient()
    monkeypatch.setattr(latency, "_client", lambda _: fake)
    latency.main(["--limit", "2", "--effort", "none"])

    assert "effort" not in fake.sent[0]["output_config"]


def test_a_missing_corpus_is_exit_2_rather_than_a_crash(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    from wayfinder.eval import latency

    code = latency.main(["--dry-run", "--corpus", str(tmp_path / "nope")])

    assert code == latency.EXIT_CANNOT_EVALUATE
    assert "could not evaluate" in capsys.readouterr().err


def test_a_failed_warm_up_stops_before_spending_the_rest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """If the first call cannot work, the other forty will not either, and
    finding that out one call at a time is how a run wastes a budget."""
    from wayfinder.eval import latency

    class Broken:
        def __init__(self) -> None:
            self.calls = 0
            self.messages = self

        def create(self, **_: Any) -> Any:
            self.calls += 1
            msg = "no"
            raise RuntimeError(msg)

    broken = Broken()
    monkeypatch.setattr(latency, "_client", lambda _: broken)

    code = latency.main(["--limit", "40"])

    assert code == latency.EXIT_CANNOT_EVALUATE
    assert broken.calls == 1, "it kept paying after the warm-up failed"
    assert "warm-up call failed" in capsys.readouterr().err
