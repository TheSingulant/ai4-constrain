"""Lifecycle status for a Solana signature. Fail closed without a clear RPC result."""

from __future__ import annotations

from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.rpc import RpcPost, json_rpc_post, resolve_rpc_url
from ai4.transaction.types import EXPLORER_TX, Network, Receipt
from ai4.transaction.validate import parse_network, validate_solana_signature

KNOWN_CONFIRMATION = {"processed", "confirmed", "finalized"}


def _explorer_url(signature: str, network: Network | None) -> str | None:
    if network is None:
        return None
    template = EXPLORER_TX.get(network)
    if not template:
        return None
    return template.format(signature=signature)


def status(
    signature: str,
    *,
    rpc_url: str | None = None,
    network: str | Network | None = None,
    rpc_post: RpcPost | None = None,
    timeout_s: float = 10.0,
) -> Receipt:
    """Poll ``getSignatureStatuses`` only when an RPC URL is provided.

    The URL comes from the ``rpc_url`` argument or ``AI4_SOLANA_RPC_URL``.
    There is no hardcoded RPC. Unreachable or ambiguous responses fail closed.
    """

    try:
        sig = validate_solana_signature(signature)
    except TransactionValidationError as exc:
        return Receipt(
            signature=str(signature or ""),
            fail_closed=True,
            reasons=exc.reasons,
            rpc_used=False,
        )

    parsed_network: Network | None = None
    if network is not None and str(network).strip():
        try:
            parsed_network = parse_network(network)
        except TransactionValidationError as exc:
            return Receipt(
                signature=sig,
                fail_closed=True,
                reasons=exc.reasons,
                rpc_used=False,
            )

    resolved = resolve_rpc_url(rpc_url)
    if not resolved:
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=(
                "no Solana RPC URL; pass --rpc-url or set AI4_SOLANA_RPC_URL "
                "(documented empty optional in .env.example)",
            ),
            explorer_url=_explorer_url(sig, parsed_network),
            network=None if parsed_network is None else parsed_network.value,
            rpc_used=False,
        )

    poster = rpc_post or json_rpc_post
    try:
        body = poster(
            resolved,
            "getSignatureStatuses",
            [[sig], {"searchTransactionHistory": True}],
            timeout_s,
        )
    except TransactionControlError as exc:
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=exc.reasons,
            explorer_url=_explorer_url(sig, parsed_network),
            network=None if parsed_network is None else parsed_network.value,
            rpc_used=True,
        )
    except Exception as exc:
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=(f"RPC call failed closed: {exc}",),
            explorer_url=_explorer_url(sig, parsed_network),
            network=None if parsed_network is None else parsed_network.value,
            rpc_used=True,
        )

    result = body.get("result")
    if not isinstance(result, dict):
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("getSignatureStatuses result is not an object; fail closed",),
            rpc_used=True,
            network=None if parsed_network is None else parsed_network.value,
            explorer_url=_explorer_url(sig, parsed_network),
        )
    value = result.get("value")
    if not isinstance(value, list) or not value:
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("getSignatureStatuses value is missing; fail closed",),
            rpc_used=True,
            network=None if parsed_network is None else parsed_network.value,
            explorer_url=_explorer_url(sig, parsed_network),
        )
    entry = value[0]
    if entry is None:
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("signature not found or status is null; fail closed",),
            rpc_used=True,
            network=None if parsed_network is None else parsed_network.value,
            explorer_url=_explorer_url(sig, parsed_network),
        )
    if not isinstance(entry, dict):
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("signature status entry is not an object; fail closed",),
            rpc_used=True,
            network=None if parsed_network is None else parsed_network.value,
            explorer_url=_explorer_url(sig, parsed_network),
        )

    confirmation = entry.get("confirmationStatus")
    if not isinstance(confirmation, str) or confirmation not in KNOWN_CONFIRMATION:
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("confirmationStatus is missing or unknown; fail closed",),
            err=entry.get("err"),
            slot=entry.get("slot") if isinstance(entry.get("slot"), int) else None,
            rpc_used=True,
            network=None if parsed_network is None else parsed_network.value,
            explorer_url=_explorer_url(sig, parsed_network),
        )

    slot = entry.get("slot")
    if slot is not None and not isinstance(slot, int):
        return Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("slot is not an integer; fail closed",),
            confirmation_status=confirmation,
            rpc_used=True,
            network=None if parsed_network is None else parsed_network.value,
            explorer_url=_explorer_url(sig, parsed_network),
        )

    return Receipt(
        signature=sig,
        fail_closed=False,
        reasons=(),
        confirmation_status=confirmation,
        slot=slot,
        err=entry.get("err"),
        explorer_url=_explorer_url(sig, parsed_network),
        network=None if parsed_network is None else parsed_network.value,
        rpc_used=True,
    )
