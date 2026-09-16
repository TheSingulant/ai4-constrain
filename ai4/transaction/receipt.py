"""AI4 transfer proof receipt. Observation only; AI4 does not execute transfers.

This is distinct from :class:`ai4.transaction.types.Receipt`, which is the raw
``status()`` RPC observation. ``AI4Receipt`` binds the approved handoff into a
structured proof record after the user wallet signs and broadcasts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ai4.constrain.report import DecisionReport
from ai4.transaction.errors import TransactionValidationError
from ai4.transaction.types import (
    EXPLORER_TX,
    ApprovedBinding,
    Decision,
    Network,
    PrepareResult,
    Receipt,
    format_sol_amount,
)
from ai4.transaction.validate import validate_solana_signature

ATTRIBUTION = (
    "Prepared and constrained by AI4; signed and broadcast by the user's wallet."
)

LIFECYCLE_PREPARED = "prepared"
LIFECYCLE_AWAITING_BROADCAST = "awaiting_broadcast"
LIFECYCLE_PROCESSED = "processed"
LIFECYCLE_CONFIRMED = "confirmed"
LIFECYCLE_FINALIZED = "finalized"
LIFECYCLE_FAILED = "failed"
LIFECYCLE_FAIL_CLOSED = "fail_closed"
LIFECYCLE_TIMEOUT = "timeout"

SUCCESS_LIFECYCLES = frozenset(
    {LIFECYCLE_PROCESSED, LIFECYCLE_CONFIRMED, LIFECYCLE_FINALIZED}
)
KNOWN_LIFECYCLES = frozenset(
    {
        LIFECYCLE_PREPARED,
        LIFECYCLE_AWAITING_BROADCAST,
        LIFECYCLE_PROCESSED,
        LIFECYCLE_CONFIRMED,
        LIFECYCLE_FINALIZED,
        LIFECYCLE_FAILED,
        LIFECYCLE_FAIL_CLOSED,
        LIFECYCLE_TIMEOUT,
    }
)

REQUIRED_RECEIPT_FIELDS = (
    "network",
    "asset",
    "action",
    "amount",
    "destination",
    "approved_binding_hash",
    "decision_report_summary",
    "decision_report_result",
    "signature",
    "lifecycle_state",
    "confirmation_status",
    "slot",
    "error",
    "timestamp",
    "explorer_url",
)


def utc_timestamp(now: datetime | None = None) -> str:
    stamp = now if now is not None else datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def summarize_decision_report(
    report: DecisionReport | None,
    *,
    product_decision: Decision,
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    """Compact DecisionReport view. Not a claim that AI4 executed a transfer."""

    return {
        "product_decision": product_decision.value,
        "constrain_decision": None if report is None else report.decision,
        "mode": None if report is None else report.mode,
        "outcome_kind": None if report is None else report.outcome_kind,
        "decision_reason": None if report is None else report.decision_reason,
        "terminal": None if report is None else report.terminal,
        "reasons": list(reasons),
    }


def lifecycle_from_status(status_receipt: Receipt) -> str:
    """Map a ``status()`` observation onto a proof lifecycle. Fail closed."""

    if status_receipt.fail_closed:
        reasons = " ".join(status_receipt.reasons).lower()
        if "timed out" in reasons or "timeout" in reasons:
            return LIFECYCLE_TIMEOUT
        return LIFECYCLE_FAIL_CLOSED
    if status_receipt.err is not None:
        return LIFECYCLE_FAILED
    confirmation = status_receipt.confirmation_status
    if confirmation == LIFECYCLE_FINALIZED:
        return LIFECYCLE_FINALIZED
    if confirmation == LIFECYCLE_CONFIRMED:
        return LIFECYCLE_CONFIRMED
    if confirmation == LIFECYCLE_PROCESSED:
        return LIFECYCLE_PROCESSED
    return LIFECYCLE_FAIL_CLOSED


def explorer_url_for_devnet(signature: str | None) -> str | None:
    if not signature:
        return None
    template = EXPLORER_TX[Network.DEVNET]
    if not template:
        return None
    return template.format(signature=signature)


@dataclass(frozen=True)
class AI4Receipt:
    """Structured proof receipt for a DevNet SOL transfer handoff.

    Never claims that AI4 signed, broadcast, or executed the transfer.
    """

    network: str
    asset: str
    action: str
    amount: str
    destination: str
    approved_binding_hash: str | None
    decision: str
    decision_report_summary: Mapping[str, Any]
    decision_report_result: str | None
    signature: str | None
    lifecycle_state: str
    confirmation_status: str | None
    slot: int | None
    error: Any
    timestamp: str
    explorer_url: str | None
    approved_binding: Mapping[str, Any] | None = None
    attribution: str = ATTRIBUTION
    fail_closed: bool = False
    reasons: tuple[str, ...] = ()
    observed_success: bool = field(init=False)

    def __post_init__(self) -> None:
        if self.network != Network.DEVNET.value:
            raise ValueError("AI4Receipt is DevNet-only; network must be 'devnet'")
        if self.attribution != ATTRIBUTION:
            raise ValueError("AI4Receipt attribution wording must not be altered")
        if self.lifecycle_state not in KNOWN_LIFECYCLES:
            raise ValueError(f"unknown lifecycle_state: {self.lifecycle_state!r}")
        if self.lifecycle_state in SUCCESS_LIFECYCLES and self.error is not None:
            raise ValueError("on-chain error cannot be represented as a successful confirmation")
        if self.lifecycle_state == LIFECYCLE_FINALIZED and self.confirmation_status != "finalized":
            raise ValueError("finalized lifecycle requires confirmation_status='finalized'")
        if self.lifecycle_state == LIFECYCLE_FAILED and self.error is None:
            raise ValueError("failed lifecycle requires an on-chain error")
        if self.lifecycle_state in {LIFECYCLE_FAIL_CLOSED, LIFECYCLE_TIMEOUT} and not self.fail_closed:
            raise ValueError("fail-closed and timeout receipts must set fail_closed=True")
        binding = self.approved_binding
        if binding is not None and self.approved_binding_hash:
            binding_hash = binding.get("sha256")
            if binding_hash is not None and binding_hash != self.approved_binding_hash:
                raise ValueError("approved_binding_hash does not match approved_binding.sha256")
        if self.explorer_url and "cluster=devnet" not in self.explorer_url:
            raise ValueError("explorer_url must be a DevNet cluster link")
        if self.explorer_url and not self.signature:
            raise ValueError("explorer_url requires a user-supplied signature")

        object.__setattr__(self, "decision_report_summary", dict(self.decision_report_summary))
        object.__setattr__(
            self,
            "approved_binding",
            None if self.approved_binding is None else dict(self.approved_binding),
        )
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(
            self,
            "observed_success",
            (
                self.lifecycle_state in SUCCESS_LIFECYCLES
                and self.error is None
                and not self.fail_closed
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "asset": self.asset,
            "action": self.action,
            "amount": self.amount,
            "destination": self.destination,
            "approved_binding_hash": self.approved_binding_hash,
            "approved_binding": self.approved_binding,
            "decision": self.decision,
            "decision_report_summary": dict(self.decision_report_summary),
            "decision_report_result": self.decision_report_result,
            "signature": self.signature,
            "lifecycle_state": self.lifecycle_state,
            "confirmation_status": self.confirmation_status,
            "slot": self.slot,
            "error": self.error,
            "timestamp": self.timestamp,
            "explorer_url": self.explorer_url,
            "attribution": self.attribution,
            "fail_closed": self.fail_closed,
            "reasons": list(self.reasons),
            "observed_success": self.observed_success,
        }


def format_ai4_receipt_summary(receipt: AI4Receipt) -> str:
    lines = [
        f"Network: Solana {receipt.network}",
        f"Asset: {receipt.asset}",
        f"Action: {receipt.action}",
        f"Amount: {receipt.amount} SOL",
        f"Destination: {receipt.destination}",
        f"Product decision: {receipt.decision}",
        f"DecisionReport result: {receipt.decision_report_result}",
        f"Approved binding hash: {receipt.approved_binding_hash}",
        f"Lifecycle: {receipt.lifecycle_state}",
        f"Signature: {receipt.signature}",
        f"Slot: {receipt.slot}",
        f"Explorer: {receipt.explorer_url}",
        f"Fail closed: {receipt.fail_closed}",
        receipt.attribution,
    ]
    if receipt.lifecycle_state == LIFECYCLE_FAILED:
        lines.append(
            f"RPC confirmationStatus of a failed transaction: {receipt.confirmation_status}"
        )
        lines.append("On-chain error observed. This is not a successful confirmation.")
    else:
        lines.append(f"Confirmation status: {receipt.confirmation_status}")
    if receipt.fail_closed:
        lines.append("Status: fail-closed (not confirmed).")
    if receipt.observed_success and receipt.lifecycle_state == LIFECYCLE_FINALIZED:
        lines.append("On-chain status is finalized. AI4 did not execute the transfer.")
    if receipt.reasons:
        lines.append("Reasons: " + "; ".join(receipt.reasons))
    lowered = "\n".join(lines).lower()
    if "ai4 executed" in lowered or "ai4 signed" in lowered or "ai4 broadcast" in lowered:
        raise ValueError("receipt summary must not claim AI4 executed the transfer")
    return "\n".join(lines)


def build_ai4_receipt(
    prepare: PrepareResult,
    *,
    lifecycle_state: str,
    status_receipt: Receipt | None = None,
    signature: str | None = None,
    timestamp: str | None = None,
    extra_reasons: tuple[str, ...] = (),
) -> AI4Receipt:
    """Bind prepare + optional status observation into an AI4 proof receipt."""

    intent = prepare.intent
    binding: ApprovedBinding | None = prepare.approved_binding
    if intent is None:
        network = Network.DEVNET.value
        asset = "SOL"
        action = "transfer"
        amount = ""
        destination = ""
    else:
        if intent.network is not Network.DEVNET:
            raise ValueError("AI4Receipt builder refuses non-devnet prepare results")
        network = intent.network.value
        asset = intent.asset.value
        action = intent.action
        amount = format_sol_amount(intent.amount)
        destination = intent.destination

    if binding is not None and binding.network != Network.DEVNET.value:
        raise ValueError("approved binding is not devnet; refusing receipt")

    sig = signature
    confirmation = None
    slot = None
    error = None
    fail_closed = lifecycle_state in {LIFECYCLE_FAIL_CLOSED, LIFECYCLE_TIMEOUT}
    reasons = tuple(prepare.reasons) + tuple(extra_reasons)
    explorer = None

    if status_receipt is not None:
        sig = status_receipt.signature or sig
        confirmation = status_receipt.confirmation_status
        slot = status_receipt.slot
        error = status_receipt.err
        fail_closed = bool(status_receipt.fail_closed) or fail_closed
        reasons = reasons + tuple(status_receipt.reasons)
        explorer = status_receipt.explorer_url
        if lifecycle_state in SUCCESS_LIFECYCLES and error is not None:
            lifecycle_state = LIFECYCLE_FAILED

    if lifecycle_state == LIFECYCLE_FAILED and error is None:
        error = {"ai4": "on-chain error required for failed lifecycle"}

    if sig:
        try:
            sig = validate_solana_signature(sig)
        except TransactionValidationError:
            sig = None
            explorer = None
    if sig and explorer is None:
        explorer = explorer_url_for_devnet(sig)
    if not sig:
        explorer = None

    summary = summarize_decision_report(
        prepare.report,
        product_decision=prepare.decision,
        reasons=prepare.reasons,
    )
    return AI4Receipt(
        network=network,
        asset=asset,
        action=action,
        amount=amount,
        destination=destination,
        approved_binding_hash=None if binding is None else binding.sha256(),
        approved_binding=None if binding is None else binding.to_dict(),
        decision=prepare.decision.value,
        decision_report_summary=summary,
        decision_report_result=None if prepare.report is None else prepare.report.decision,
        signature=sig,
        lifecycle_state=lifecycle_state,
        confirmation_status=confirmation,
        slot=slot,
        error=error,
        timestamp=timestamp or utc_timestamp(),
        explorer_url=explorer,
        fail_closed=fail_closed,
        reasons=reasons,
    )


__all__ = [
    "AI4Receipt",
    "ATTRIBUTION",
    "KNOWN_LIFECYCLES",
    "LIFECYCLE_AWAITING_BROADCAST",
    "LIFECYCLE_CONFIRMED",
    "LIFECYCLE_FAIL_CLOSED",
    "LIFECYCLE_FAILED",
    "LIFECYCLE_FINALIZED",
    "LIFECYCLE_PREPARED",
    "LIFECYCLE_PROCESSED",
    "LIFECYCLE_TIMEOUT",
    "REQUIRED_RECEIPT_FIELDS",
    "SUCCESS_LIFECYCLES",
    "build_ai4_receipt",
    "explorer_url_for_devnet",
    "format_ai4_receipt_summary",
    "lifecycle_from_status",
    "summarize_decision_report",
    "utc_timestamp",
]
