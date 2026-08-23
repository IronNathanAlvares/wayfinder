# 13. Deploying the demo site

**Project:** Wayfinder · **Updated:** 22 August 2026

The site in `site/` is static: hand-written HTML, CSS and JavaScript, no
framework, no build step, no package manifest, and no network requests after
the page loads. That is what makes deploying it boring, which is the point.

---

## Run it locally

```bash
python -m http.server 4173 --directory site
```

Open `http://localhost:4173`. Nothing else is needed: no `npm install`, no
build, no environment variables, no API key.

Two things worth knowing while working on it:

**The local server caches.** `python -m http.server` answers with `304 Not
Modified`, so an edited stylesheet can keep serving the old file and you end up
debugging a layout that is already fixed on disk. Hard-reload with
`Ctrl+Shift+R`, or append a query string. Vercel serves hashed immutable assets
in production, so this is a local problem only.

**The data file is generated.** `site/data.js` is written by
`scripts/build_site_data.py`, which runs the real plan engine, the real graph
and the real safety layers and records what they produced. Do not edit it by
hand: regenerate it.

```bash
uv run python scripts/build_site_data.py
```

`tests/unit/test_site_data.py` regenerates it and fails if the committed file
differs, and CI runs that too. That is the only thing stopping the page from
describing a system that changed underneath it.

---

## Deploy to Vercel

`vercel.json` is already in the repository root and sets everything needed:

```json
{
  "outputDirectory": "site",
  "cleanUrls": true,
  "trailingSlash": false
}
```

There is **no build command and no framework preset**. Vercel serves `site/` as
static files.

### From the dashboard

1. **New Project**, import `IronNathanAlvares/wayfinder`.
2. Framework preset: **Other**. Leave the build command empty.
3. Output directory: `site` — `vercel.json` sets this already, so if the field
   is pre-filled with something else, clearing it is correct.
4. Deploy. There is nothing to configure afterwards: no environment variables,
   no secrets, no integrations.

### From the CLI

```bash
npx vercel --prod
```

### What to check once it is live

- The page renders and the theme toggle cycles Auto → Light → Dark.
- The network tab shows requests for `index.html`, `style.css`, `app.js`,
  `data.js` and `favicon.svg`, **and nothing else**. If anything else appears,
  something was added that should not have been.
- `curl -I https://<your-domain>` shows the security headers below.

---

## The security headers, and why each is there

All set in `vercel.json` for every path. A reviewer will ask about these, so
each one has a reason rather than being copied from a checklist.

| Header | Value | What it stops |
|---|---|---|
| `Content-Security-Policy` | `default-src 'none'` and the rest below | Script injection, exfiltration, framing |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Downgrade to HTTP |
| `X-Content-Type-Options` | `nosniff` | A file being executed as a type it is not |
| `X-Frame-Options` | `DENY` | Clickjacking, for older browsers |
| `Referrer-Policy` | `no-referrer` | Leaking the page somebody came from |
| `Permissions-Policy` | camera, microphone, geolocation and the rest set to `()` | A compromised page asking for hardware |
| `Cross-Origin-Opener-Policy` | `same-origin` | Cross-window scripting |
| `Cross-Origin-Resource-Policy` | `same-origin` | The page being embedded elsewhere |
| `X-Permitted-Cross-Domain-Policies` | `none` | Legacy Flash-era policy files |

The policy itself:

```
default-src 'none';
script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self';
connect-src 'none'; form-action 'none'; frame-ancestors 'none';
base-uri 'none'; object-src 'none'; upgrade-insecure-requests
```

**`connect-src 'none'` is the interesting one.** It says the page may not make
network requests at all: no `fetch`, no `XMLHttpRequest`, no WebSocket, no
beacon. Most sites cannot set it, because they fetch their data. This one can,
because the data ships as a JavaScript file rather than as something to fetch.
The consequence is that **the page has no way to send anything anywhere**, and
that is verifiable in any browser's network tab rather than being a promise.

`unsafe-inline` and `unsafe-eval` appear nowhere. There is no inline script, no
inline style attribute and no inline event handler in the page, which is
asserted by a test rather than left to discipline.

---

## The security posture in full

What somebody reviewing this will want to know, in the order they will ask.

**Is there an API key anywhere?** No. The page calls no model and no API. The
screening results it reports were measured offline against a held-out corpus.
There is nothing to leak, no endpoint to abuse and no per-visitor cost.

**What is the third-party supply chain?** There is none. No `package.json`, no
lockfile, no bundler, no CDN, no external font, no analytics. A test asserts
that `site/` contains exactly five files and that none of them loads a
subresource from another origin.

**What user data is collected?** None. No cookies, no analytics, no logging
that this project controls. The only thing written to the browser is the light
or dark preference, in `localStorage`, on the visitor's own machine, and the
page works without it.

**What is the XSS surface?** Every value from the data file reaches the DOM
through `textContent`, never `innerHTML`. A test asserts that `innerHTML`,
`outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` and `new Function`
appear nowhere in `app.js`. The data is generated rather than user-supplied, so
this is defence in depth, but it costs nothing.

**Can it be framed or embedded?** No. `frame-ancestors 'none'` and
`X-Frame-Options: DENY`.

**What happens if the repository is compromised?** The same as any static site:
an attacker who can commit can change the page. The mitigations are the ones
that apply to the repository rather than to the page — branch protection and
review — and the CSP limits what altered code could do, since it still could
not make a network request.

**What is not protected?** The site is public and meant to be. There is no
authentication because there is nothing behind one.

---

## What this deployment is not

**It is not the application.** The API in `src/wayfinder/api/` is a real
FastAPI service with a caseworker queue and a durable checkpointer, and **it
cannot be deployed to Vercel as it stands.** The design turns on a pause that
lasts days: a caseworker answers on Thursday a question asked on Monday, and
that pause is a row in a SQLite file. Vercel's filesystem is ephemeral, so the
queue would empty between invocations, and there is a test in this repository
that kills a process to prove the pause survives exactly that.

Deploying the application for real needs, in order:

1. **An access model for the applicant side.** The caseworker queue is done: it
   is behind a bearer token and a determination is signed with the name that
   token is registered to rather than with whatever the body claimed. See
   `14-getting-started.md` §6. What is not done is the applicant side, where a
   thread id is a bearer capability and ids are caller-chosen. That is the
   blocker, not a nicety, and it needs a front end that issues unguessable ids
   plus TLS and rate limiting at the proxy.
2. **A Postgres checkpointer.** `sqlite_checkpointer` is the only
   implementation. The swap is small and the deserialisation allowlist in
   `graph/checkpoint.py` has to come with it.
3. **A host with a real disk**, or Postgres behind a serverless deployment.
   Railway, Render and Fly all work; Vercel works for the frontend either way.
4. **A budget.** The crisis screen calls Opus before every turn, which was
   measured at about $0.012 per turn.

Until those exist, the honest thing to deploy is the recording, which is what
this document is about.

---

## Screenshots

`docs/screenshots/` holds whole-page captures, regenerated by:

```bash
uv run python scripts/capture_screenshots.py
```

It serves `site/` on a free port and drives whichever Chrome or Edge is already
installed, in headless mode. Nothing is downloaded and no browser-automation
dependency is added. The theme is passed on the query string, which the page
supports so a link can carry one, so what is captured is the page as shipped
rather than a mode that exists for cameras.
