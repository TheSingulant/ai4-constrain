"""AI4Receipt field integrity and fail-closed mapping."""

from __future__ import annotations

import pytest

from ai4.transaction.receipt import (
    ATTRIBUTION,
    AI4Receipt,
    LIFECYCLE_CONFIRMED,
    LIFECYCLE_FAILED,
    LIFECYCLE_FAIL_CLOSED,
    LIFECYCLE_FINALIZED,
    LIFECYCLE_PREPARED,
    REQUIRED_RECEIPT_FIELDS,
    build_ai4_receipt,
    format_ai4_receipt_summary,
    lifecycle_from_status,
)
from ai4.transaction.types import Decision, Receipt, TransferIntent
from ai4.transaction.prepare import prepare_transfer
from tests.transaction_util import fixture_report, solana_address, solana_signature

DEST = solana_address(41)
SIG = solana_signature(17)


def _prepare_allow():
    return prepare_transfer(
        TransferIntent(network="devnet", asset="SOL", amount="0.001", destination=DEST),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
    )


def test_receipt_required_fields_present():
    prepared = _prepare_allow()
    receipt = build_ai4_receipt(prepared, lifecycle_state=LIFECYCLE_PREPARED)
    payload = receipt.to_dict()
    for key in REQUIRED_RECEIPT_FIELDS:
        assert key in payload
    assert payload["network"] == "devnet"
    assert payload["asset"] == "SOL"
    assert payload["action"] == "transfer"
    assert payload["amount"] == "0.001"
    assert payload["destination"] == DEST
    assert payload["approved_binding_hash"] == prepared.approved_binding.sha256()
    assert payload["attribution"] == ATTRIBUTION
    assert "Prepared and constrained by AI4" in payload["attribution"]
    assert "signed and broadcast by the user's wallet" in payload["attribution"]
    assert "AI4 executed" not in payload["attribution"]
    assert payload["explorer_url"] is None
    assert payload["signature"] is None
    assert payload["lifecycle_state"] == "prepared"


def test_handoff_binding_preserved_into_receipt():
    prepared = _prepare_allow()
    observed = Receipt(
        signature=SIG,
        fail_closed=False,
        reasons=(),
        confirmation_status="finalized",
        slot=42,
        err=None,
        explorer_url=f"https://explorer.solana.com/tx/{SIG}?cluster=devnet",
        network="devnet",
        rpc_used=True,
    )
    receipt = build_ai4_receipt(
        prepared,
        lifecycle_state=LIFECYCLE_FINALIZED,
        status_receipt=observed,
    )
    assert receipt.approved_binding_hash == prepared.approved_binding.sha256()
    assert receipt.approved_binding["destination"] == DEST
    assert receipt.approved_binding["network"] == "devnet"
    assert receipt.approved_binding["amount_sol"] == "0.001"
    assert receipt.approved_binding["action"] == "transfer"
    assert receipt.destination == prepared.approved_binding.destination
    assert receipt.amount == prepared.approved_binding.amount_sol
    assert receipt.signature == SIG
    assert "cluster=devnet" in receipt.explorer_url


def test_failed_tx_not_reported_as_confirmed():
    prepared = _prepare_allow()
    observed = Receipt(
        signature=SIG,
        fail_closed=False,
        reasons=(),
        confirmation_status="confirmed",
        slot=8,
        err={"InstructionError": [0, "Custom"]},
        explorer_url=f"https://explorer.solana.com/tx/{SIG}?cluster=devnet",
        network="devnet",
        rpc_used=True,
    )
    assert lifecycle_from_status(observed) == LIFECYCLE_FAILED
    receipt = build_ai4_receipt(
        prepared,
        lifecycle_state=LIFECYCLE_CONFIRMED,
        status_receipt=observed,
    )
    assert receipt.lifecycle_state == LIFECYCLE_FAILED
    assert receipt.observed_success is False
    assert receipt.error is not None
    summary = format_ai4_receipt_summary(receipt)
    assert "not a successful confirmation" in summary.lower()
    assert "Lifecycle: confirmed" not in summary
    assert "AI4 executed" not in summary
    payload = receipt.to_dict()
    assert payload["lifecycle_state"] == "failed"
    assert payload["observed_success"] is False


