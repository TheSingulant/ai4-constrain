"""Approved-intent to Solana Pay URI binding. Fail closed on mismatch.

DecisionReport is free-text only. Structured binding lives here: the same
NormalizedIntent that was proposed must parse back out of the handoff URI
before ALLOW may return a URI.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from ai4.transaction.errors import TransactionControlError
from ai4.transaction.handoff import AI4_NETWORK_QUERY_KEY, PHANTOM_UL_BROWSE_PREFIX
from ai4.transaction.types import (
    ACTION_TRANSFER,
    LAMPORTS_PER_SOL,
    NormalizedIntent,
    format_sol_amount,
)
from ai4.transaction.validate import parse_sol_amount, validate_solana_address

ALLOWED_QUERY_KEYS = frozenset({"amount", "label", "message", AI4_NETWORK_QUERY_KEY})


def parse_solana_pay_uri(uri: str) -> dict[str, str]:
    if not isinstance(uri, str) or not uri.strip():
        raise TransactionControlError(
            "handoff URI is missing",
            reasons=("handoff URI is missing",),
        )
    parsed = urlparse(uri.strip())
    if parsed.scheme != "solana":
        raise TransactionControlError(
            "handoff URI scheme is not solana",
            reasons=(f"handoff URI scheme is {parsed.scheme!r}, expected 'solana'",),
        )
    if parsed.netloc:
        raise TransactionControlError(
            "handoff URI must not use solana:// netloc form",
            reasons=("handoff URI uses an unexpected netloc",),
        )
    if parsed.fragment:
        raise TransactionControlError(
            "handoff URI must not contain a fragment",
            reasons=("handoff URI contains a fragment",),
        )
    recipient = parsed.path
    if not recipient:
        raise TransactionControlError(
            "handoff URI is missing a recipient",
            reasons=("handoff URI is missing a recipient",),
        )
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise TransactionControlError(
            "handoff URI query is malformed",
            reasons=("handoff URI query is malformed",),
        ) from exc
    for key, values in query.items():
        if len(values) != 1:
            raise TransactionControlError(
                "handoff URI has duplicate query keys",
                reasons=(f"handoff URI query key {key!r} is repeated",),
            )
    keys = set(query)
    if "spl-token" in keys:
        raise TransactionControlError(
            "handoff URI must not include spl-token",
            reasons=("handoff URI includes spl-token; v1 is native SOL only",),
        )
    extra = sorted(keys - ALLOWED_QUERY_KEYS)
    if extra:
        raise TransactionControlError(
            "handoff URI has unexpected query keys",
            reasons=(f"handoff URI unexpected query keys: {extra}",),
        )
    missing = sorted({"amount", AI4_NETWORK_QUERY_KEY} - keys)
    if missing:
        raise TransactionControlError(
            "handoff URI is missing required binding fields",
            reasons=(f"handoff URI missing query keys: {missing}",),
        )
    return {
        "recipient": recipient,
        "amount": query["amount"][0],
        "network": query[AI4_NETWORK_QUERY_KEY][0],
        "label": query.get("label", [""])[0],
        "message": query.get("message", [""])[0],
    }


def verify_solana_pay_binding(uri: str, intent: NormalizedIntent) -> None:
    """Require the URI to parse back to the approved destination, amount, and cluster."""

    parsed = parse_solana_pay_uri(uri)
    try:
        recipient = validate_solana_address(parsed["recipient"])
    except Exception as exc:
        raise TransactionControlError(
            "handoff recipient failed address validation",
            reasons=("handoff recipient failed address validation",),
        ) from exc
    if recipient != intent.destination:
        raise TransactionControlError(
            "handoff recipient does not match approved destination",
            reasons=("handoff recipient does not match approved destination",),
        )
    try:
        amount = parse_sol_amount(parsed["amount"])
    except Exception as exc:
        raise TransactionControlError(
            "handoff amount failed validation",
            reasons=("handoff amount failed validation",),
        ) from exc
    lamports = int(amount * LAMPORTS_PER_SOL)
    if lamports != intent.lamports or amount != intent.amount:
        raise TransactionControlError(
            "handoff amount does not match approved amount",
            reasons=("handoff amount does not match approved amount",),
        )
    if parsed["network"] != intent.network.value:
        raise TransactionControlError(
            "handoff ai4-network does not match approved cluster",
            reasons=(
                "handoff ai4-network does not match approved cluster; "
                f"uri={parsed['network']!r} approved={intent.network.value!r}",
            ),
        )
    cluster = intent.network.value
    if cluster not in parsed["label"] or cluster not in parsed["message"]:
        raise TransactionControlError(
            "handoff label/message must include the approved cluster",
            reasons=("handoff label/message missing approved cluster",),
        )
    if intent.action != ACTION_TRANSFER:
        raise TransactionControlError(
            "approved action is not transfer",
            reasons=("approved action is not transfer",),
        )
    if format_sol_amount(amount) != format_sol_amount(intent.amount):
        raise TransactionControlError(
            "handoff amount text does not match approved amount",
            reasons=("handoff amount text does not match approved amount",),
        )


def verify_phantom_browse_binding(browse_uri: str, pay_uri: str) -> None:
    if not isinstance(browse_uri, str) or not browse_uri.startswith(PHANTOM_UL_BROWSE_PREFIX):
        raise TransactionControlError(
            "Phantom browse URI is not the expected Universal Link",
            reasons=("Phantom browse URI is not the expected Universal Link",),
        )
    rest = browse_uri[len(PHANTOM_UL_BROWSE_PREFIX) :]
    encoded, sep, _query = rest.partition("?")
    if not sep:
        raise TransactionControlError(
            "Phantom browse URI is missing ref query",
            reasons=("Phantom browse URI is missing ref query",),
        )
    if unquote(encoded) != pay_uri:
        raise TransactionControlError(
            "Phantom browse URI does not wrap the approved Solana Pay URI",
            reasons=("Phantom browse URI does not wrap the approved Solana Pay URI",),
        )


def verify_approved_handoff(pay_uri: str, browse_uri: str, intent: NormalizedIntent) -> None:
    verify_solana_pay_binding(pay_uri, intent)
    verify_phantom_browse_binding(browse_uri, pay_uri)
