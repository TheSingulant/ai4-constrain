"""status() fails closed without a clear RPC result."""

from __future__ import annotations

from ai4.transaction.errors import TransactionControlError
from ai4.transaction.status import status
from tests.transaction_util import solana_signature

SIG = solana_signature()


def test_status_fail_closed_without_rpc(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    receipt = status(SIG)
    assert receipt.fail_closed is True
    assert receipt.rpc_used is False
    assert any("no Solana RPC URL" in item for item in receipt.reasons)


def test_status_fail_closed_on_empty_env(monkeypatch):
    monkeypatch.setenv("AI4_SOLANA_RPC_URL", "   ")
    receipt = status(SIG)
    assert receipt.fail_closed is True


def test_status_fail_closed_on_bad_signature():
    receipt = status("not-a-sig", rpc_url="https://rpc.example.test")
    assert receipt.fail_closed is True
    assert receipt.rpc_used is False


def test_status_fail_closed_when_rpc_raises():
    def boom(_url, _method, _params, _timeout):
        raise TransactionControlError("Solana RPC unreachable; fail closed", reasons=("RPC unreachable",))

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=boom)
    assert receipt.fail_closed is True
    assert receipt.rpc_used is True
    assert "RPC unreachable" in receipt.reasons[0]


def test_status_fail_closed_when_value_null():
    def fake(_url, _method, _params, _timeout):
        return {"result": {"value": [None]}}

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=fake)
    assert receipt.fail_closed is True
    assert "not found" in receipt.reasons[0]


def test_status_fail_closed_when_confirmation_unknown():
    def fake(_url, _method, _params, _timeout):
        return {"result": {"value": [{"confirmationStatus": "maybe", "slot": 1, "err": None}]}}

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=fake)
    assert receipt.fail_closed is True


def test_status_processed_is_pending_like_not_fail_closed():
    def fake(_url, _method, _params, _timeout):
        return {"result": {"value": [{"confirmationStatus": "processed", "slot": 7, "err": None}]}}

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=fake)
    assert receipt.fail_closed is False
    assert receipt.confirmation_status == "processed"
    from ai4.transaction.status import format_status_summary

    text = format_status_summary(receipt)
    assert "pending-like" in text
    assert "not yet confirmed" in text


def test_status_fail_closed_summary_never_says_confirmed():
    from ai4.transaction.status import format_status_summary
    from ai4.transaction.types import Receipt

    leaked = Receipt(
        signature=SIG,
        fail_closed=True,
        reasons=("slot is not an integer; fail closed",),
        confirmation_status="confirmed",
        rpc_used=True,
    )
    text = format_status_summary(leaked)
    assert "Status: fail-closed (not confirmed)" in text
    assert "Confirmation: confirmed" not in text


def test_status_fail_closed_on_malformed_result_object():
    def fake(_url, _method, _params, _timeout):
        return {"result": ["not-an-object"]}

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=fake)
    assert receipt.fail_closed is True


def test_status_fail_closed_on_empty_value_list():
    def fake(_url, _method, _params, _timeout):
        return {"result": {"value": []}}

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=fake)
    assert receipt.fail_closed is True
    def fake(_url, _method, _params, _timeout):
        return {"result": {"value": [{"confirmationStatus": "finalized", "slot": 99, "err": None}]}}

    receipt = status(
        SIG,
        rpc_url="https://rpc.example.test",
        network="devnet",
        rpc_post=fake,
    )
    assert receipt.fail_closed is False
    assert receipt.confirmation_status == "finalized"
    assert receipt.slot == 99
    assert receipt.err is None
    assert receipt.explorer_url is not None
    assert "cluster=devnet" in receipt.explorer_url
    assert SIG in receipt.explorer_url


def test_status_found_on_chain_error_is_not_ambiguous():
    def fake(_url, _method, _params, _timeout):
        return {
            "result": {
                "value": [{"confirmationStatus": "confirmed", "slot": 4, "err": {"InstructionError": [0, "Custom"]}}]
            }
        }

    receipt = status(SIG, rpc_url="https://rpc.example.test", rpc_post=fake)
    assert receipt.fail_closed is False
    assert receipt.err is not None
