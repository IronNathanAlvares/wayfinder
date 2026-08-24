"""What the crisis screen costs a person who is waiting, and what it costs to run.

ADR-0006 puts a model call in front of every turn, and ADR-0008 says that call
has to be Opus. Both decisions were made on recall alone. This measures the two
things recall does not say: how long somebody waits for it, and what it costs
per turn.

Three things make this worth its own harness rather than a stopwatch.

**The screen does not run on every turn.** `full_screen` consults the lexicon
first and returns without calling the model when the lexicon fires. So the cost
per *turn* is the cost per *call* times the fraction of turns that reach the
model, and that fraction is computable offline for nothing. Reporting the call
cost as the turn cost would overstate it.

**The timeout is the interesting tail.** `DEFAULT_TIMEOUT_SECONDS` is 8. A call
that exceeds it does not fail the turn, it returns `DEGRADED`, which means the
turn was not screened. So the latency distribution is not a comfort question:
the far tail is the rate at which the safety layer silently stops working, and
p50 tells you nothing about it.

**The real adapter is measured, not a copy of it.** The client is wrapped rather
than reimplemented, so `AnthropicCrisisScreen` runs exactly as it does in
production, including its schema handling and its retry.

Costs come from a stated price table rather than from anything inferred, and the
table is printed with the result so a stale price is visible rather than baked
into a number somebody quotes later.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from wayfinder.eval.corpus import (
    CRISIS_HOLDOUT_V4_SPLIT,
    EvalError,
    LabelledTurn,
    by_split,
    load_corpus,
)
from wayfinder.safety.crisis import screen
from wayfinder.safety.llm import (
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    SYSTEM_PROMPT,
    AnthropicCrisisScreen,
)
from wayfinder.safety.loader import SafetyDataError, load_lexicon

CORPUS: Final = (
    Path(__file__).resolve().parent.parent.parent.parent / "tests" / "corpus"
)

EXIT_OK: Final = 0
EXIT_CANNOT_EVALUATE: Final = 2


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens. Stated, not inferred.

    Printed with every result. A price table that lives only in a constant is a
    number somebody quotes two years later without knowing it moved.
    """

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_5m_per_mtok: float
    source: str


# https://platform.claude.com/docs/en/about-claude/pricing, read 2026-08-24.
PRICES: Final[dict[str, Price]] = {
    "claude-opus-5": Price(5.0, 25.0, 0.50, 6.25, "platform.claude.com, 2026-08-24"),
    "claude-haiku-4-5-20251001": Price(
        1.0, 5.0, 0.10, 1.25, "platform.claude.com, 2026-08-24"
    ),
}


@dataclass
class Call:
    """One screen call, as it actually happened."""

    seconds: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    ok: bool
    text_chars: int


class _Recorder:
    """Wraps the real client so the shipped adapter is what gets measured.

    `AnthropicCrisisScreen` takes a client and calls `client.messages.create`.
    Standing in the middle of that is the only way to see both the wall time the
    caller experiences and the token usage the bill is computed from, without
    reimplementing the call and measuring the copy instead.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[Call] = []
        self._chars = 0

    @property
    def messages(self) -> _Recorder:
        return self

    def about_to_send(self, text: str) -> None:
        self._chars = len(text)

    def create(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        ok = True
        response = None
        try:
            response = self._inner.messages.create(**kwargs)
        except Exception:
            ok = False
            raise
        finally:
            elapsed = time.perf_counter() - started
            usage = getattr(response, "usage", None)
            self.calls.append(
                Call(
                    seconds=elapsed,
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                    cache_read_tokens=int(
                        getattr(usage, "cache_read_input_tokens", 0) or 0
                    ),
                    cache_write_tokens=int(
                        getattr(usage, "cache_creation_input_tokens", 0) or 0
                    ),
                    ok=ok,
                    text_chars=self._chars,
                )
            )
        return response


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank, which does not invent a value between two observations.

    Interpolating would produce a p99 from 40 samples that reads as a
    measurement. It is not one, and `supports_percentile` is what says so.
    """
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return ordered[rank - 1]


