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

TODAY = ("--today", "2026-08-24")


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


# --- minting a caseworker token ----------------------------------------------


def test_minting_prints_the_token_once_and_the_digest_to_store(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The token is shown and never stored; only the digest is configured. That
    is what makes a leaked configuration harmless."""
    from wayfinder.api.auth import ENV_VAR, hash_token

    assert main(["caseworker-token", "Clare Nolan, Irish Refugee Council"]) == EXIT_OK
    out = capsys.readouterr().out

    assert "Clare Nolan, Irish Refugee Council" in out
    assert ENV_VAR in out

    # The printed token and the printed digest must actually correspond, or
    # somebody follows these instructions and cannot log in.
    token = next(
        line.strip()
        for line in out.splitlines()
        if line.startswith("    ") and "=" not in line and len(line.strip()) > 30
    )
    assert hash_token(token) in out


def test_every_minted_token_differs(capsys: pytest.CaptureFixture[str]) -> None:
    seen = set()
    for _ in range(3):
        main(["caseworker-token", "Somebody"])
        seen.add(capsys.readouterr().out)
    assert len(seen) == 3


def test_minting_warns_against_sharing_a_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A shared token makes the name on a determination meaningless, and the
    place somebody is most likely to consider sharing one is right here."""
    main(["caseworker-token", "Somebody"])
    assert "never share a token" in capsys.readouterr().out


# --- serving with a registry --------------------------------------------------


def test_serve_reads_a_caseworker_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The file option has to actually reach the app, or the queue is shut while
    the operator believes it is open."""
    import json

    import uvicorn

    from wayfinder.api.auth import mint_token

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    _, digest = mint_token()
    registry = tmp_path / "caseworkers.json"
    registry.write_text(
        json.dumps([{"name": "Clare Nolan", "token_sha256": digest}]), encoding="utf-8"
    )

    code = main(
        [
            *TODAY,
            "serve",
            "--no-model-screen",
            "--db",
            str(tmp_path / "q.sqlite"),
            "--caseworkers",
            str(registry),
        ]
    )

    assert code == EXIT_OK
    assert "1 caseworker(s)" in capsys.readouterr().out


def test_serve_says_at_startup_when_the_queue_is_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Discovering a shut queue at the first 503 means discovering it when a
    caseworker is already waiting on it."""
    import uvicorn

    from wayfinder.api.auth import ENV_VAR

    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)

    main([*TODAY, "serve", "--no-model-screen", "--db", str(tmp_path / "q.sqlite")])

    out = capsys.readouterr().out
    assert "queue is closed" in out
    assert "caseworker-token" in out, "it said what was wrong but not how to fix it"


def test_serve_refuses_to_start_on_an_unreadable_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, and before the checkpointer is opened.

    Starting anyway would serve the applicant endpoints with the queue silently
    shut, which looks identical to working until somebody escalates.
    """
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: None)
    db = tmp_path / "unused.sqlite"

    code = main(
        [
            *TODAY,
            "serve",
            "--no-model-screen",
            "--db",
            str(db),
            "--caseworkers",
            str(tmp_path / "nope.json"),
        ]
    )

    assert code == EXIT_CANNOT_EVALUATE
    assert "caseworker registry" in capsys.readouterr().err
    assert not db.exists(), "it opened the queue before checking the registry"


def test_a_bad_registry_error_does_not_reach_the_terminal_with_a_token_in_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same no-echo property as `load_caseworkers`, checked at the boundary
    where it would actually end up in a shell history or a log."""
    import json

    secret = "super-secret-token-pasted-in-the-wrong-field"
    registry = tmp_path / "caseworkers.json"
    registry.write_text(
        json.dumps([{"name": "Clare Nolan", "token_sha256": secret}]), encoding="utf-8"
    )

    main(
        [
            *TODAY,
            "serve",
            "--no-model-screen",
            "--db",
            str(tmp_path / "q.sqlite"),
            "--caseworkers",
            str(registry),
        ]
    )

    captured = capsys.readouterr()
    assert secret not in captured.err + captured.out


# --- a missing optional extra -------------------------------------------------


def test_serve_without_the_api_extra_says_which_flag_fixes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 and one line, not a ModuleNotFoundError stack.

    `uv sync` installs neither extra on purpose, so the first command a new
    reader runs can be the one that needs one. A traceback does not tell them
    which flag to add.
    """
    import builtins

    real_import = builtins.__import__

    def no_uvicorn(name: str, *rest: Any) -> Any:
        if name == "uvicorn":
            raise ModuleNotFoundError("No module named 'uvicorn'")
        return real_import(name, *rest)

    monkeypatch.setattr(builtins, "__import__", no_uvicorn)

    code = main(
        [*TODAY, "serve", "--no-model-screen", "--db", str(tmp_path / "q.sqlite")]
    )

    assert code == EXIT_CANNOT_EVALUATE
    err = capsys.readouterr().err
    assert "uv sync --extra api" in err
    assert "Traceback" not in err


def test_the_model_screen_without_the_llm_extra_says_which_flag_fixes_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `llm` package raises a good message, but as an unhandled RuntimeError
    it still reached the terminal as a stack."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-real")
    monkeypatch.setattr(
        "wayfinder.safety.llm.AnthropicCrisisScreen",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("needs anthropic")),
    )

    code = main([*TODAY, "ask", "what do I do first?"])

    assert code == EXIT_CANNOT_EVALUATE
    assert "uv sync --extra llm" in capsys.readouterr().err
