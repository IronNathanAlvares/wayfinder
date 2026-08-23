# 14. Getting started

Everything needed to go from a clone to a running system, in the order somebody
new would need it. Every command here has been run against this repository.

Two things are worth knowing before you start, because both will otherwise look
like bugs:

- **`ask` and `serve` refuse to start without an API key.** That is deliberate.
  [ADR-0008](adr/ADR-0008-crisis-recall-needs-a-model.md) measured the
  deterministic crisis screen at 0.167 recall on held-out data, so starting
  quietly with it alone would ship a safety claim the measurements do not
  support. `--no-model-screen` is the way past it, and it prints what it costs.
- **The caseworker queue is shut until somebody is registered.** No credentials
  configured means 503, not open access. See [§6](#6-the-caseworker-queue).

Nothing else here needs an API key. The plan engine, the corpus, the graph, the
deterministic safety layers, the site and the entire test suite run offline.

---

## 1. What you need

| Thing | Version | Why |
|---|---|---|
| Python | 3.12.x | Pinned `>=3.12,<3.13` in `pyproject.toml` |
| [uv](https://docs.astral.sh/uv/) | any recent | The lockfile is `uv.lock`; `pip` will not reproduce it |
| git | any | |
| Docker | optional | Only for §7 |

An `ANTHROPIC_API_KEY` is optional. It buys the model crisis screen and the
evals in §8, and nothing else.

---

## 2. Clone and install

```bash
git clone https://github.com/IronNathanAlvares/wayfinder.git
```

```bash
cd wayfinder
```

The default install is the plan engine and the safety layers, with no web
framework and no model client. That is the point of the import contracts: the
parts carrying the value are usable as a library without any of it.

```bash
uv sync
```

For the API and the model screen as well, which is what you want if you intend
to run the server:

```bash
uv sync --extra api --extra llm
```

`uv sync` creates `.venv` and installs from the lockfile. Prefix commands with
`uv run`, or activate the environment once:

```bash
source .venv/bin/activate
```

On Windows PowerShell that line is `.venv\Scripts\Activate.ps1`. Every example
below uses the `uv run` form, which works either way.

---

## 3. Check it actually works

```bash
uv run pytest -q
```

611 tests, no network, no key, under three minutes. If this passes,
everything in §4 and §5 will work.

The corpus has its own integrity check, worth running separately because it is
the thing most likely to be wrong after an edit:

```bash
uv run wayfinder corpus check
```

`20 tasks, 8 sources, 17 artefacts. No integrity problems.`

---

## 4. The CLI

### Build a plan

Two worked situations ship in `examples/`. The first is Amara from PDD §4, two
weeks after arriving.

```bash
uv run wayfinder plan examples/amara-week-one.yaml
```

You get `Start now`, then `Not yet` with the reason each task is blocked, then
`Questions for you` where the situation is genuinely unknown rather than
assumed. Add `--format json` for the machine-readable form.

A situation file is YAML, and every field is optional because intake asks for a
field only when it changes the plan:

```yaml
arrival_date: 2026-08-01
protection_application_date: 2026-08-04   # not the same as arrival, on purpose
protection_stage: applied
accommodation: homeless
household:
  adults: 1
  children_ages: [7]
held:
  - document:national_id
known_absent:
  - document:ppsn
  - document:proof_of_address
```

Anything absent from both `held` and `known_absent` is genuinely unknown. The
planner asks rather than assuming, which is why `known_absent` exists as a
separate list at all.

### See what changed

```bash
uv run wayfinder diff examples/amara-week-one.yaml examples/amara-six-weeks-later.yaml
```

`You can now start` / `Now done` / `Newly blocked`. This is the command that
shows the plan is a graph rather than a checklist: completing one task unblocks
a set you could not have predicted from the list order.

### Corpus staleness

```bash
uv run wayfinder corpus health
```

Every source with the date it was last verified, bucketed into verify,
downgrade and excluded. A source that ages out is dropped from retrieval rather
than served with a caveat.

### Ask one question

```bash
uv run wayfinder ask --no-model-screen "how do I apply for a PPS number"
```

```bash
uv run wayfinder ask --no-model-screen --situation examples/amara-week-one.yaml "what do I do first?"
```

Now ask an entitlement question and watch it refuse:

```bash
uv run wayfinder ask --no-model-screen "am I entitled to child benefit?"
```

It names somebody who can decide instead of deciding. That refusal is
structural rather than a prompt instruction: see
[ADR-0004](adr/ADR-0004-no-determinations.md).

With a key exported, drop `--no-model-screen` and the real screen runs:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```bash
uv run wayfinder ask "am I entitled to child benefit?"
```

### Exit codes

Three of them, and 1 and 2 are never collapsed:

| Code | Means |
|---|---|
| 0 | Ran, and the verdict is pass |
| 1 | Ran, and the verdict is fail |
| 2 | Could not evaluate: bad config, missing key, unreadable corpus |

A missing API key returning 1 would read as a check that ran and failed. It
returns 2.

---

## 5. The API

```bash
uv run wayfinder serve --no-model-screen --db ./wayfinder.sqlite
```

`--db` is not optional in practice. The handoff this system is built around
lasts days, so the queue has to outlive the process. Interactive docs are at
`http://127.0.0.1:8000/docs`.

Start a thread:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/threads -H 'content-type: application/json' -d '{"thread_id":"amara","situation":{"arrival_date":"2026-08-01","protection_application_date":"2026-08-04","protection_stage":"applied","accommodation":"homeless","household":{"adults":1,"children_ages":[7]},"known_absent":["document:ppsn","document:proof_of_address"]}}'
```

```bash
curl -s http://127.0.0.1:8000/v1/threads/amara/plan
```

```bash
curl -s -X POST http://127.0.0.1:8000/v1/threads/amara/turn -H 'content-type: application/json' -d '{"question":"how do I apply for a PPS number?"}'
```

The situation body is validated with `extra="forbid"`, so a misspelled field is
a 422 rather than a silently ignored fact about somebody's life.

| Endpoint | Auth | What |
|---|---|---|
| `POST /v1/threads` | none | Start a thread with a situation |
| `POST /v1/threads/{id}/turn` | none | Ask one question |
| `GET /v1/threads/{id}/plan` | none | The ordered plan |
| `DELETE /v1/threads/{id}` | none | Forget it (PDD NG5) |
| `GET /v1/queue` | caseworker | Everything waiting on a person |
| `POST /v1/queue/{id}/respond` | caseworker | Answer one, signed |
| `GET /v1/whoami` | caseworker | What your token signs as |
| `GET /v1/corpus/health` | none | 503 once a source has aged out |

`/v1/corpus/health` is an alarm rather than a report, which is why it is the
container's healthcheck. Source staleness is the most likely silent failure in
this system, and an endpoint that returns 200 with a list of rotting sources
nobody reads is not an alarm.

---

## 6. The caseworker queue

The queue carries what people have said about their own circumstances, so it
needs a lock. That is the obvious half.

The half that matters more is attribution. `answered_by` used to be free text in
the request body, so the audit trail was only as good as the honesty of whoever
posted: anybody who could reach the endpoint could sign a determination with any
name. ADR-0004 rests on a determination being traceable to a named human, and a
name somebody typed about themselves is not that.

**So the name comes from the credential, not from the body.**

### Register somebody

```bash
uv run wayfinder caseworker-token "Clare Nolan, Irish Refugee Council"
```

```
Token for Clare Nolan, Irish Refugee Council. Copy it now, it is not stored anywhere:

    JTk6cMg5HFMRvRA3_X9Nlk3ZUBoGill9OPRo5S5q3PY

Add this caseworker to the registry and restart the API:

    WAYFINDER_CASEWORKERS='[{"name": "Clare Nolan, ...", "token_sha256": "b1e943e5..."}]'
```

The token is shown once and never stored. What goes in the configuration is its
SHA-256 digest, so a leaked config file does not hand over working credentials.
Comparison is constant-time, and nothing logs a token on success or on failure.

This command works on a plain `uv sync`, without the `api` extra, because
setting a caseworker up happens before deciding how to serve the thing.

To add a second person, put both objects in the same JSON list. Two people
sharing a token is refused at startup, because a shared token makes the name on
a determination meaningless, which is the one thing this exists for.

The registry can also come from a file, which is easier to manage than a long
environment variable:

```bash
uv run wayfinder serve --no-model-screen --db ./wayfinder.sqlite --caseworkers ./caseworkers.json
```

### The full handoff, end to end

Export the registry and start the server:

```bash
export WAYFINDER_CASEWORKERS='[{"name":"Clare Nolan, Irish Refugee Council","token_sha256":"b1e943e5..."}]'
```

Check what your token will sign as, before spending it on a real answer:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/whoami
```

Ask something that needs a person:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/threads/amara/turn -H 'content-type: application/json' -d '{"question":"am I entitled to child benefit?"}'
```

```json
{"status": "waiting_for_a_person",
 "why": "That question needs a decision about your own situation. It has gone to a caseworker.",
 "escalation": {"kind": "determination", "asked_on": "2026-08-24"}}
```

The graph is now genuinely paused at a LangGraph `interrupt()`. Stop the server,
restart it, and the thread is still waiting. Read the queue:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/queue
```

Each item carries the question, a situation summary and the sources already
found, so Clare can answer in two minutes rather than twenty. Answer it:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/queue/amara/respond -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"answer":"Habitual residence has to be assessed before I can say. Bring your IPAS letter.","source":"citizensinformation.ie"}'
```

```json
{"status": "answered",
 "attributed_to": "Clare Nolan, Irish Refugee Council",
 "text": "Clare Nolan, Irish Refugee Council looked at this and said: ... That answer is theirs, given on 2026-08-24. I have not changed it and I am not adding to it."}
```

Note what `attributed_to` is. Nothing in that request said "Clare Nolan"; the
name came out of the token. The system quotes the determination and adds nothing
to it.

### What each failure looks like

| Situation | Response |
|---|---|
| No `Authorization` header | 401 plus `WWW-Authenticate: Bearer realm="wayfinder"` |
| Unknown token | 401, identical body |
| Malformed header (`Basic ...`) | 401, identical body |
| Nobody configured | 503, and it names the variable to set |
| Body still sends `answered_by` | 422 |

The three 401s are byte-identical on purpose. A rejection that distinguished an
unknown token from a malformed header would hand somebody a way to probe.

---

## 7. Docker

The corpus is baked into the image rather than mounted. That means the image
itself has an expiry date and the staleness alarm fires against the thing that
is actually deployed. A mounted corpus would let somebody quietly swap in
unreviewed content under a green build.

```bash
docker build -t wayfinder .
```

```bash
docker run --rm -p 8000:8000 -v wayfinder-threads:/data -e ANTHROPIC_API_KEY -e WAYFINDER_CASEWORKERS wayfinder
```

Or with compose, which wires the volume, the healthcheck and the restart policy:

```bash
docker compose up --build
```

```bash
docker compose logs -f wayfinder
```

```bash
docker compose down
```

Three things about this setup are deliberate:

**`/data` is a named volume.** Paused threads outlive the container. A caseworker
queue that empties on redeploy is the one failure this design cannot have, so
`docker compose down -v` will destroy real pending work.

**There is no `--no-model-screen` in the `CMD`.** A container that starts without
`ANTHROPIC_API_KEY` refuses to start rather than serving a screen ADR-0008
measured at 0.167. To run the degraded screen anyway, you have to say so:

```bash
docker compose run --rm wayfinder wayfinder serve --host 0.0.0.0 --db /data/wayfinder.sqlite --no-model-screen
```

**The healthcheck asks about staleness, not liveness.** A process that is up and
serving a corpus nobody has checked in a year is the failure this system is most
likely to have while looking fine, so that is what it checks, hourly.

Any CLI command runs inside the image:

```bash
docker compose run --rm wayfinder wayfinder corpus health
```

---

## 8. The evals

These are the measurements behind ADR-0007 and ADR-0008.

The gate runs offline against the committed baseline. This is what CI runs:

```bash
uv run wayfinder-eval --baseline
```

The design gates are not currently met, and the baseline file says so rather
than hiding it. To see the scores against the original design gates instead,
drop the flag.

**The comparison harness costs money.** It calls a model once per corpus item.

```bash
uv run wayfinder-compare --split crisis-holdout-v4 --model claude-haiku-4-5-20251001 --cache .eval-cache.json --save results.json
```

Always pass `--cache`. Verdicts are keyed on model, prompt and turn together and
written to disk as they arrive, so an interrupted run resumes for the price of
what is left. Two paid runs were lost to a terminal before that existed. Always
pass `--save` too: a run costs money and a terminal scrolls away.

Use `--limit N` to price a run before committing to it. Only held-out splits are
offered as choices, because measuring a dev split would report the tuning rather
than the performance.

---

## 9. The demo site

Static, zero dependencies, zero build step, and no network requests after load.

```bash
uv run python scripts/build_site_data.py
```

This regenerates `site/data.js` by running the real plan engine, the real graph
and the real safety layers. Nothing in it is written by hand, no model is
involved, and no key is needed. A test regenerates the file and fails if it
differs, so the site cannot drift away from the system it claims to demonstrate.

```bash
python -m http.server 8080 --directory site
```

Deployment, the CSP, every security header and why the API cannot go on Vercel
are in [`13-deploying-the-site.md`](13-deploying-the-site.md).

---

## 10. Working on it

The full gate, in the order that fails fastest:

```bash
uv run ruff format --check .
```

```bash
uv run ruff check .
```

```bash
uv run mypy src tests
```

```bash
uv run lint-imports
```

```bash
uv run pytest --cov=wayfinder --cov-report=term-missing --cov-fail-under=90
```

`lint-imports` is the one people skip and should not. Four contracts hold the
architecture up:

1. `plan/` is pure: no I/O, no framework, no model
2. The deterministic safety layers contain no model and no I/O
3. `corpus/` may read files but may not reach for a model
4. The layering is acyclic

Contract 2 is what makes ADR-0006 checkable rather than aspirational. A crisis
path that could reach a model is a crisis path that can be talked out of
escalating, and no amount of prompt engineering fixes that. The contract is why
that claim is verified by a linter instead of trusted.

---

## 11. What is not secured

Stated here rather than left for somebody to discover.

**Thread ids are bearer capabilities.** Anybody holding a thread id can read that
thread's plan and post turns to it. The applicant endpoints have no
authentication at all, which is a deliberate consequence of the applicant not
having an account: asking somebody in an emergency accommodation queue to
register before they can find out where the nearest GP is would defeat the
point. It does mean a guessable thread id is a real exposure, so ids should be
generated as random tokens by whatever front end sits in front of this, and
never derived from anything about the person. That front end does not exist yet.

**There is no rate limiting and no TLS.** Both belong at the reverse proxy, and
neither is configured here.

**There is no token revocation beyond editing the registry and restarting.** For
a handful of caseworkers that is proportionate. It would not be for a hundred.

**Personal data is not persisted beyond the thread's checkpoint** (PDD NG5), and
`DELETE /v1/threads/{id}` exists and is expected to be used. But the SQLite file
is not encrypted at rest, so the volume is as sensitive as the data in it.

---

## 12. When something goes wrong

**`ask` or `serve` exits 2 saying `ANTHROPIC_API_KEY`.** Working as designed.
Export a key, or pass `--no-model-screen` and read the warning it prints.

**The queue returns 503 saying no caseworkers are configured.** Fail-closed. Mint
a token per §6 and restart.

**A 401 on every request even with the right token.** The header is
`Authorization: Bearer <token>`, and it is the token that goes there, not the
digest. Offering the digest is refused on purpose, so somebody who reads the
deployment environment cannot replay what they find in it. Check with
`/v1/whoami`.

**Startup fails with `invalid caseworker entry at position N`.** Almost always a
real token pasted where its digest belongs. The error names the field and the
position but never echoes the value, precisely because that value is often a
live credential and the error is often in a log.

**`GET /v1/queue` returns 503 about a checkpointer.** The API was built without a
durable store. Pass `--db`.

**`/v1/corpus/health` returns 503.** A source has aged out of retrieval. Not a
crash; it is the alarm doing its job. Run `wayfinder corpus health` to see which.

**Tests pass locally but `lint-imports` fails.** Something in `plan/` or the
deterministic part of `safety/` picked up an import it must not have. Read the
contract name in the failure before changing the contract.
