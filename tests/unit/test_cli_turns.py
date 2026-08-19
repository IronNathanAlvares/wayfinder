"""`wayfinder ask` and `wayfinder serve`.

The interesting behaviour here is the refusal to start. ADR-0008 measured the
deterministic crisis screen at 0.167 recall on held-out data, so starting
quietly with it alone would ship a safety claim the measurements do not
support. Both commands stop instead, and the way past them is to say so on the
command line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wayfinder.cli.main import EXIT_CANNOT_EVALUATE, EXIT_OK, main

TODAY = ("--today", "2026-08-18")


@pytest.fixture(autouse=True)
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this file may reach a model, whatever the developer's shell
    happens to have exported."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_ask_answers_a_procedural_question_with_its_sources(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([*TODAY, "ask", "--no-model-screen", "how do I apply for a PPS number"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert "PPS" in out
    assert "https://" in out, "an answerable question printed no source"


def test_ask_hands_an_entitlement_question_to_a_person(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main([*TODAY, "ask", "--no-model-screen", "am I entitled to child benefit?"])
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert "needs a person" in out
    assert "determination" in out
    for phrase in ("you are entitled", "you qualify", "you may be entitled"):
        assert phrase not in out.lower()


def test_ask_reads_a_situation_file(tmp_path: Path) -> None:
    situation = tmp_path / "amara.yaml"
    situation.write_text(
        "arrival_date: 2026-08-01\nprotection_stage: applied\n", encoding="utf-8"
    )
    code = main(
        [
            *TODAY,
            "ask",
            "--no-model-screen",
            "--situation",
            str(situation),
            "what do I do first?",
        ]
    )
    assert code == EXIT_OK


def test_ask_refuses_to_run_without_the_model_screen_or_an_explicit_opt_out(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 2, not exit 1.

    This is a configuration problem, not a verdict about anything. Collapsing
    the two would let a missing key read as a check that ran and failed.
    """
    code = main([*TODAY, "ask", "what do I do first?"])

    assert code == EXIT_CANNOT_EVALUATE
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err
    assert "--no-model-screen" in err


def test_opting_out_of_the_model_screen_says_what_it_costs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """On stderr, every run, with the measured number in it. A degraded screen
    that does not announce itself is still trusted."""
    main([*TODAY, "ask", "--no-model-screen", "how do I apply for a PPS number"])
    assert "0.167" in capsys.readouterr().err


def test_serve_starts_the_app_on_a_durable_checkpointer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`uvicorn.run` is stubbed. What is under test is everything up to it: the
    app is built, and the queue it will serve is backed by a file rather than by
    memory."""
    import uvicorn

    started: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        started["app"] = app
        started["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)
    db = tmp_path / "queue.sqlite"

    code = main(
        [
            *TODAY,
            "serve",
            "--no-model-screen",
            "--db",
            str(db),
            "--port",
            "8099",
        ]
    )

    assert code == EXIT_OK
    assert started["kwargs"]["port"] == 8099
    assert db.exists(), "the queue was not backed by a file, so it would not survive"
    assert {route.path for route in started["app"].routes} >= {
        "/v1/threads",
        "/v1/queue",
        "/v1/corpus/health",
    }


def test_serve_refuses_without_the_model_screen_too(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main([*TODAY, "serve", "--db", str(tmp_path / "unused.sqlite")])
    assert code == EXIT_CANNOT_EVALUATE
    assert not (tmp_path / "unused.sqlite").exists(), "it started before checking"
