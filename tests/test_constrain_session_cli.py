"""CLI session / explain / demo commands."""

from __future__ import annotations

import json
from pathlib import Path

from ai4.constrain.cli import EXIT_ACCEPT, EXIT_CONFIG, EXIT_REVISE, main

CLEAN = "Please give a brief, checkable outline of options and limits."
CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
LEAKING = "Jane Doe lives at 123 Main. SSN 078-05-1120."


def test_explain_command_prints_shard_card(capsys):
    assert main(["explain", "--text", CLEAN_TEXT]) == EXIT_ACCEPT
    out = capsys.readouterr().out
    assert out.startswith("shard card")
    assert "decision: accept" in out
    assert "privacy" in out


def test_explain_json_and_revise(capsys):
    assert main(["explain", "--text", LEAKING, "--json"]) == EXIT_REVISE
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "ai4.shard_card.v0.1"
    assert payload["decision"] == "revise"
    assert "078-05-1120" not in json.dumps(payload)


def test_run_explain_keeps_json_stdout(capsys):
    assert main(["run", "--prompt", CLEAN, "--explain"]) == EXIT_ACCEPT
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["decision"] == "accept"
    assert "shard card" in captured.err
    assert "decision: accept" in captured.err


def test_session_complete_and_show(tmp_path: Path, capsys):
    store = tmp_path / "sessions"
    trace = tmp_path / "trace.jsonl"
    code = main(
        [
            "session",
            "complete",
            "--prompt",
            CLEAN,
            "--session-id",
            "cli-1",
            "--store-dir",
            str(store),
            "--trace-jsonl",
            str(trace),
            "--explain",
        ]
    )
    assert code == EXIT_ACCEPT
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["session_id"] == "cli-1"
    assert payload["turn_index"] == 1
    assert payload["report"]["decision"] == "accept"
    assert payload["shard_card"]["schema"] == "ai4.shard_card.v0.1"
    assert "shard card" in captured.err
    assert trace.is_file()
    assert "shard_card" in trace.read_text(encoding="utf-8")
    assert main(["session", "show", "--session-id", "cli-1", "--store-dir", str(store)]) == EXIT_ACCEPT
    shown = json.loads(capsys.readouterr().out)
    assert shown["session_id"] == "cli-1"
    assert len(shown["turns"]) == 1


def test_session_demo(capsys):
    assert main(["session", "demo"]) == EXIT_ACCEPT
    payload = json.loads(capsys.readouterr().out)
    decisions = [row["decision"] for row in payload["turns"]]
    assert decisions == ["accept", "accept", "refuse"]


def test_session_complete_dry_run_live_is_config(capsys):
    assert (
        main(
            [
                "session",
                "complete",
                "--prompt",
                CLEAN,
                "--dry-run",
                "--provider",
                "live",
            ]
        )
        == EXIT_CONFIG
    )
    assert "mock-only" in capsys.readouterr().err


def test_session_show_missing_is_config(tmp_path: Path, capsys):
    assert (
        main(["session", "show", "--session-id", "nope", "--store-dir", str(tmp_path)])
        == EXIT_CONFIG
    )
    assert "was not found" in capsys.readouterr().err
