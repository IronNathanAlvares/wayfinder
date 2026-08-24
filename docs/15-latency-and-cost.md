# 15. What the crisis screen costs

**Measured 24 August 2026.** Records in
[`tests/corpus/measurements/`](../tests/corpus/measurements/), reproducible with
`uv run wayfinder-latency`.

ADR-0006 puts a model call in front of every turn and ADR-0008 says that call
has to be Opus. Both decisions were made on recall alone. Recall does not say
how long somebody waits, or what it costs to keep the thing running, and until
now neither number existed.

---

## 1. The answer

| | Opus 5 (shipped) | Haiku 4.5 |
|---|---|---|
| Latency p50 | **2.24 s** | 1.04 s |
| Latency p90 | 3.07 s | 1.38 s |
| Latency max, 40 calls | 4.58 s | 2.95 s |
| Calls over the 8 s timeout | **0 of 40** | 0 of 40 |
| Input tokens per call | 2,051 | 1,513 |
| Output tokens per call | 42 | 14 |
| **Cost per turn** | **$0.0102** | $0.0014 |
| Cost per 1,000 turns | **$10.17** | $1.43 |
| Held-out recall (ADR-0008) | **0.975** | 0.856 |

Forty sequential calls each, through the shipped `AnthropicCrisisScreen` rather
than a reimplementation of it, one warm-up call discarded so a TLS handshake is
not counted as a cost the second turn of a session pays.

**Somebody waits about 2.2 seconds before anything at all happens**, and a
thousand turns costs about ten dollars.

---

## 2. Almost all of the wait is the model

The rest of a turn was measured over 100 local runs with the model screen
disabled: retrieval, the plan build, classification, composition, the graph.

| | |
|---|---|
| Everything except the model, p50 | **3 ms** |
| The model call, p50 | 2,240 ms |

The model is **99.87 percent** of the wait. That is worth stating plainly because
it closes off a whole category of optimisation: there is nothing to tune in the
plan engine or in retrieval that a person would ever notice. Any latency work on
this system is work on the model call or it is nothing.

---

## 3. The tail is a safety property, not a comfort one

`DEFAULT_TIMEOUT_SECONDS` is 8. A call that exceeds it does not raise and does
not fail the turn. `full_screen` catches it and returns `DEGRADED`, which means
**that turn was not screened**.

So the far tail of this distribution is not a latency complaint. It is the rate
at which the crisis screen silently stops working, and p50 says nothing about
it. That is why the harness reports the maximum and counts timeouts rather than
reporting an average and stopping.

Nothing came close in this sample: the slowest of 40 calls was 4.58 s, which
leaves 3.4 s of headroom. But **40 samples cannot speak to p99** — there is less
than one expected observation out of 40 in that tail — and the tool says so on
the line rather than printing a number that reads like a measurement. What can
honestly be said is that no call in 40 exceeded half the timeout, and that a
real deployment needs this monitored rather than sampled.

---

## 4. Cost per turn is not cost per call

`full_screen` consults the lexicon first and returns without calling the model
when the lexicon fires. Those turns cost nothing.

| | |
|---|---|
| Turns in the eval corpus | 2,371 |
| Caught by the lexicon, no model call | 239 |
| Reached the model | 2,132 |
| Reach rate | 0.899 |

**That 0.899 is a floor, not an estimate of live traffic.** It is measured on a
corpus deliberately built to be mostly crisis turns, and the lexicon only fires
on crisis language. Real traffic is mostly procedural, where the lexicon almost
never fires, so closer to every turn pays for a call. Read $0.0102 per turn as
very nearly the $0.0113 per call.

---

## 5. What the ADR-0008 decision actually costs

ADR-0008 chose Opus over Haiku for recall: 0.975 against 0.856, paired
p = 0.0000, with self-harm going from 0.648 to every one of 54 items. The price
of that choice was never quantified. It is:

**7.1x the money and 2.15x the wait, for 0.12 recall.**

Put in the units that matter, and keeping the two denominators apart because
they are not the same one: **of every 100 crisis turns, Haiku misses about 14
and Opus misses about 2.5.** The cost of closing that gap is $8.74 per thousand
turns of *all* traffic, and 1.2 seconds added to every turn.

How those trade depends on how much of the traffic is crisis, which nobody
knows for this system yet. It does not need to be known. Even if crisis turns
were one in a thousand, the arithmetic is a few dollars against recognising
somebody who is describing a plan to end their life, and that is not a close
call in any direction. **The decision stands, and now it stands on numbers.**

Part of the cost gap is not the rate card. Opus 5 uses a newer tokenizer that
produces about 30 percent more tokens for the same text, and that shows up
directly: 2,051 input tokens against Haiku's 1,513 for identical prompts, a
factor of 1.36. So the 5x rate difference becomes about 7x in practice. Worth
knowing before anybody estimates a bill from a rate card alone.

---

## 6. Prompt caching would cut the bill by 81 percent, if there is traffic

The system prompt is 2,000-odd tokens, it is identical on every call, and it is
almost the entire input. The shipped code sends no `cache_control`.

| Per 1,000 turns | Opus 5 |
|---|---|
| As shipped | $10.17 |
| With the system prompt cached | **$1.93** |

**That number carries a condition, and the condition is the whole decision.** It
assumes every call finds a warm cache. A 5-minute cache write costs 1.25x base
input where a read costs 0.1x, so caching only pays above about **1.3 calls per
five minutes, roughly 15 an hour**. Below that the cache is cold on arrival,
every call pays the write premium, and caching costs *more* than not caching.

For a service that might see a handful of turns a day at an NGO, that is a
realistic failure mode rather than a footnote. The change is worth making for a
deployment with sustained traffic and worth skipping for a quiet one, and it is
not implemented precisely because which of those applies is not yet known.

---

## 7. What this does not measure

**One caller at a time.** Calls were sequential, which is the shape of a single
person taking a turn. Nothing here says what happens under concurrency, rate
limits, or contention.

**One region, one afternoon.** Latency is a property of a network path on a day.
A second run would differ, and a deployment needs this monitored continuously
rather than sampled once.

**p99 is not established.** Forty calls cannot support it. That matters more
than usual here, because p99 is where the screen degrades.

**No retry costs.** The client is configured with `max_retries=1`. A retried
call bills twice and waits twice, and none of the 40 calls retried.

---

## 8. Reproducing it

```bash
uv run wayfinder-latency --dry-run
```

The free half: the reach rate over the whole corpus and a price estimate for the
paid run, with no API calls at all. Then:

```bash
uv run wayfinder-latency --limit 40 --save results.json
```

```bash
uv run wayfinder-latency --model claude-haiku-4-5-20251001 --effort none --limit 40
```

Haiku needs `--effort none`; it returns a 400 when the effort parameter is sent.
