"""CLI operation for the public shard runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4.constrain.cli import (
    EXIT_ACCEPT,
    EXIT_CONFIG,
    EXIT_REFUSE,
    EXIT_REVISE,
    EXIT_TIMEOUT,
    main,
    report_exit_code,
)
from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import REPORT_SCHEMA_VERSION
from src.protocol_labels import FROZEN_TERMINAL_LABELS

CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_PROMPT = "Please give a brief, checkable outline of options and limits."
LEAKING = "Jane Doe lives at 123 Main. SSN 078-05-1120."


def _minimal_report(**overrides) -> DecisionReport:
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": "constrained_loop",
        "outcome_kind": "constraint",
        "prompt": "",
        "initial_proposal": "",
        "shard_evaluations": None,
        "arbitration": None,
        "decision": "accept",
        "terminal": "accepted",
        "decision_reason": "",
        "revision_trace": [],
        "final_output": "",
        "telemetry": {},
        "versions": {},
        "candidate_evaluated": False,
    }
    payload.update(overrides)
    return DecisionReport.from_dict(payload)


def test_cli_exit_codes_are_independent_of_implementation_helpers():
    assert report_exit_code(_minimal_report(decision="accept", terminal="accepted")) == EXIT_ACCEPT
    assert report_exit_code(_minimal_report(decision="revise", terminal="revision_exhausted")) == EXIT_REVISE
    assert report_exit_code(_minimal_report(decision="refuse", terminal="refused")) == EXIT_REFUSE
    assert (
        report_exit_code(
            _minimal_report(
                outcome_kind="execution",
                decision=None,
                terminal="timed_out",
            )
        )
        == EXIT_TIMEOUT
    )
    assert EXIT_ACCEPT == 0
    assert EXIT_CONFIG == 1
    assert EXIT_REVISE == 2
    assert EXIT_REFUSE == 3
    assert EXIT_TIMEOUT == 4
    assert "timed_out" in FROZEN_TERMINAL_LABELS


def test_cli_evaluate_writes_decision_report(capsys):
    assert main(["evaluate", "--text", CLEAN_TEXT, "--prompt-id", "cli-eval"]) == EXIT_ACCEPT
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "evaluate_only"
    assert payload["decision"] == "accept"
    assert payload["terminal"] is None
    assert payload["prompt_id"] == "cli-eval"
    assert payload["telemetry"]["calls"] == 0
    assert payload["versions"]["evaluator_id"] == "v0.1-regex"


def test_cli_evaluate_revise_uses_exit_2(capsys):
    assert main(["evaluate", "--text", LEAKING, "--no-redact"]) == EXIT_REVISE
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "revise"
    assert payload["arbitration"]["veto"] is True


def test_cli_timeout_uses_exit_4(capsys):
    assert main(["run", "--prompt", CLEAN_PROMPT, "--timeout-s", "0"]) == EXIT_TIMEOUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome_kind"] == "execution"
    assert payload["decision"] is None
    assert payload["candidate_evaluated"] is False
    assert payload["shard_evaluations"] is None
    assert payload["arbitration"] is None


def test_cli_default_redacts_ssn(capsys):
    assert main(["evaluate", "--text", LEAKING]) == EXIT_REVISE
    raw = capsys.readouterr().out
    assert "078-05-1120" not in raw
    payload = json.loads(raw)
    assert payload["redacted"] is True
    assert payload["decision"] == "revise"


def test_cli_run_mock_accept(capsys):
    assert main(["run", "--prompt", CLEAN_PROMPT]) == EXIT_ACCEPT
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "constrained_loop"
    assert payload["decision"] == "accept"
    assert payload["final_output"]
    assert payload["telemetry"]["provider"] == "mock"
    assert payload["proposal"]["provider_id"] == "mock"
    assert payload["proposal"]["resolved_as"] == "explicit_argument"
    assert "provider_id" not in payload["versions"]


def test_cli_run_writes_output_file(tmp_path: Path, capsys):
    target = tmp_path / "report.json"
    assert main(["run", "--prompt", CLEAN_PROMPT, "--output", str(target)]) == EXIT_ACCEPT
    stdout = json.loads(capsys.readouterr().out)
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["decision"] == stdout["decision"]
    assert written["final_output"] == stdout["final_output"]


def test_cli_evaluate_from_file(tmp_path: Path, capsys):
    path = tmp_path / "candidate.txt"
    path.write_text(CLEAN_TEXT, encoding="utf-8")
    assert main(["evaluate", "--text-file", str(path)]) == EXIT_ACCEPT
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "accept"


def test_cli_unknown_provider_is_config_exit_not_revise(capsys):
    assert main(["run", "--prompt", "x", "--provider", "unregistered"]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "error:" in err
    assert "unregistered" in err


def test_cli_missing_command_is_config_exit_not_revise(capsys):
    assert main([]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "error:" in err


def test_cli_missing_prompt_fails(capsys):
    assert main(["run"]) == EXIT_CONFIG
    err = capsys.readouterr().err
    assert "error:" in err
    assert "--prompt" in err


def test_cli_missing_text_file_fails(tmp_path: Path, capsys):
    assert main(["evaluate", "--text-file", str(tmp_path / "absent.txt")]) == EXIT_CONFIG
    assert "not found" in capsys.readouterr().err


def test_cli_help_documents_exit_contract():
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    from ai4.constrain.cli import build_parser

    help_text = build_parser().format_help()
    assert "0=accept" in help_text
    assert "4=timeout" in help_text
