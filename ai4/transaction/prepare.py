"""Prepare a v1 SOL transfer: validate, firewall, bind unsigned handoff."""

from __future__ import annotations

from ai4.constrain.report import DecisionReport
from ai4.transaction.binding import verify_approved_handoff
from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.firewall import EvaluateFn, run_firewall
from ai4.transaction.handoff import handoff_uris_for_intent
from ai4.transaction.rpc import RpcPost, json_rpc_post, resolve_rpc_url
from ai4.transaction.types import (
    Decision,
    NormalizedIntent,
    PrepareResult,
    TransferConfig,
    TransferIntent,
    UnsignedPayload,
    approved_binding_from_intent,
    format_sol_amount,
)
from ai4.transaction.validate import validate_transfer_intent


def _fee_from_rpc(
    rpc_url: str,
    *,
    rpc_post: RpcPost,
    timeout_s: float,
) -> tuple[str, str]:
    """Confirm chain reachability and a fee hint. Fail closed if ambiguous."""

    blockhash_body = rpc_post(rpc_url, "getLatestBlockhash", [{"commitment": "confirmed"}], timeout_s)
    result = blockhash_body.get("result")
    if not isinstance(result, dict):
        raise TransactionControlError(
            "getLatestBlockhash result is ambiguous; fail closed",
            reasons=("getLatestBlockhash result is not an object",),
        )
    value = result.get("value")
    if not isinstance(value, dict) or not value.get("blockhash"):
        raise TransactionControlError(
            "latest blockhash is missing; fail closed",
            reasons=("latest blockhash is missing or empty",),
        )

    fees_body = rpc_post(rpc_url, "getRecentPrioritizationFees", [[]], timeout_s)
    fees_result = fees_body.get("result")
    if not isinstance(fees_result, list):
        raise TransactionControlError(
            "fee response is ambiguous; fail closed",
            reasons=("getRecentPrioritizationFees result is not a list",),
        )
    samples: list[int] = []
    for item in fees_result:
        if not isinstance(item, dict):
            raise TransactionControlError(
                "fee sample is ambiguous; fail closed",
                reasons=("a prioritization-fee sample is not an object",),
            )
        raw = item.get("prioritizationFee")
        if raw is None:
            raise TransactionControlError(
                "fee sample is missing prioritizationFee; fail closed",
                reasons=("a prioritization-fee sample is missing prioritizationFee",),
            )
        try:
            samples.append(int(raw))
        except (TypeError, ValueError) as exc:
            raise TransactionControlError(
                "fee sample is not an integer; fail closed",
                reasons=("a prioritization-fee sample is not an integer",),
            ) from exc

    if samples:
        typical = sorted(samples)[len(samples) // 2]
        hint = (
            f"recent median prioritization fee sample: {typical} micro-lamports per CU; "
            "base signature fee is still quoted by the wallet"
        )
    else:
        hint = (
            "no recent prioritization-fee samples; base signature fee is quoted by the wallet"
        )
    return (
        "rpc_hint",
        (
            f"{hint}. Chain blockhash was reachable. The wallet shows the exact fee "
            "before you sign. AI4 does not hold keys or assets."
        ),
    )


def _unsigned_payload(intent: NormalizedIntent) -> UnsignedPayload:
    return UnsignedPayload(
        kind="solana_system_transfer_stub",
        network=intent.network.value,
        asset=intent.asset.value,
        amount_sol=format_sol_amount(intent.amount),
        lamports=intent.lamports,
        destination=intent.destination,
    )


def _deny(
    *,
    reasons: tuple[str, ...],
    fee_status: str,
    fee_note: str,
    intent: NormalizedIntent | None = None,
    report: DecisionReport | None = None,
) -> PrepareResult:
    denied = PrepareResult(
        decision=Decision.DENY,
        reasons=reasons,
        summary="",
        intent=intent,
        report=report,
        unsigned_payload=None,
        handoff_uri=None,
        phantom_browse_uri=None,
        fee_status=fee_status,
        fee_note=fee_note,
        approved_binding=None,
    )
    return PrepareResult(
        decision=Decision.DENY,
        reasons=denied.reasons,
        summary=format_prepare_summary(denied),
        intent=intent,
        report=report,
        unsigned_payload=None,
        handoff_uri=None,
        phantom_browse_uri=None,
        fee_status=fee_status,
        fee_note=fee_note,
        approved_binding=None,
    )


def format_prepare_summary(result: PrepareResult) -> str:
    lines = [f"Decision: {result.decision.value}"]
    if result.intent is not None:
        lines.extend(
            [
                f"Network: Solana {result.intent.network.value}",
                f"Asset: {result.intent.asset.value}",
                f"Action: {result.intent.action}",
                f"Amount: {format_sol_amount(result.intent.amount)} SOL",
                f"Destination: {result.intent.destination}",
            ]
        )
    fee_note = result.fee_note or result.fee_status
    lines.append(f"Estimated fee: {fee_note}")
    lines.append("AI4 does not hold keys or assets.")
    if result.reasons:
        lines.append("Reasons: " + "; ".join(result.reasons))
    if result.decision is Decision.ALLOW:
        lines.append("Prepare complete. Sign in your wallet. Later: status plus explorer.")
        if result.approved_binding is not None:
            lines.append(
                "Approved binding: "
                f"{result.approved_binding.action} {result.approved_binding.amount_sol} "
                f"{result.approved_binding.asset} on Solana {result.approved_binding.network} "
                f"to {result.approved_binding.destination}."
            )
        if result.handoff_uri:
            lines.append(f"Wallet handoff URI: {result.handoff_uri}")
        if result.phantom_browse_uri:
            lines.append(f"Phantom browse URI (MOBILE_ONLY): {result.phantom_browse_uri}")
            lines.append(
                "Phantom browse Universal Link is MOBILE_ONLY (iOS/Android in-app browser). "
                "The Chrome/desktop extension does not consume it."
            )
        lines.append(
            "Wallet cluster is a user setting. The URI records ai4-network for binding; "
            "confirm the wallet is on the same Solana cluster before you sign."
        )
    else:
        lines.append("Denied. No unsigned payload and no wallet handoff.")
    return "\n".join(lines)


def prepare_transfer(
    intent: TransferIntent,
    *,
    config: TransferConfig | None = None,
    evaluate_fn: EvaluateFn | None = None,
    rpc_url: str | None = None,
    rpc_post: RpcPost | None = None,
    timeout_s: float = 10.0,
) -> PrepareResult:
    """Validate, run the firewall, and on ALLOW emit a bound unsigned handoff.

    On DENY, return the DecisionReport (when constrain ran) and reasons only.
    Handoff URIs and unsigned payloads are never set on DENY.
    """

    cfg = config or TransferConfig()
    resolved_rpc = resolve_rpc_url(rpc_url if rpc_url is not None else cfg.rpc_url)
    fee_status = "unverified_no_rpc"
    fee_note = (
        "not verified (no RPC URL); your wallet will show the fee before you sign"
    )

    try:
        normalized = validate_transfer_intent(intent, config=cfg)
    except TransactionValidationError as exc:
        return _deny(
            reasons=exc.reasons,
            fee_status=fee_status,
            fee_note=fee_note,
        )

    if resolved_rpc:
        poster = rpc_post or json_rpc_post
        try:
            fee_status, fee_note = _fee_from_rpc(
                resolved_rpc, rpc_post=poster, timeout_s=timeout_s
            )
        except TransactionControlError as exc:
            return _deny(
                reasons=exc.reasons,
                intent=normalized,
                fee_status="rpc_fail_closed",
                fee_note="fee or chain state could not be verified; fail closed",
            )
        except Exception as exc:
            return _deny(
                reasons=(f"RPC failed closed: {exc}",),
                intent=normalized,
                fee_status="rpc_fail_closed",
                fee_note="fee or chain state could not be verified; fail closed",
            )

    firewall = run_firewall(normalized, config=cfg, evaluate_fn=evaluate_fn)
    if firewall.decision is not Decision.ALLOW:
        return _deny(
            reasons=firewall.reasons,
            intent=normalized,
            report=firewall.report,
            fee_status=fee_status,
            fee_note=fee_note,
        )

    # Binding is enforced here, not inferred from DecisionReport prose.
    pay_uri, phantom_uri = handoff_uris_for_intent(normalized)
    try:
        verify_approved_handoff(pay_uri, phantom_uri, normalized)
    except TransactionControlError as exc:
        return _deny(
            reasons=exc.reasons,
            intent=normalized,
            report=firewall.report,
            fee_status=fee_status,
            fee_note=fee_note,
        )

    binding = approved_binding_from_intent(normalized)
    allowed = PrepareResult(
        decision=Decision.ALLOW,
        reasons=firewall.reasons,
        summary="",
        intent=normalized,
        report=firewall.report,
        unsigned_payload=_unsigned_payload(normalized),
        handoff_uri=pay_uri,
        phantom_browse_uri=phantom_uri,
        fee_status=fee_status,
        fee_note=fee_note,
        approved_binding=binding,
    )
    return PrepareResult(
        decision=Decision.ALLOW,
        reasons=allowed.reasons,
        summary=format_prepare_summary(allowed),
        intent=normalized,
        report=firewall.report,
        unsigned_payload=allowed.unsigned_payload,
        handoff_uri=pay_uri,
        phantom_browse_uri=phantom_uri,
        fee_status=fee_status,
        fee_note=fee_note,
        approved_binding=binding,
    )
