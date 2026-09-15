"""Transaction Firewall: deterministic validation, then ai4.constrain."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai4.constrain.api import evaluate
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport
from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.types import (
    Decision,
    FirewallResult,
    NormalizedIntent,
    TransferConfig,
    TransferIntent,
    format_sol_amount,
)
from ai4.transaction.validate import validate_transfer_intent

EvaluateFn = Callable[[str], DecisionReport]

# Default path is evaluate-only: frozen shard scoring, no model calls, no live
# LLM spend. Live ``run()`` with a paid evaluator needs owner approval and is
# not wired into this scaffold CLI.
DEFAULT_ENGINE = "evaluate"


def build_firewall_proposal(intent: NormalizedIntent) -> str:
    """Structured, checkable proposal text for ``ai4.constrain.evaluate``."""

    amount = format_sol_amount(intent.amount)
    return (
        "Here is a brief, checkable outline of a proposed transfer and its limits.\n"
        "Action: transfer native SOL only.\n"
        f"Network: Solana {intent.network.value}.\n"
        f"Asset: {intent.asset.value}.\n"
        f"Amount: {amount} SOL ({intent.lamports} lamports).\n"
        f"Destination: {intent.destination} (Solana address shape already checked).\n"
        "The software does not hold keys or assets. The user signs in their own wallet.\n"
        "No custody, no server signing, no server broadcast from a server key.\n"
        "No swap, no buy, no sell, no fiat, no discretionary routing.\n"
        "I will mark anything I cannot verify.\n"
    )


def map_constrain_decision(report: DecisionReport | None) -> tuple[Decision, tuple[str, ...]]:
    """Map constrain outcomes onto ALLOW or DENY. Fail closed."""

    if report is None:
        return Decision.DENY, ("constrain produced no DecisionReport",)
    if report.decision == "accept":
        return Decision.ALLOW, ("constrain decision is accept",)
    if report.decision == "refuse":
        return Decision.DENY, ("constrain decision is refuse; fail closed",)
    if report.decision == "revise":
        return Decision.DENY, ("constrain decision is revise; fail closed",)
    if report.decision is None:
        return Decision.DENY, (
            "constrain decision is null (timeout or execution failure); fail closed",
        )
    return Decision.DENY, (f"unmapped constrain decision {report.decision!r}; fail closed",)


def _default_evaluate(text: str) -> DecisionReport:
    return evaluate(text, prompt="Review this proposed SOL transfer against frozen limits.")


def run_firewall(
    intent: TransferIntent | NormalizedIntent,
    *,
    config: TransferConfig | None = None,
    evaluate_fn: EvaluateFn | None = None,
    engine: str = DEFAULT_ENGINE,
) -> FirewallResult:
    """Validate, then score the structured proposal with ai4.constrain.

    ``engine`` is ``evaluate`` (default, no model calls) or ignored when
    ``evaluate_fn`` is supplied (unit-test / dry fixture path).

    Live LLM evaluator spend is not enabled here. Owner approval is required
    before any host wires ``run()`` to a paid provider.
    """

    del engine  # reserved; default product path is evaluate-only
    try:
        if isinstance(intent, NormalizedIntent):
            normalized = intent
        else:
            normalized = validate_transfer_intent(intent, config=config)
    except TransactionValidationError as exc:
        return FirewallResult(
            decision=Decision.DENY,
            reasons=exc.reasons,
            report=None,
            proposal_text="",
        )

    proposal = build_firewall_proposal(normalized)
    scorer = evaluate_fn if evaluate_fn is not None else _default_evaluate
    try:
        report = scorer(proposal)
    except ConstraintExecutionError as exc:
        return FirewallResult(
            decision=Decision.DENY,
            reasons=(f"constrain failed closed: {exc}",),
            report=None,
            proposal_text=proposal,
        )
    except Exception as exc:
        return FirewallResult(
            decision=Decision.DENY,
            reasons=(f"constrain could not run; fail closed: {exc}",),
            report=None,
            proposal_text=proposal,
        )

    if not isinstance(report, DecisionReport):
        return FirewallResult(
            decision=Decision.DENY,
            reasons=("constrain result was not a DecisionReport; fail closed",),
            report=None,
            proposal_text=proposal,
        )

    decision, reasons = map_constrain_decision(report)
    extra: dict[str, Any] = {
        "constrain_decision": report.decision,
        "constrain_mode": report.mode,
        "network": normalized.network.value,
        "asset": normalized.asset.value,
    }
    return FirewallResult(
        decision=decision,
        reasons=reasons,
        report=report,
        proposal_text=proposal,
        extra=extra,
    )


def require_allow(result: FirewallResult) -> None:
    if result.decision is not Decision.ALLOW:
        raise TransactionControlError(
            "transaction firewall denied the transfer",
            reasons=result.reasons,
        )