def supports_percentile(n: int, fraction: float) -> bool:
    """Whether n observations can speak to this percentile at all.

    A p99 from 40 samples is the maximum with a different name on it. Requiring
    at least one expected observation in the tail is the weakest honest bar.

    Rounded before comparing because `1.0 - 0.90` is 0.09999999999999998, which
    put n=10 on the wrong side of its own boundary for p90.
    """
    return n > 0 and round(n * (1.0 - fraction), 9) >= 1.0


@dataclass
class Reach:
    """How often a turn gets as far as the model."""

    turns: int
    reached_model: int
    caught_by_lexicon: int

    @property
    def rate(self) -> float:
        return self.reached_model / self.turns if self.turns else 0.0


def measure_reach(turns: Sequence[LabelledTurn], lexicon: Any) -> Reach:
    """Free, offline, and over the whole corpus rather than the paid sample.

    The lexicon runs first and the model is skipped when it fires, so this is
    the multiplier between cost per call and cost per turn. Costs nothing to
    compute, so there is no reason to estimate it.
    """
    caught = sum(1 for turn in turns if screen(turn.text, lexicon) is not None)
    return Reach(
        turns=len(turns), reached_model=len(turns) - caught, caught_by_lexicon=caught
    )


@dataclass
class Result:
    model: str
    sampled: int
    failed: int
    latency: dict[str, float] = field(default_factory=dict)
    tokens: dict[str, float] = field(default_factory=dict)
    cost: dict[str, float] = field(default_factory=dict)
    reach: dict[str, float] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    over_timeout: int = 0
    price_source: str = ""


def summarise(calls: Sequence[Call], reach: Reach, model: str) -> Result:
    good = [c for c in calls if c.ok]
    seconds = [c.seconds for c in good]
    price = PRICES.get(model)

    result = Result(
        model=model,
        sampled=len(calls),
        failed=len(calls) - len(good),
        price_source=price.source if price else "unpriced model",
    )
    if not good:
        return result

    result.latency = {
        "min": min(seconds),
        "p50": percentile(seconds, 0.50),
        "mean": statistics.fmean(seconds),
        "p90": percentile(seconds, 0.90),
        "p95": percentile(seconds, 0.95),
        "max": max(seconds),
    }
    result.over_timeout = sum(1 for s in seconds if s > DEFAULT_TIMEOUT_SECONDS)

    result.tokens = {
        "input_mean": statistics.fmean(c.input_tokens for c in good),
        "output_mean": statistics.fmean(c.output_tokens for c in good),
        "cache_read_mean": statistics.fmean(c.cache_read_tokens for c in good),
    }

    result.reach = {
        "turns": reach.turns,
        "reached_model": reach.reached_model,
        "caught_by_lexicon": reach.caught_by_lexicon,
        "rate": reach.rate,
    }

    if price is not None:
        per_call = statistics.fmean(
            (
                c.input_tokens * price.input_per_mtok
                + c.output_tokens * price.output_per_mtok
                + c.cache_read_tokens * price.cache_read_per_mtok
            )
            / 1_000_000
            for c in good
        )
        # The system prompt is identical on every call and is most of the input,
        # so caching it is the obvious lever. Projected rather than measured:
        # the shipped code sends no `cache_control`, and this says what turning
        # it on would be worth before anybody spends a round measuring it.
        cached = statistics.fmean(
            (
                max(0, c.input_tokens - _system_tokens(c)) * price.input_per_mtok
                + _system_tokens(c) * price.cache_read_per_mtok
                + c.output_tokens * price.output_per_mtok
            )
            / 1_000_000
            for c in good
        )
        # Caching is not free below a traffic floor. Writing a 5-minute cache
        # costs 1.25x base input and reading it costs 0.1x, so N calls sharing
        # one window cost 1.25 + 0.1(N-1) against N uncached. Solving for where
        # that turns favourable is the number that decides whether to bother.
        write = price.cache_write_5m_per_mtok / price.input_per_mtok
        read = price.cache_read_per_mtok / price.input_per_mtok
        breakeven = (write - read) / (1.0 - read)
        result.cost = {
            "per_call": per_call,
            "per_turn": per_call * reach.rate,
            "per_1000_turns": per_call * reach.rate * 1000,
            "per_call_if_cached_projected": cached,
            "per_1000_turns_if_cached_projected": cached * reach.rate * 1000,
            "cache_breakeven_calls_per_window": breakeven,
            "cache_breakeven_calls_per_hour": breakeven * 12,
        }
    return result


