"""Offline checks for committed DevNet live-evidence (no live RPC)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai4.transaction.desktop_handoff import LIVE_PROOF_HTML_REPO_PATH, LIVE_PROOF_SHA256
from ai4.transaction.receipt import ATTRIBUTION

ROOT = Path(__file__).resolve().parents[1]
LIVE_DEST = "4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e"
LIVE_SIG = "4KAtBNHVJQBkAHoGGJCDDRDr1A9Rha2PSHZ5D8mA8cVKXZiyjXJmoRWUA4Y2HqEY1YKi12LmDRSJMdjRDN4dxX9E"
EVIDENCE_MD = ROOT / "examples" / "transaction" / "LIVE_EVIDENCE.md"
EVIDENCE_JSON = ROOT / "examples" / "transaction" / "live_proof" / "fe30e76a_devnet_live_evidence.json"


def test_live_evidence_markdown_records_finalized_owner_proof():
    md = EVIDENCE_MD.read_text(encoding="utf-8")
    assert "0.7.0" in md
    assert LIVE_DEST in md
    assert "1000000" in md
    assert LIVE_PROOF_SHA256 in md
    assert LIVE_SIG in md
    assert "finalized" in md
    assert ATTRIBUTION in md
    assert "self-transfer" in md.lower()
    assert "thesingulant.github.io/ai4-constrain/live-proof/fe30e76a" in md
    assert "signAndSendTransaction" in md
    assert "AI4.destination" in md
    assert "AI4.lamports" in md
    assert "python3 -m http.server" not in md
    assert "BEGIN PRIVATE KEY" not in md
    assert "--private-key" not in md
    assert "--seed" not in md
    lowered = md.lower()
    assert "never received keys" in lowered or "never received, stored" in lowered
    assert "not telegram" in lowered
    assert "not a pypi" in lowered


def test_live_evidence_json_matches_frozen_binding_and_receipt():
    payload = json.loads(EVIDENCE_JSON.read_text(encoding="utf-8"))
    binding = payload["approved_binding"]
    assert binding["sha256"] == LIVE_PROOF_SHA256
    assert binding["network"] == "devnet"
    assert binding["asset"] == "SOL"
    assert binding["action"] == "transfer"
    assert binding["amount_sol"] == "0.001"
    assert binding["lamports"] == 1_000_000
    assert binding["destination"] == LIVE_DEST
    receipt = payload["receipt"]
    assert receipt["lifecycle_state"] == "finalized"
    assert receipt["confirmation_status"] == "finalized"
    assert receipt["slot"] == 499404925
    assert receipt["error"] is None
    assert receipt["signature"] == LIVE_SIG
    assert receipt["attribution"] == ATTRIBUTION
    assert receipt["decision"] == "ALLOW"
    assert receipt["decision_report_summary"]["constrain_decision"] == "accept"
    assert receipt["decision_report_summary"]["mode"] == "evaluate_only"
    assert payload["ai4_signed"] is False
    assert payload["ai4_custody"] is False
    assert payload["wallet_signed"] is True
    assert payload["package_version"] == "0.7.0"
    assert payload["telegram"] is False
    assert payload["on_chain_jsonParsed"]["self_transfer"] is True
    assert payload["on_chain_jsonParsed"]["destination"] == LIVE_DEST
    assert payload["on_chain_jsonParsed"]["lamports"] == 1_000_000
    html = (ROOT / LIVE_PROOF_HTML_REPO_PATH).read_bytes()
    assert payload["pages_binding_integrity"]["html_sha256"] == hashlib.sha256(html).hexdigest()
    assert payload["pages_binding_integrity"]["matches_committed_html"] is True
    blob = EVIDENCE_JSON.read_text(encoding="utf-8").lower()
    assert "begin private key" not in blob
    assert "mnemonic" not in blob
    assert '"seed"' not in blob
