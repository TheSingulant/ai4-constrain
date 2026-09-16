"""Firewall maps constrain outcomes and fails closed."""

from __future__ import annotations

from ai4.constrain.errors import ConstraintExecutionError
from ai4.transaction.firewall import build_firewall_proposal, map_constrain_decision, run_firewall
from ai4.transaction.types import Decision, TransferIntent
from tests.transaction_util import fixture_report, solana_address

DEST = solana_address(11)


def _intent(**overrides) -> TransferIntent:
    payload = {
        "network": "devnet",
        "asset": "SOL",
        "amount": "0.05",
        "destination": DEST,
    }
    payload.update(overrides)
    return TransferIntent(**payload)


def test_map_accept_allow_others_deny():
    assert map_constrain_decision(fixture_report(decision="accept"))[0] is Decision.ALLOW
    assert map_constrain_decision(fixture_report(decision="refuse"))[0] is Decision.DENY
    assert map_constrain_decision(fixture_report(decision="revise"))[0] is Decision.DENY
    assert (
        map_constrain_decision(
            fixture_report(
                outcome_kind="execution",
                decision=None,
                terminal="timed_out",
                mode="constrained_loop",
            )
        )[0]
        is Decision.DENY
    )
    assert map_constrain_decision(None)[0] is Decision.DENY


def test_validation_deny_skips_constrain():
    called = {"n": 0}

    def boom(_text: str):
        called["n"] += 1
        raise AssertionError("constrain must not run on invalid intent")

    result = run_firewall(_intent(request_custody=True), evaluate_fn=boom)
    assert result.decision is Decision.DENY
    assert called["n"] == 0
    assert result.report is None
    assert any("custody" in item for item in result.reasons)


def test_allow_with_fixture_evaluate():
    result = run_firewall(_intent(), evaluate_fn=lambda _text: fixture_report(decision="accept"))
    assert result.decision is Decision.ALLOW
    assert result.report is not None
    assert result.report.decision == "accept"
    assert DEST in result.proposal_text


def test_deny_when_constrain_refuses():
    result = run_firewall(_intent(), evaluate_fn=lambda _text: fixture_report(decision="refuse"))
    assert result.decision is Decision.DENY
    assert result.report is not None
    assert result.report.decision == "refuse"


def test_deny_when_constrain_asks_revise():
    result = run_firewall(_intent(), evaluate_fn=lambda _text: fixture_report(decision="revise"))
    assert result.decision is Decision.DENY


def test_deny_when_constrain_raises():
    def fail(_text: str):
        raise ConstraintExecutionError("evaluator unavailable")

    result = run_firewall(_intent(), evaluate_fn=fail)
    assert result.decision is Decision.DENY
    assert result.report is None
    assert any("fail closed" in item or "failed closed" in item for item in result.reasons)


def test_deny_when_evaluate_returns_wrong_type():
    result = run_firewall(_intent(), evaluate_fn=lambda _text: {"decision": "accept"})  # type: ignore[arg-type]
    assert result.decision is Decision.DENY


def test_default_evaluate_only_path_accepts_clean_proposal():
    result = run_firewall(_intent())
    assert result.decision is Decision.ALLOW
    assert result.report is not None
    assert result.report.mode == "evaluate_only"
    assert "transfer native SOL" in result.proposal_text


def test_proposal_text_is_checkable_and_has_no_keys():
    from ai4.transaction.validate import validate_transfer_intent

    normalized = validate_transfer_intent(_intent())
    text = build_firewall_proposal(normalized)
    assert "private key" not in text.lower()
    assert "seed" not in text.lower()
    assert "BEGIN" not in text
    assert normalized.destination in text
