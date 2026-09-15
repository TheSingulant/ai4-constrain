"""Phantom / Solana Pay handoff URIs. No signing."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import unquote, urlparse

from ai4.transaction.handoff import (
    PHANTOM_UL_BROWSE_PREFIX,
    phantom_browse_uri,
    solana_pay_transfer_uri,
)
from tests.transaction_util import solana_address

DEST = solana_address(23)


def test_solana_pay_native_sol_uri():
    uri = solana_pay_transfer_uri(DEST, Decimal("0.10"))
    assert uri.startswith(f"solana:{DEST}?")
    assert "amount=0.1" in uri
    assert "spl-token" not in uri
    parsed = urlparse(uri.replace("solana:", "solana://", 1))
    assert parsed.path.endswith(DEST) or DEST in uri


def test_phantom_browse_wraps_encoded_inner():
    inner = solana_pay_transfer_uri(DEST, Decimal("1"))
    browse = phantom_browse_uri(inner, ref="https://www.thesingulant.ai")
    assert browse.startswith(PHANTOM_UL_BROWSE_PREFIX)
    encoded_part = browse[len(PHANTOM_UL_BROWSE_PREFIX) :].split("?", 1)[0]
    assert unquote(encoded_part) == inner
    assert "ref=" in browse
    # Provider signAndSendTransaction is intentionally not used.
    assert "/ul/v1/signAndSendTransaction" not in browse
