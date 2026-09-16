"""Fail-closed deterministic validators for v1 SOL transfers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ai4.transaction._base58 import b58decode
from ai4.transaction.errors import TransactionValidationError
from ai4.transaction.types import (
    ALLOWED_ACTIONS,
    ALLOWED_ASSETS,
    ALLOWED_NETWORKS,
    ACTION_TRANSFER,
    Asset,
    DEFAULT_MAX_AMOUNT_SOL,
    DESTINATION_FORBIDDEN_CHARS,
    LAMPORTS_PER_SOL,
    MAX_LAMPORTS,
    NETWORK_ALIASES,
    Network,
    NormalizedIntent,
    TransferConfig,
    TransferIntent,
    format_sol_amount,
)

SOLANA_PUBKEY_BYTES = 32
SOLANA_ADDRESS_MIN_CHARS = 32
SOLANA_ADDRESS_MAX_CHARS = 44


def parse_network(value: Network | str) -> Network:
    if isinstance(value, Network):
        if value not in ALLOWED_NETWORKS:
            raise TransactionValidationError(
                "network is not on the v1 allowlist",
                reasons=(f"unsupported network: {value.value}",),
            )
        return value
    if not isinstance(value, str) or not value.strip():
        raise TransactionValidationError(
            "network is required",
            reasons=("network is required",),
        )
    key = value.strip().lower()
    network = NETWORK_ALIASES.get(key)
    if network is None or network not in ALLOWED_NETWORKS:
        raise TransactionValidationError(
            "network is not on the v1 allowlist",
            reasons=(
                f"unsupported network: {value.strip()!r}; "
                "allowed: mainnet-beta, devnet, localnet",
            ),
        )
    return network


def parse_asset(value: Asset | str) -> Asset:
    if isinstance(value, Asset):
        if value not in ALLOWED_ASSETS:
            raise TransactionValidationError(
                "asset is not native SOL",
                reasons=(f"unsupported asset: {value.value}",),
            )
        return value
    if not isinstance(value, str) or not value.strip():
        raise TransactionValidationError(
            "asset is required",
            reasons=("asset is required",),
        )
    token = value.strip().upper()
    if token != Asset.SOL.value:
        raise TransactionValidationError(
            "asset is not native SOL",
            reasons=(
                f"unsupported asset: {value.strip()!r}; v1 allows native SOL only",
            ),
        )
    return Asset.SOL


def parse_action(value: str | None) -> str:
    if value is None:
        return ACTION_TRANSFER
    if not isinstance(value, str) or not value.strip():
        raise TransactionValidationError(
            "action is required",
            reasons=("action is required",),
        )
    action = value.strip().lower()
    if action not in ALLOWED_ACTIONS:
        raise TransactionValidationError(
            "action is not transfer",
            reasons=(f"unsupported action: {value.strip()!r}; v1 allows transfer only",),
        )
    return ACTION_TRANSFER


def parse_max_amount(value: Decimal | str | int | float) -> Decimal:
    return _parse_positive_sol(value, field_name="max_amount")


def parse_sol_amount(value: Decimal | str | int | float) -> Decimal:
    return _parse_positive_sol(value, field_name="amount")


def _parse_positive_sol(value: Decimal | str | int | float, *, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise TransactionValidationError(
            f"{field_name} must be a positive SOL amount",
            reasons=(f"{field_name} must not be a boolean",),
        )
    try:
        if isinstance(value, Decimal):
            amount = value
        elif isinstance(value, int):
            amount = Decimal(value)
        elif isinstance(value, float):
            amount = Decimal(str(value))
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                raise InvalidOperation("empty")
            amount = Decimal(text)
        else:
            raise InvalidOperation("unsupported type")
    except (InvalidOperation, ValueError) as exc:
        raise TransactionValidationError(
            f"{field_name} must be a positive SOL amount",
            reasons=(f"{field_name} is not a decimal SOL amount",),
        ) from exc
    if not amount.is_finite() or amount <= 0:
        raise TransactionValidationError(
            f"{field_name} must be greater than 0",
            reasons=(f"{field_name} must be greater than 0",),
        )
    lamports = amount * LAMPORTS_PER_SOL
    if lamports != lamports.to_integral_value():
        raise TransactionValidationError(
            f"{field_name} has more than 9 decimal places",
            reasons=(f"{field_name} exceeds SOL lamport precision",),
        )
    as_int = int(lamports)
    if as_int > MAX_LAMPORTS:
        raise TransactionValidationError(
            f"{field_name} exceeds the u64 lamport range",
            reasons=(f"{field_name} exceeds the u64 lamport range",),
        )
    return amount


def validate_solana_address(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransactionValidationError(
            "destination is required",
            reasons=("destination is required",),
        )
    address = value.strip()
    if any(char in address for char in DESTINATION_FORBIDDEN_CHARS):
        raise TransactionValidationError(
            "destination contains URI delimiter characters",
            reasons=("destination contains ?, &, #, or /; refusing query injection",),
        )
    if address.startswith("0x"):
        raise TransactionValidationError(
            "destination is not a Solana address",
            reasons=("destination looks like an EVM address; v1 is Solana only",),
        )
    if not (SOLANA_ADDRESS_MIN_CHARS <= len(address) <= SOLANA_ADDRESS_MAX_CHARS):
        raise TransactionValidationError(
            "destination is not a Solana address",
            reasons=("destination length is outside the Solana base58 public-key range",),
        )
    try:
        decoded = b58decode(address)
    except ValueError as exc:
        raise TransactionValidationError(
            "destination is not a Solana address",
            reasons=("destination is not valid base58",),
        ) from exc
    if len(decoded) != SOLANA_PUBKEY_BYTES:
        raise TransactionValidationError(
            "destination is not a Solana address",
            reasons=("destination does not decode to a 32-byte public key",),
        )
    return address


def validate_solana_signature(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransactionValidationError(
            "signature is required",
            reasons=("signature is required",),
        )
    signature = value.strip()
    try:
        decoded = b58decode(signature)
    except ValueError as exc:
        raise TransactionValidationError(
            "signature is not a Solana transaction signature",
            reasons=("signature is not valid base58",),
        ) from exc
    if len(decoded) != 64:
        raise TransactionValidationError(
            "signature is not a Solana transaction signature",
            reasons=("signature does not decode to 64 bytes",),
        )
    return signature


def reject_custody_flags(intent: TransferIntent) -> None:
    reasons: list[str] = []
    if intent.request_custody:
        reasons.append("custody was requested; v1 is user self-custodial only")
    if intent.server_sign:
        reasons.append("server signing was requested; signing is user off-box only")
    if intent.server_broadcast:
        reasons.append("server broadcast from a server key was requested; refused")
    if reasons:
        raise TransactionValidationError(
            "custody or server-sign flags are not allowed",
            reasons=tuple(reasons),
        )


def validate_transfer_intent(
    intent: TransferIntent,
    *,
    config: TransferConfig | None = None,
) -> NormalizedIntent:
    """Validate a transfer. Raises TransactionValidationError (fail closed)."""

    cfg = config or TransferConfig()
    reject_custody_flags(intent)
    action = parse_action(intent.action)
    network = parse_network(intent.network)
    asset = parse_asset(intent.asset)
    amount = parse_sol_amount(intent.amount)
    max_amount = parse_max_amount(cfg.max_amount_sol)
    if amount > max_amount:
        raise TransactionValidationError(
            "amount exceeds the configured cap",
            reasons=(
                f"amount {format_sol_amount(amount)} SOL exceeds cap "
                f"{format_sol_amount(max_amount)} SOL",
            ),
        )
    destination = validate_solana_address(intent.destination)
    lamports = int(amount * LAMPORTS_PER_SOL)
    return NormalizedIntent(
        network=network,
        asset=asset,
        amount=amount,
        destination=destination,
        lamports=lamports,
        action=action,
    )


__all__ = [
    "DEFAULT_MAX_AMOUNT_SOL",
    "parse_action",
    "parse_asset",
    "parse_max_amount",
    "parse_network",
    "parse_sol_amount",
    "reject_custody_flags",
    "validate_solana_address",
    "validate_solana_signature",
    "validate_transfer_intent",
]