def _system_tokens(call: Call) -> int:
    """How much of this call's input was the constant system prompt.

    Estimated by subtracting the turn, since the API reports one input total.
    Four characters per token is the documented rough conversion and it is only
    used for the caching projection, never for a measured number.
    """
    turn_estimate = call.text_chars // 4
    return max(0, call.input_tokens - turn_estimate)


def _sample(turns: Sequence[LabelledTurn], limit: int) -> list[LabelledTurn]:
    """An evenly spaced slice, not the first N.

    The splits are written in blocks by category, so the first N would be one
    category measured against a prompt with six sections in it.
    """
    if limit <= 0 or limit >= len(turns):
        return list(turns)
    step = len(turns) / limit
    return [turns[int(i * step)] for i in range(limit)]


def render(result: Result) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"Crisis screen latency and cost: {result.model}")
    add("")

    if not result.latency:
        add(f"No successful calls out of {result.sampled}.")
        return "\n".join(lines)

    n = result.sampled - result.failed
    add(f"Latency over {n} sequential calls, seconds")
    for key in ("min", "p50", "mean", "p90", "p95", "max"):
        value = result.latency[key]
        caveat = ""
        if key.startswith("p") and key != "p50":
            fraction = int(key[1:]) / 100
            if not supports_percentile(n, fraction):
                caveat = f"  (n={n} cannot speak to {key}; this is the maximum)"
        add(f"  {key:<5} {value:6.2f}{caveat}")
    add("")

    add(f"Timeout is {result.timeout_seconds:.0f}s, and a call over it is not an")
    add("error: it returns DEGRADED, which means the turn went unscreened.")
    add(f"  calls over the timeout: {result.over_timeout} of {n}")
    add("")

    add("Tokens per call, mean")
    add(f"  input   {result.tokens['input_mean']:8.0f}")
    add(f"  output  {result.tokens['output_mean']:8.0f}")
    if result.tokens["cache_read_mean"]:
        add(f"  cached  {result.tokens['cache_read_mean']:8.0f}")
    add("")

    reach = result.reach
    add("How often a turn reaches the model")
    add(f"  turns in the corpus     {reach['turns']:.0f}")
    add(f"  caught by the lexicon   {reach['caught_by_lexicon']:.0f}  (no model call)")
    add(f"  reached the model       {reach['reached_model']:.0f}")
    add(f"  reach rate              {reach['rate']:.3f}")
    add("")
    add("  This rate is a floor, not an estimate of live traffic. It is measured")
    add("  on a safety corpus built to be mostly crisis turns, and the lexicon")
    add("  only fires on crisis language. Real traffic is mostly procedural, so")
    add("  the lexicon fires less often and closer to every turn pays the call.")
    add("  Read the per-turn cost below as very nearly the per-call cost.")
    add("")

    if result.cost:
        cost = result.cost
        add(f"Cost, priced from {result.price_source}")
        add(f"  per model call          ${cost['per_call']:.5f}")
        add(f"  per turn                ${cost['per_turn']:.5f}")
        add(f"  per 1,000 turns         ${cost['per_1000_turns']:.2f}")
        add("")
        add("  Projected, not measured. The shipped code sends no cache_control,")
        add("  and the system prompt is identical on every call:")
        add(f"    per call if cached    ${cost['per_call_if_cached_projected']:.5f}")
        add(
            f"    per 1,000 turns       "
            f"${cost['per_1000_turns_if_cached_projected']:.2f}"
        )
        add("")
        add("  And the condition on that projection, which is the part that")
        add("  decides whether it is worth doing at all. It assumes every call")
        add("  finds a warm cache. A 5-minute cache write costs 1.25x base")
        add("  input, a read costs 0.1x, so caching only pays above")
        add(
            f"    {cost['cache_breakeven_calls_per_window']:.2f} calls per 5 minutes"
            f"  (about {cost['cache_breakeven_calls_per_hour']:.0f} per hour)"
        )
        add("  Below that the cache is cold on arrival and every call pays the")
        add("  write premium, which is more than sending it uncached. For a")
        add("  service this quiet that is a real possibility, not a footnote.")
    else:
        add(f"No price on record for {result.model}, so no cost is reported.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wayfinder-latency",
        description="Measure what the crisis screen costs in time and money.",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--split", default=CRISIS_HOLDOUT_V4_SPLIT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="how many calls to make. Each one costs money, so this is small by "
        "default and the report says which percentiles the count supports",
    )
    parser.add_argument(
        "--effort",
        default="low",
        help="effort level, or 'none' for models that reject the parameter. "
        "Haiku 4.5 returns a 400 when it is sent",
    )
    parser.add_argument(
        "--save", type=Path, default=None, help="write every call record here"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="do the free half only: the reach rate and the projected bill, "
        "with no API calls at all",
    )
    args = parser.parse_args(argv)

    try:
        corpus = load_corpus(args.corpus)
        lexicon = load_lexicon()
    except (EvalError, SafetyDataError, OSError) as exc:
        print(f"could not evaluate: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE

    reach = measure_reach(corpus, lexicon)
    turns = _sample(by_split(corpus, args.split), args.limit)

    if args.dry_run:
        price = PRICES.get(args.model)
        print(f"Reach rate {reach.rate:.3f} over {reach.turns} turns.")
        if price:
            # Rough, and labelled as such: the point of the flag is to price a
            # run before paying for it, not to replace the run.
            rough = (len(SYSTEM_PROMPT) // 4) * price.input_per_mtok / 1_000_000
            print(
                f"About {len(turns)} calls at roughly ${rough:.5f} of input each, "
                f"so on the order of ${rough * len(turns):.2f} plus output."
            )
        return EXIT_OK

    recorder = _Recorder(_client(args.model))
    effort = None if args.effort.lower() == "none" else args.effort
    screener = AnthropicCrisisScreen(recorder, model=args.model, effort=effort)

    # One warm-up, discarded. A long-lived client reuses its connection, so
    # folding a TLS handshake into the first sample would report a cost the
    # second turn of any real session does not pay.
    try:
        recorder.about_to_send(turns[0].text)
        screener(turns[0].text)
    except Exception as exc:
        print(f"could not evaluate: the warm-up call failed: {exc}", file=sys.stderr)
        return EXIT_CANNOT_EVALUATE
    recorder.calls.clear()

    for turn in turns:
        recorder.about_to_send(turn.text)
        try:
            screener(turn.text)
        except Exception as exc:  # a failed call is a data point, not a stop
            print(f"  call failed: {type(exc).__name__}", file=sys.stderr)

    result = summarise(recorder.calls, reach, args.model)
    print(render(result))

    if args.save:
        args.save.write_text(
            json.dumps(
                {
                    "result": asdict(result),
                    "calls": [asdict(c) for c in recorder.calls],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nEvery call recorded in {args.save}.")
    return EXIT_OK


def _client(model: str) -> Any:
    import anthropic

    del model
    return anthropic.Anthropic(timeout=DEFAULT_TIMEOUT_SECONDS, max_retries=1)


if __name__ == "__main__":
    raise SystemExit(main())
