"""AI4 Transaction Control scaffold (v1 Solana native SOL transfer).

This is a downloadable library surface, not a hosted Telegram bot and not a
released PyPI version claim for transaction features. Signing stays off-box.
"""

from __future__ import annotations

from ai4.transaction.audit_stub import AuditLogService, AuditLogSink
from ai4.transaction.binding import verify_solana_pay_binding
from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.firewall import build_firewall_proposal, map_constrain_decision, run_firewall
from ai4.transaction.handoff import phantom_browse_uri, solana_pay_transfer_uri
from ai4.transaction.prepare import prepare_transfer
from ai4.transaction.status import status
from ai4.transaction.types import (
    DEFAULT_MAX_AMOUNT_SOL,
    ApprovedBinding,
    Asset,
    Decision,
    FirewallResult,
    NormalizedIntent,
    PrepareResult,
    Receipt,
    TransferConfig,
    TransferIntent,
    UnsignedPayload,
    Network,
)
from ai4.transaction.validate import validate_solana_address, validate_transfer_intent

__all__ = [
    "DEFAULT_MAX_AMOUNT_SOL",
    "ApprovedBinding",
    "Asset",
    "AuditLogService",
    "AuditLogSink",
    "Decision",
    "FirewallResult",
    "Network",
    "NormalizedIntent",
    "PrepareResult",
    "Receipt",
    "TransactionControlError",
    "TransactionValidationError",
    "TransferConfig",
    "TransferIntent",
    "UnsignedPayload",
    "build_firewall_proposal",
    "map_constrain_decision",
    "phantom_browse_uri",
    "prepare_transfer",
    "run_firewall",
    "solana_pay_transfer_uri",
    "status",
    "validate_solana_address",
    "validate_transfer_intent",
    "verify_solana_pay_binding",
]
