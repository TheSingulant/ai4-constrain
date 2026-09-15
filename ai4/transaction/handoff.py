"""Unsigned wallet handoff URIs. No signing. No private keys."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote, urlencode

from ai4.transaction.types import NormalizedIntent, format_sol_amount

# Solana Pay transfer request (Phantom and other wallets handle this scheme).
# Spec: https://docs.solanapay.com/spec
SOLANA_PAY_SCHEME = "solana"

# Phantom Universal Links. Provider methods live at /ul/v1/<method> and need
# an encrypted payload plus a dapp encryption key. This scaffold does not
# implement those methods. Browse opens an inner URI in Phantom.
# Docs: https://docs.phantom.com/phantom-deeplinks/deeplinks-ios-and-android
PHANTOM_UL_BROWSE_PREFIX = "https://phantom.app/ul/browse/"
PHANTOM_CUSTOM_SCHEME_BROWSE_PREFIX = "phantom://browse/"
DEFAULT_HANDOFF_REF = "https://www.thesingulant.ai"
DEFAULT_LABEL = "AI4 transfer"
DEFAULT_MESSAGE = "Unsigned SOL transfer. Review and sign in your wallet."


def solana_pay_transfer_uri(
    destination: str,
    amount: Decimal | str,
    *,
    label: str = DEFAULT_LABEL,
    message: str = DEFAULT_MESSAGE,
) -> str:
    """Build a Solana Pay transfer-request URI for native SOL.

    Shape: ``solana:<recipient>?amount=<sol>&label=...&message=...``

    Amount is SOL, not lamports. No ``spl-token`` parameter (native SOL only).
    The wallet composes and signs the transaction. This function does not sign.
    """

    if isinstance(amount, Decimal):
        amount_text = format_sol_amount(amount)
    else:
        amount_text = str(amount).strip()
    query = urlencode({"amount": amount_text, "label": label, "message": message})
    return f"{SOLANA_PAY_SCHEME}:{destination}?{query}"


def phantom_browse_uri(inner_uri: str, *, ref: str = DEFAULT_HANDOFF_REF) -> str:
    """Wrap an inner URI (usually Solana Pay) in Phantom's browse Universal Link.

    Shape: ``https://phantom.app/ul/browse/<url-encoded-inner>?ref=<url-encoded-ref>``

    This is a handoff template, not a signed transaction and not
    ``/ul/v1/signAndSendTransaction``.
    """

    encoded_inner = quote(inner_uri, safe="")
    encoded_ref = quote(ref, safe="")
    return f"{PHANTOM_UL_BROWSE_PREFIX}{encoded_inner}?ref={encoded_ref}"


def phantom_custom_scheme_browse_uri(inner_uri: str) -> str:
    """Optional ``phantom://browse/<encoded>`` form. Universal Link is preferred."""

    return f"{PHANTOM_CUSTOM_SCHEME_BROWSE_PREFIX}{quote(inner_uri, safe='')}"


def handoff_uris_for_intent(intent: NormalizedIntent) -> tuple[str, str]:
    pay = solana_pay_transfer_uri(intent.destination, intent.amount)
    return pay, phantom_browse_uri(pay)
