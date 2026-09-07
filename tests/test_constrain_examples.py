"""Clone-and-run examples must work from the repository root."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_hello_example_accepts():
    out = _run("examples/constrain/hello.py")
    assert "decision=accept" in out
    assert '"schema_version": "0.1.0"' in out


def test_evaluate_text_example_shows_privacy_fail():
    out = _run("examples/constrain/evaluate_text.py")
    assert "clean:    decision=accept" in out
    assert "leaking:  decision=revise" in out


def test_complete_flow_example_covers_accept_revise_refuse():
    out = _run("examples/constrain/complete_flow.py")
    assert "decision=accept" in out
    assert "initial_had_ssn=True" in out
    assert "final_has_ssn=False" in out
    assert "decision=refuse" in out
