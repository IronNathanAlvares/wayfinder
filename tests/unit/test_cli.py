"""The demo surface, including the parts of the output that are safety claims.

The tone assertions are not fussiness. The output is read by somebody under
stress who may have just been told they cannot do the thing they came to do, and
a cheerful refusal is worse than a plain one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from wayfinder.cli.main import EXIT_CANNOT_EVALUATE, EXIT_FAIL, EXIT_OK, main

SHELTER_SITUATION = """
arrival_date: 2026-08-03
protection_stage: applied
accommodation: emergency
household:
  adults: 1
  children_ages: [7]
held: [document:identity]
known_absent:
  - document:permit
  - document:card
  - document:address_proof
  - document:shelter_letter
  - document:tenancy
  - status:banked
  - status:work_allowed
"""


@pytest.fixture
def situation_file(tmp_path: Path) -> Path:
    path = tmp_path / "situation.yaml"
    path.write_text(SHELTER_SITUATION, encoding="utf-8")
    return path


def _run(args: list[str]) -> int:
    """Global options come before the subcommand, so the date is prepended.

    Pinning the date matters: a demo whose output changes overnight cannot be
    asserted on, and the engine takes the date as an input precisely so it does
    not have to be.
    """
    return main(["--today", "2026-08-17", *args])


def test_plan_command_succeeds(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(["--corpus", str(FIXTURES / "corpus"), "plan", str(situation_file)])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "Start now" in out
    assert "Ask the shelter for a letter" in out


def test_the_output_names_the_authority_and_refuses_to_assess_it(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The sentence the whole project exists to be able to write."""
    _run(["--corpus", str(FIXTURES / "corpus"), "plan", str(situation_file)])
    out = capsys.readouterr().out
    assert "the Fictional Benefits Office" in out
    assert "not by you and not by this system" in out


def test_the_output_never_assesses_an_entitlement(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Hedged entitlement language is still entitlement language.

    "You may be entitled to X" is worse than saying nothing, because it sounds
    like permission to plan around it.
    """
    _run(["--corpus", str(FIXTURES / "corpus"), "plan", str(situation_file)])
    out = capsys.readouterr().out.lower()
    for phrase in (
        "you may be entitled",
        "you are entitled",
        "you qualify",
        "you may qualify",
        "you should qualify",
        "you will get",
        "you are eligible",
        "likely to be approved",
    ):
        assert phrase not in out, phrase


def test_the_output_has_no_cheerfulness(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(["--corpus", str(FIXTURES / "corpus"), "plan", str(situation_file)])
    out = capsys.readouterr().out
    assert "!" not in out
    for word in ("Great", "Congratulations", "Don't worry", "Good news"):
        assert word not in out


def test_a_blocked_task_always_offers_something(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal that leaves somebody stuck is a failure, not a safety win."""
    _run(["--corpus", str(FIXTURES / "corpus"), "plan", str(situation_file)])
    lines = capsys.readouterr().out.splitlines()
    start = lines.index("Not yet")
    section = lines[start + 1 :]
    blocked_headings = [
        i for i, line in enumerate(section) if line.startswith("  ") and line[2] != " "
    ]
    for i, heading in enumerate(blocked_headings):
        end = blocked_headings[i + 1] if i + 1 < len(blocked_headings) else len(section)
        body = "\n".join(section[heading:end])
        assert "You can start now" in body or "caseworker" in body or "until" in body


def test_json_output_is_machine_readable(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    _run(
        [
            "--corpus",
            str(FIXTURES / "corpus"),
            "plan",
            str(situation_file),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["frontier"][0] == "shelter.letter_request"
    assert payload["built_on"] == "2026-08-17"


def test_corpus_check_passes_on_a_good_corpus(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _run(["--corpus", str(FIXTURES / "corpus"), "corpus", "check"]) == EXIT_OK
    assert "No integrity problems" in capsys.readouterr().out


def test_corpus_check_fails_with_exit_one_on_a_broken_corpus(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 1 is a verdict of fail. It must not be confused with exit 2."""
    code = _run(["--corpus", str(FIXTURES / "broken_corpus"), "corpus", "check"])
    assert code == EXIT_FAIL
    assert "corpus problem" in capsys.readouterr().err


def test_a_missing_file_is_exit_two_not_exit_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Could-not-evaluate is a different thing from a failing verdict, and
    collapsing the two lets a broken check read as a passing one."""
    code = _run(
        ["--corpus", str(FIXTURES / "corpus"), "plan", str(tmp_path / "nope.yaml")]
    )
    assert code == EXIT_CANNOT_EVALUATE


def test_a_cyclic_corpus_is_a_loud_failure(
    situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(
        ["--corpus", str(FIXTURES / "cycle_corpus"), "plan", str(situation_file)]
    )
    assert code == EXIT_FAIL
    assert "cycle" in capsys.readouterr().err


def test_diff_reports_what_changed(
    tmp_path: Path, situation_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    after = tmp_path / "after.yaml"
    after.write_text(
        SHELTER_SITUATION.replace(
            "held: [document:identity]",
            "held: [document:identity, document:shelter_letter]",
        ).replace("  - document:shelter_letter\n", ""),
        encoding="utf-8",
    )
    code = _run(
        ["--corpus", str(FIXTURES / "corpus"), "diff", str(situation_file), str(after)]
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "You can now start" in out
    assert "Apply for your permit" in out


def test_corpus_health_reports_bands(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(["--corpus", str(FIXTURES / "corpus"), "corpus", "health"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "normal:" in out
    assert "excluded: 0" in out
