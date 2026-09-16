"""Unsigned wallet handoff URIs. No signing. No private keys."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote, urlencode

from ai4.transaction.errors import TransactionValidationError
from ai4.transaction.types import Network, NormalizedIntent, format_sol_amount
from ai4.transaction.validate import parse_network, parse_sol_amount, validate_solana_address

# Solana Pay transfer request (Phantom and other wallets handle this scheme).
# Spec: https://docs.solanapay.com/spec
# Solana Pay has no official cluster field. This scaffold adds non-standard
# ``ai4-network=<cluster>`` for binding integrity / audit. The wallet cluster
# remains a user setting.
SOLANA_PAY_SCHEME = "solana"
AI4_NETWORK_QUERY_KEY = "ai4-network"

# Phantom Universal Links. Provider methods live at /ul/v1/<method> and need
# an encrypted payload plus a dapp encryption key. This scaffold does not
# implement those methods. Browse opens an inner URI in Phantom.
# Docs: https://docs.phantom.com/phantom-deeplinks/deeplinks-ios-and-android
PHANTOM_UL_BROWSE_PREFIX = "https://phantom.app/ul/browse/"
PHANTOM_CUSTOM_SCHEME_BROWSE_PREFIX = "phantom://browse/"
DEFAULT_HANDOFF_REF = "https://www.thesingulant.ai"


def cluster_label(network: Network | str) -> str:
    cluster = parse_network(network).value
    return f"AI4 transfer on Solana {cluster}"


def cluster_message(network: Network | str) -> str:
    cluster = parse_network(network).value
    return (
        f"Unsigned SOL transfer on Solana {cluster}. "
        "Review and sign in your wallet. Wallet cluster is a user setting."
    )


def solana_pay_transfer_uri(
    destination: str,
    amount: Decimal,
    *,
    network: Network | str,
    label: str | None = None,
    message: str | None = None,
) -> str:
    """Build a Solana Pay transfer-request URI for native SOL.

    Shape:
    ``solana:<recipient>?amount=<sol>&label=...&message=...&ai4-network=<cluster>``

    Amount must be a Decimal (re-validated). Destination must already be a
    validated Solana public key and must not contain ``?`` ``&`` ``#`` ``/``.
    No ``spl-token`` parameter (native SOL only). This function does not sign.
    """

    if not isinstance(amount, Decimal):
        raise TransactionValidationError(
            "handoff amount must be a Decimal",
            reasons=("handoff amount must be a Decimal, not a raw string",),
        )
    cluster = parse_network(network)
    safe_destination = validate_solana_address(destination)
    safe_amount = parse_sol_amount(amount)
    amount_text = format_sol_amount(safe_amount)
    resolved_label = label if label is not None else cluster_label(cluster)
    resolved_message = message if message is not None else cluster_message(cluster)
    query = urlencode(
        {
            "amount": amount_text,
            "label": resolved_label,
            "message": resolved_message,
            AI4_NETWORK_QUERY_KEY: cluster.value,
        }
    )
    return f"{SOLANA_PAY_SCHEME}:{safe_destination}?{query}"


def phantom_browse_uri(inner_uri: str, *, ref: str = DEFAULT_HANDOFF_REF) -> str:
    """Wrap an inner URI (usually Solana Pay) in Phantom's **mobile** browse UL.

    Shape: ``https://phantom.app/ul/browse/<url-encoded-inner>?ref=<url-encoded-ref>``

    MOBILE_ONLY: iOS/Android in-app browser. The Chrome/desktop extension does
    not consume this Universal Link. Desktop owners must use the injected
    provider HTML handoff. This is not ``/ul/v1/signAndSendTransaction``.
    """

    encoded_inner = quote(inner_uri, safe="")
    encoded_ref = quote(ref, safe="")
    return f"{PHANTOM_UL_BROWSE_PREFIX}{encoded_inner}?ref={encoded_ref}"


def phantom_custom_scheme_browse_uri(inner_uri: str) -> str:
    """Optional ``phantom://browse/<encoded>`` form. Universal Link is preferred."""

    return f"{PHANTOM_CUSTOM_SCHEME_BROWSE_PREFIX}{quote(inner_uri, safe='')}"


def handoff_uris_for_intent(intent: NormalizedIntent) -> tuple[str, str]:
    pay = solana_pay_transfer_uri(
        intent.destination,
        intent.amount,
        network=intent.network,
    )
    return pay, phantom_browse_uri(pay)