def test_finalized_represented_correctly():
    prepared = _prepare_allow()
    observed = Receipt(
        signature=SIG,
        fail_closed=False,
        reasons=(),
        confirmation_status="finalized",
        slot=99,
        err=None,
        explorer_url=f"https://explorer.solana.com/tx/{SIG}?cluster=devnet",
        network="devnet",
        rpc_used=True,
    )
    receipt = build_ai4_receipt(
        prepared,
        lifecycle_state=LIFECYCLE_FINALIZED,
        status_receipt=observed,
    )
    assert receipt.lifecycle_state == "finalized"
    assert receipt.confirmation_status == "finalized"
    assert receipt.slot == 99
    assert receipt.error is None
    assert receipt.fail_closed is False
    assert receipt.observed_success is True
    summary = format_ai4_receipt_summary(receipt)
    assert "On-chain status is finalized" in summary
    assert "AI4 did not execute the transfer" in summary


def test_receipt_rejects_non_devnet_network():
    with pytest.raises(ValueError, match="DevNet-only"):
        AI4Receipt(
            network="mainnet-beta",
            asset="SOL",
            action="transfer",
            amount="0.001",
            destination=DEST,
            approved_binding_hash="abc",
            decision="ALLOW",
            decision_report_summary={},
            decision_report_result="accept",
            signature=None,
            lifecycle_state=LIFECYCLE_PREPARED,
            confirmation_status=None,
            slot=None,
            error=None,
            timestamp="2026-01-01T00:00:00Z",
            explorer_url=None,
        )


def test_receipt_rejects_success_lifecycle_with_error():
    with pytest.raises(ValueError, match="on-chain error"):
        AI4Receipt(
            network="devnet",
            asset="SOL",
            action="transfer",
            amount="0.001",
            destination=DEST,
            approved_binding_hash="abc",
            decision="ALLOW",
            decision_report_summary={},
            decision_report_result="accept",
            signature=SIG,
            lifecycle_state=LIFECYCLE_FINALIZED,
            confirmation_status="finalized",
            slot=1,
            error={"err": True},
            timestamp="2026-01-01T00:00:00Z",
            explorer_url=f"https://explorer.solana.com/tx/{SIG}?cluster=devnet",
        )


def test_fail_closed_status_maps_to_fail_closed_lifecycle():
    observed = Receipt(
        signature=SIG,
        fail_closed=True,
        reasons=("confirmationStatus is missing or unknown; fail closed",),
        rpc_used=True,
        network="devnet",
    )
    assert lifecycle_from_status(observed) == LIFECYCLE_FAIL_CLOSED
    prepared = _prepare_allow()
    receipt = build_ai4_receipt(
        prepared,
        lifecycle_state=LIFECYCLE_FAIL_CLOSED,
        status_receipt=observed,
    )
    assert receipt.fail_closed is True
    assert receipt.observed_success is False
    assert "fail-closed (not confirmed)" in format_ai4_receipt_summary(receipt)


def test_deny_prepare_receipt_has_no_execution_claim():
    prepared = prepare_transfer(
        TransferIntent(network="devnet", asset="SOL", amount="0.001", destination=DEST),
        evaluate_fn=lambda _text: fixture_report(decision="refuse"),
    )
    assert prepared.decision is Decision.DENY
    receipt = build_ai4_receipt(
        prepared,
        lifecycle_state=LIFECYCLE_FAIL_CLOSED,
        extra_reasons=("prepare denied; no wallet handoff",),
    )
    assert receipt.approved_binding_hash is None
    assert receipt.signature is None
    assert receipt.explorer_url is None
    assert receipt.fail_closed is True
    assert ATTRIBUTION in receipt.attribution
