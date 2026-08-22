"""The demo site's data file, and whether it still matches the system.

A static site is a recording, and a recording goes stale silently. The page
claims that everything on it was produced by running the real code, which stops
being true the moment somebody changes a prompt, a task or a route and does not
regenerate. So the generator runs here and the result is compared byte for byte.

This is the same discipline as the corpus staleness alarm: the failure mode is
not that the site breaks, it is that the site keeps working while quietly
describing a system that no longer exists.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
DATA = ROOT / "site" / "data.js"
GENERATOR = ROOT / "scripts" / "build_site_data.py"
SITE = ROOT / "site"


def payload() -> dict[str, Any]:
    """The JSON out of the JavaScript wrapper."""
    text = DATA.read_text(encoding="utf-8")
    body = text.split("window.WAYFINDER = ", 1)[1].rsplit(";", 1)[0]
    loaded: dict[str, Any] = json.loads(body)
    return loaded


def test_the_data_file_matches_what_the_system_produces_now() -> None:
    """Regenerate and compare. If this fails, run the generator and look at the
    diff before committing it: something about the system changed."""
    before = DATA.read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(GENERATOR)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    after = DATA.read_text(encoding="utf-8")
    assert before == after, (
        "site/data.js is stale. Regenerate it with "
        "`uv run python scripts/build_site_data.py` and review the diff. "
        f"Generator said: {result.stdout.strip()}"
    )


# --- the claims the page makes about itself ----------------------------------


def test_every_route_out_of_classification_is_demonstrated() -> None:
    """The page says a question takes one of five routes. If a route stopped
    being reachable, the page would keep saying five."""
    routes = {turn["route"] for turn in payload()["turns"]}
    assert routes == {
        "procedural",
        "planning",
        "determination",
        "crisis",
        "out_of_scope",
    }


def test_each_recorded_turn_took_the_route_it_was_chosen_to_show() -> None:
    for turn in payload()["turns"]:
        assert turn["route"] == turn["expected"], turn["question"]


def test_the_planning_turn_carries_citations() -> None:
    """The bug this file was written during. A plan was built and then answered
    with "I do not have a source I trust for that"."""
    planning = next(t for t in payload()["turns"] if t["route"] == "planning")
    assert planning["citations"], "the planning demo shows a refusal"
    assert "do not have a source" not in planning["answer"]


def test_the_determination_turn_pauses_and_generates_nothing() -> None:
    """The claim the whole page is organised around."""
    turn = next(t for t in payload()["turns"] if t["route"] == "determination")
    assert turn["paused"] is True
    assert "answer" not in turn
    assert turn["escalation"]["kind"] == "determination"


def test_the_crisis_turn_carries_a_real_number_and_no_citations() -> None:
    turn = next(t for t in payload()["turns"] if t["route"] == "crisis")
    assert "1800 707 707" in turn["answer"]
    assert turn["citations"] == []


def test_the_handoff_answer_is_attributed_to_the_named_caseworker() -> None:
    handoff = payload()["handoff"]
    assert handoff["attributedTo"] == handoff["caseworker"]
    assert handoff["caseworker"] in handoff["reply"]
    assert "I have not changed it" in handoff["reply"]


def test_no_recorded_answer_asserts_an_entitlement() -> None:
    """The same check the graph tests make, applied to what a visitor reads."""
    banned = ("you are entitled", "you may be entitled", "you qualify", "you will get")
    for turn in payload()["turns"]:
        text = turn.get("answer", "").lower()
        for phrase in banned:
            assert phrase not in text, turn["question"]


def test_every_citation_has_a_date_and_an_https_source() -> None:
    for turn in payload()["turns"]:
        for cite in turn.get("citations", []):
            assert cite["url"].startswith("https://"), cite
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cite["lastVerified"]), cite


def test_the_topology_shown_is_the_compiled_one() -> None:
    """The page draws the graph. Drawing a sketch instead would let the diagram
    keep claiming a safety property the code had stopped having."""
    topology = payload()["topology"]
    edges = {(e["from"], e["to"]) for e in topology["edges"]}

    assert ("handoff", "compose") in edges
    assert ("classify", "handoff") in edges
    # Crisis and decline end the turn.
    assert {t for f, t in edges if f == "crisis_response"} == {"__end__"}
    assert {t for f, t in edges if f == "decline"} == {"__end__"}
    # Nothing reaches composition from the crisis path.
    assert not [t for f, t in edges if f == "crisis_response" and t == "compose"]


def test_the_measurements_shown_are_the_committed_ones() -> None:
    """The chart reads the measurement files rather than restating them, so the
    page and ADR-0008 cannot disagree."""
    arms = payload()["measurements"]["arms"]
    assert [a["model"] for a in arms] == [
        "no model",
        "claude-haiku-4-5",
        "claude-opus-5",
    ]
    deterministic, haiku, opus = arms
    assert deterministic["recall"] < haiku["recall"] < opus["recall"]
    assert opus["bound"] < payload()["measurements"]["gate"], (
        "the page would be claiming the gate is met"
    )


# --- the site's own security posture -----------------------------------------


def test_the_page_loads_nothing_from_anybody_elses_server() -> None:
    """The security claim the page makes in so many words. A CDN font or an
    analytics tag would make `connect-src 'none'` a lie.

    Subresources are what matter here, not links. A reader clicking through to
    GitHub is fine; the browser fetching something from GitHub is not.
    """
    html = (SITE / "index.html").read_text(encoding="utf-8")

    loaded = [
        *re.findall(r"<script[^>]*\bsrc=\"([^\"]+)\"", html),
        *re.findall(r"<link[^>]*\bhref=\"([^\"]+)\"", html),
        *re.findall(r"<img[^>]*\bsrc=\"([^\"]+)\"", html),
        *re.findall(r"<iframe[^>]*\bsrc=\"([^\"]+)\"", html),
    ]
    assert loaded, "the check found nothing to check"
    for target in loaded:
        assert not target.startswith(("http://", "https://", "//")), (
            f"{target} is fetched from another origin"
        )

    # And no @import in the stylesheet, which is the other way to pull one in.
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert "@import" not in css
    assert "url(http" not in css.replace(" ", "")


def test_no_inline_script_or_style_survives_the_csp() -> None:
    """The policy has no 'unsafe-inline'. Anything inline would silently stop
    running in production while working locally."""
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline <script>"
    assert "<style" not in html
    assert not re.search(r"\son[a-z]+=", html), "inline event handler attribute"
    assert not re.search(r'\sstyle="', html), "inline style attribute"


def test_the_javascript_never_writes_html() -> None:
    """The page says every value reaches it as text. innerHTML anywhere would
    make that untrue."""
    app = (SITE / "app.js").read_text(encoding="utf-8")
    # Comments discuss these sinks by name, so strip them before looking.
    code = re.sub(r"/\*.*?\*/", "", app, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in code, sink
    assert "eval(" not in code
    assert "new Function" not in code
    # The one place markup could still get in.
    assert "createContextualFragment" not in code


def test_the_headers_are_configured_rather_than_assumed() -> None:
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    headers = {
        h["key"]: h["value"]
        for rule in config["headers"]
        if rule["source"] == "/(.*)"
        for h in rule["headers"]
    }

    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "connect-src 'none'" in csp, "the page must not be able to phone home"
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "max-age=" in headers["Strict-Transport-Security"]
    for capability in ("camera", "microphone", "geolocation", "payment"):
        assert f"{capability}=()" in headers["Permissions-Policy"]


def test_the_site_ships_no_dependencies() -> None:
    """No package manifest, no lockfile, no vendored bundle. The page claims
    there is no third-party supply chain, and this is that claim."""
    for name in ("package.json", "package-lock.json", "yarn.lock", "node_modules"):
        assert not (SITE / name).exists(), name
    assert sorted(p.name for p in SITE.iterdir()) == [
        "app.js",
        "data.js",
        "favicon.svg",
        "index.html",
        "style.css",
    ]


@pytest.mark.parametrize("name", ["index.html", "app.js", "style.css"])
def test_the_site_files_are_utf8_without_surprises(name: str) -> None:
    text = (SITE / name).read_text(encoding="utf-8")
    assert "\x00" not in text
    assert text.strip(), name
