"""Adversarial decision-to-handoff binding and DENY invariants."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from ai4.transaction.binding import verify_solana_pay_binding
from ai4.transaction.errors import TransactionControlError
from ai4.transaction.handoff import (
    AI4_NETWORK_QUERY_KEY,
    phantom_browse_uri,
    solana_pay_transfer_uri,
)
from ai4.transaction.prepare import prepare_transfer
from ai4.transaction.types import Decision, TransferIntent
from ai4.transaction.validate import validate_transfer_intent
from tests.transaction_util import fixture_report, solana_address

DEST = solana_address(41)
OTHER = solana_address(42)


def _intent(**overrides) -> TransferIntent:
    payload = {
        "network": "mainnet-beta",
        "asset": "SOL",
        "amount": "0.25",
        "destination": DEST,
    }
    payload.update(overrides)
    return TransferIntent(**payload)


def _normalized(**overrides):
    return validate_transfer_intent(_intent(**overrides))


def test_verifier_rejects_amount_mutated_after_report():
    intent = _normalized()
    forged = solana_pay_transfer_uri(intent.destination, Decimal("0.9"), network=intent.network)
    with pytest.raises(TransactionControlError) as exc:
        verify_solana_pay_binding(forged, intent)
    assert "amount" in exc.value.reasons[0]


def test_verifier_rejects_destination_mutated_after_report():
    intent = _normalized()
    forged = solana_pay_transfer_uri(OTHER, intent.amount, network=intent.network)
    with pytest.raises(TransactionControlError) as exc:
        verify_solana_pay_binding(forged, intent)
    assert "destination" in exc.value.reasons[0]


def test_verifier_rejects_wrong_cluster_marker():
    intent = _normalized(network="mainnet-beta")
    forged = solana_pay_transfer_uri(intent.destination, intent.amount, network="devnet")
    with pytest.raises(TransactionControlError) as exc:
        verify_solana_pay_binding(forged, intent)
    assert "cluster" in exc.value.reasons[0]


def test_verifier_rejects_spl_token_and_duplicate_amount():
    intent = _normalized()
    with pytest.raises(TransactionControlError):
        verify_solana_pay_binding(
            f"solana:{intent.destination}?amount=0.25&spl-token=So11111111111111111111111111111111111111112"
            f"&{AI4_NETWORK_QUERY_KEY}=mainnet-beta&label=AI4 transfer on Solana mainnet-beta"
            f"&message=Unsigned SOL transfer on Solana mainnet-beta. x",
            intent,
        )
    with pytest.raises(TransactionControlError):
        verify_solana_pay_binding(
            f"solana:{intent.destination}?amount=0.25&amount=9"
            f"&{AI4_NETWORK_QUERY_KEY}=mainnet-beta&label=AI4 transfer on Solana mainnet-beta"
            f"&message=Unsigned SOL transfer on Solana mainnet-beta. x",
            intent,
        )


def test_allow_uri_contains_approved_cluster_and_parses_back():
    result = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
    )
    assert result.decision is Decision.ALLOW
    assert result.handoff_uri is not None
    parsed = urlparse(result.handoff_uri)
    assert parsed.scheme == "solana"
    assert parsed.path == DEST
    query = parse_qs(parsed.query)
    assert query["amount"] == ["0.25"]
    assert query[AI4_NETWORK_QUERY_KEY] == ["mainnet-beta"]
    assert "spl-token" not in query
    verify_solana_pay_binding(result.handoff_uri, result.intent)
    assert result.approved_binding is not None
    assert result.approved_binding.to_dict()["network"] == "mainnet-beta"


def test_prepare_denies_and_strips_handoff_if_builder_mutates_amount(monkeypatch):
    def mutated(intent):
        uri = solana_pay_transfer_uri(intent.destination, Decimal("0.99"), network=intent.network)
        return uri, phantom_browse_uri(uri)

    monkeypatch.setattr("ai4.transaction.prepare.handoff_uris_for_intent", mutated)
    result = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: fixture_report(decision="accept"),
    )
    assert result.decision is Decision.DENY
    assert result.handoff_uri is None
    assert result.phantom_browse_uri is None
    assert result.unsigned_payload is None
    assert result.approved_binding is None


def test_deny_paths_never_emit_handoff():
    cases = [
        _intent(request_custody=True),
        _intent(server_sign=True),
        _intent(amount="0"),
        _intent(amount="-1"),
        _intent(amount="2"),
        _intent(network="ethereum"),
        _intent(asset="USDC"),
        _intent(action="buy"),
        _intent(destination=DEST + "?amount=9&"),
    ]
    for intent in cases:
        result = prepare_transfer(
            intent,
            evaluate_fn=lambda _text: fixture_report(decision="accept"),
        )
        assert result.decision is Decision.DENY, intent
        assert result.handoff_uri is None
        assert result.phantom_browse_uri is None
        assert result.unsigned_payload is None


def test_deny_prepareresult_cannot_carry_handoff():
    from ai4.transaction.types import PrepareResult

    with pytest.raises(ValueError):
        PrepareResult(
            decision=Decision.DENY,
            reasons=("nope",),
            summary="Denied",
            handoff_uri="solana:x",
        )


def test_deny_after_constrain_cannot_carry_handoff():
    for decision in ("refuse", "revise"):
        result = prepare_transfer(
            _intent(),
            evaluate_fn=lambda _text, d=decision: fixture_report(decision=d),
        )
        assert result.decision is Decision.DENY
        assert result.handoff_uri is None
        assert result.unsigned_payload is None
        assert result.report is not None

    timeout = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: fixture_report(
            outcome_kind="execution",
            decision=None,
            terminal="timed_out",
            mode="constrained_loop",
        ),
    )
    assert timeout.decision is Decision.DENY
    assert timeout.handoff_uri is None

    errored = prepare_transfer(
        _intent(),
        evaluate_fn=lambda _text: (_ for _ in ()).throw(RuntimeError("evaluator down")),
    )
    assert errored.decision is Decision.DENY
    assert errored.handoff_uri is None
