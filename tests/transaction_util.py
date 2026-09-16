"""Shared helpers for transaction-control tests."""

from __future__ import annotations

from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import REPORT_SCHEMA_VERSION
from ai4.transaction._base58 import b58encode
from src.protocol_labels import FROZEN_TERMINAL_LABELS


def solana_address(seed: int = 7) -> str:
    data = bytes((seed + i) % 256 for i in range(32))
    return b58encode(data)


def solana_signature(seed: int = 3) -> str:
    data = bytes((seed + i) % 256 for i in range(64))
    return b58encode(data)


def fixture_report(**overrides) -> DecisionReport:
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": "evaluate_only",
        "outcome_kind": "constraint",
        "prompt": "Review this proposed SOL transfer against frozen limits.",
        "initial_proposal": "fixture proposal",
        "shard_evaluations": None,
        "arbitration": None,
        "decision": "accept",
        "terminal": None,
        "decision_reason": "fixture",
        "revision_trace": [],
        "final_output": "fixture proposal",
        "telemetry": {},
        "versions": {},
        "candidate_evaluated": False,
    }
    payload.update(overrides)
    return DecisionReport.from_dict(payload)


assert "accepted" in FROZEN_TERMINAL_LABELS
