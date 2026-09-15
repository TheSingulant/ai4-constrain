"""prepare_transfer ALLOW and DENY paths."""

from __future__ import annotations

from ai4.transaction.prepare import prepare_transfer
from ai4.transaction.types import Decision, TransferConfig, TransferIntent
from tests.transaction_util import fixture_report, solana_address

DEST = solana_address(19)


def _intent(**overrides) -> TransferIntent:
    payload = {
        "network": "mainnet-beta",
        "asset": "SOL",
        "amount": "0.25",
        "destination": DEST,
    }
    payload.update(overrides)
    return TransferIntent(**payload)


def test_allow_emits_unsigned_stub_and_handoff():
    result = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
    )
    assert result.decision is Decision.ALLOW
    assert result.report is not None
    assert result.unsigned_payload is not None
    assert result.unsigned_payload.kind == "solana_system_transfer_stub"
    assert result.unsigned_payload.destination == DEST
    assert result.handoff_uri is not None
    assert result.handoff_uri.startswith("solana:" + DEST)
    assert "amount=0.25" in result.handoff_uri
    assert result.phantom_browse_uri is not None
    assert result.phantom_browse_uri.startswith("https://phantom.app/ul/browse/")
    assert "AI4 does not hold keys or assets" in result.summary
    assert "Sign in your wallet" in result.summary


def test_deny_returns_report_only():
    result = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: fixture_report(decision="refuse"),
    )
    assert result.decision is Decision.DENY
    assert result.report is not None
    assert result.unsigned_payload is None
    assert result.handoff_uri is None
    assert result.phantom_browse_uri is None
    assert "Denied" in result.summary


def test_deny_custody_has_no_report_and_no_handoff():
    result = prepare_transfer(_intent(server_sign=True))
    assert result.decision is Decision.DENY
    assert result.report is None
    assert result.unsigned_payload is None


def test_deny_over_cap_before_firewall():
    result = prepare_transfer(
        _intent(amount="5"),
        config=TransferConfig(max_amount_sol="1"),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
    )
    assert result.decision is Decision.DENY
    assert result.report is None
    assert any("exceeds cap" in item for item in result.reasons)


def test_prepare_without_rpc_does_not_claim_verified_fee():
    result = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
    )
    assert result.fee_status == "unverified_no_rpc"
    assert "not verified" in result.fee_note


def test_prepare_with_rpc_fail_closed():
    def boom(_url, _method, _params, _timeout):
        raise ConnectionError("nope")

    result = prepare_transfer(
        _intent(),
        config=TransferConfig(rpc_url="https://rpc.example.invalid"),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
        rpc_post=boom,
    )
    assert result.decision is Decision.DENY
    assert result.fee_status == "rpc_fail_closed"
    assert result.unsigned_payload is None


def test_prepare_with_rpc_hint_on_allow():
    def fake_rpc(_url, method, _params, _timeout):
        if method == "getLatestBlockhash":
            return {"result": {"value": {"blockhash": "11111111111111111111111111111111"}}}
        if method == "getRecentPrioritizationFees":
            return {"result": [{"slot": 1, "prioritizationFee": 1000}]}
        raise AssertionError(method)

    result = prepare_transfer(
        _intent(),
        rpc_url="https://rpc.example.test",
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
        rpc_post=fake_rpc,
    )
    assert result.decision is Decision.ALLOW
    assert result.fee_status == "rpc_hint"
    assert "prioritization fee" in result.fee_note
