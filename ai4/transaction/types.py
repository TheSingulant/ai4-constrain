"""Public types for the v1 Solana native-SOL transfer scaffold."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from ai4.constrain.report import DecisionReport


class Network(str, Enum):
    """Solana clusters allowed in v1."""

    MAINNET_BETA = "mainnet-beta"
    DEVNET = "devnet"
    LOCALNET = "localnet"


class Asset(str, Enum):
    """v1 asset allowlist. Native SOL only."""

    SOL = "SOL"


class Decision(str, Enum):
    """Transaction-firewall product decision."""

    ALLOW = "ALLOW"
    DENY = "DENY"


ALLOWED_NETWORKS = frozenset(Network)
ALLOWED_ASSETS = frozenset(Asset)
ACTION_TRANSFER = "transfer"
ALLOWED_ACTIONS = frozenset({ACTION_TRANSFER})
DEFAULT_MAX_AMOUNT_SOL = Decimal("1")
LAMPORTS_PER_SOL = Decimal("1000000000")
MAX_LAMPORTS = 2**64 - 1
DESTINATION_FORBIDDEN_CHARS = frozenset("?&#/")

NETWORK_ALIASES = {
    "mainnet-beta": Network.MAINNET_BETA,
    "devnet": Network.DEVNET,
    "localnet": Network.LOCALNET,
    "local": Network.LOCALNET,
    "localhost": Network.LOCALNET,
}

EXPLORER_TX = {
    Network.MAINNET_BETA: "https://explorer.solana.com/tx/{signature}",
    Network.DEVNET: "https://explorer.solana.com/tx/{signature}?cluster=devnet",
    Network.LOCALNET: None,
}


@dataclass(frozen=True)
class TransferIntent:
    """Caller-supplied transfer request. Flags default to self-custodial."""

    network: Network | str
    asset: Asset | str
    amount: Decimal | str | int | float
    destination: str
    action: str = ACTION_TRANSFER
    request_custody: bool = False
    server_sign: bool = False
    server_broadcast: bool = False


@dataclass(frozen=True)
class TransferConfig:
    """Deterministic caps and optional RPC. No secrets belong here."""

    max_amount_sol: Decimal | str | int | float = DEFAULT_MAX_AMOUNT_SOL
    rpc_url: str | None = None


@dataclass(frozen=True)
class NormalizedIntent:
    network: Network
    asset: Asset
    amount: Decimal
    destination: str
    lamports: int
    action: str = ACTION_TRANSFER


@dataclass(frozen=True)
class UnsignedPayload:
    """Unsigned transfer stub. Not a signed transaction. No private keys."""

    kind: str
    network: str
    asset: str
    amount_sol: str
    lamports: int
    destination: str
    note: str = (
        "Unsigned stub only. The user signs in a self-custodial wallet. "
        "AI4 does not hold keys or assets."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "network": self.network,
            "asset": self.asset,
            "amount_sol": self.amount_sol,
            "lamports": self.lamports,
            "destination": self.destination,
            "note": self.note,
        }


@dataclass(frozen=True)
class ApprovedBinding:
    """Structured params bound into the handoff. Not a wallet cluster lock."""

    network: str
    asset: str
    action: str
    amount_sol: str
    lamports: int
    destination: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "asset": self.asset,
            "action": self.action,
            "amount_sol": self.amount_sol,
            "lamports": self.lamports,
            "destination": self.destination,
        }

    def sha256(self) -> str:
        blob = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["sha256"] = self.sha256()
        return payload


def approved_binding_from_intent(intent: NormalizedIntent) -> ApprovedBinding:
    return ApprovedBinding(
        network=intent.network.value,
        asset=intent.asset.value,
        action=intent.action,
        amount_sol=format_sol_amount(intent.amount),
        lamports=intent.lamports,
        destination=intent.destination,
    )


@dataclass(frozen=True)
class PrepareResult:
    decision: Decision
    reasons: tuple[str, ...]
    summary: str
    intent: NormalizedIntent | None = None
    report: DecisionReport | None = None
    unsigned_payload: UnsignedPayload | None = None
    handoff_uri: str | None = None
    phantom_browse_uri: str | None = None
    fee_status: str = "unverified_no_rpc"
    fee_note: str = ""
    approved_binding: ApprovedBinding | None = None

    def __post_init__(self) -> None:
        if self.decision is Decision.DENY:
            if (
                self.handoff_uri is not None
                or self.phantom_browse_uri is not None
                or self.unsigned_payload is not None
            ):
                raise ValueError("DENY PrepareResult must not carry a handoff or unsigned payload")
        elif self.decision is Decision.ALLOW:
            if not self.handoff_uri or not self.phantom_browse_uri or self.unsigned_payload is None:
                raise ValueError("ALLOW PrepareResult must carry handoff URIs and an unsigned stub")
            if self.approved_binding is None:
                raise ValueError("ALLOW PrepareResult must carry approved_binding")

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "summary": self.summary,
            "intent": None
            if self.intent is None
            else {
                "network": self.intent.network.value,
                "asset": self.intent.asset.value,
                "action": self.intent.action,
                "amount": format_sol_amount(self.intent.amount),
                "destination": self.intent.destination,
                "lamports": self.intent.lamports,
            },
            "approved_binding": None if self.approved_binding is None else self.approved_binding.to_dict(),
            "decision_report": None if self.report is None else self.report.to_dict(),
            "unsigned_payload": None
            if self.unsigned_payload is None
            else self.unsigned_payload.to_dict(),
            "handoff_uri": self.handoff_uri,
            "phantom_browse_uri": self.phantom_browse_uri,
            "fee_status": self.fee_status,
            "fee_note": self.fee_note,
        }


@dataclass(frozen=True)
class Receipt:
    """Lifecycle observation for a submitted signature. Not a mint receipt."""

    signature: str
    fail_closed: bool
    reasons: tuple[str, ...]
    confirmation_status: str | None = None
    slot: int | None = None
    err: Any = None
    explorer_url: str | None = None
    network: str | None = None
    rpc_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "fail_closed": self.fail_closed,
            "reasons": list(self.reasons),
            "confirmation_status": self.confirmation_status,
            "slot": self.slot,
            "err": self.err,
            "explorer_url": self.explorer_url,
            "network": self.network,
            "rpc_used": self.rpc_used,
        }


@dataclass(frozen=True)
class FirewallResult:
    decision: Decision
    reasons: tuple[str, ...]
    report: DecisionReport | None = None
    proposal_text: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


def format_sol_amount(amount: Decimal) -> str:
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
