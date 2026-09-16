"""CLI entry for prepare and status."""

from __future__ import annotations

import json

from ai4.transaction.cli import EXIT_FAIL, EXIT_OK, main
from tests.transaction_util import solana_address, solana_signature

DEST = solana_address(29)


def test_cli_prepare_allow(capsys):
    code = main(
        [
            "prepare",
            "--network",
            "devnet",
            "--asset",
            "SOL",
            "--amount",
            "0.01",
            "--destination",
            DEST,
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == EXIT_OK
    assert payload["decision"] == "ALLOW"
    assert payload["decision_report"]["decision"] == "accept"
    assert payload["handoff_uri"].startswith("solana:")
    assert "ai4-network=devnet" in payload["handoff_uri"]
    assert payload["approved_binding"]["network"] == "devnet"
    assert payload["unsigned_payload"]["kind"] == "solana_system_transfer_stub"
    assert "AI4 does not hold keys or assets" in captured.err
    assert "Decision: ALLOW" in captured.err


def test_cli_prepare_deny_bad_network(capsys):
    code = main(
        [
            "prepare",
            "--network",
            "ethereum",
            "--asset",
            "SOL",
            "--amount",
            "0.01",
            "--destination",
            DEST,
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == EXIT_FAIL
    assert payload["decision"] == "DENY"
    assert payload["unsigned_payload"] is None
    assert payload["decision_report"] is None


def test_cli_prepare_deny_wrong_asset(capsys):
    code = main(
        [
            "prepare",
            "--network",
            "mainnet-beta",
            "--asset",
            "USDC",
            "--amount",
            "0.01",
            "--destination",
            DEST,
        ]
    )
    assert code == EXIT_FAIL
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "DENY"


def test_cli_status_fail_closed_without_rpc(capsys, monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    code = main(["status", solana_signature()])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == EXIT_FAIL
    assert payload["fail_closed"] is True
    assert "no Solana RPC URL" in captured.err
    assert "fail-closed (not confirmed)" in captured.err
    assert "Confirmation: confirmed" not in captured.err


def test_cli_usage_error_is_nonzero(capsys):
    code = main(["prepare"])
    assert code == EXIT_FAIL
    assert capsys.readouterr().err
