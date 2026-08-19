"""The demo runs. This is here because demos rot faster than anything else.

A demo script is the first thing a reader runs and the last thing anybody
maintains. Running it in CI means a rename three milestones from now breaks the
build rather than breaking the first impression.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
DEMO = ROOT / "scripts" / "demo.py"


def test_the_demo_runs_end_to_end() -> None:
    result = subprocess.run(
        [sys.executable, str(DEMO)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    out = result.stdout

    # The five things the demo exists to show, in the order it shows them.
    assert "Apply for your PPS number" in out
    assert "checked 2026-08-18" in out, "an answer was shown without a dated source"
    assert "Am I entitled to child benefit?" in out
    assert "Clare Nolan, Irish Refugee Council looked at this and said" in out
    assert "I have not changed it" in out


def test_the_demo_does_not_claim_an_entitlement_anywhere_in_its_output() -> None:
    """The same check the graph tests make, applied to the thing a reader
    actually sees first."""
    result = subprocess.run(
        [sys.executable, str(DEMO)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    lowered = result.stdout.lower()
    for phrase in ("you are entitled", "you qualify", "you may be entitled"):
        assert phrase not in lowered
