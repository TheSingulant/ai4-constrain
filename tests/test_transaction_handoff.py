"""Phantom / Solana Pay handoff URIs. No signing."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import unquote

import pytest

from ai4.transaction.errors import TransactionValidationError
from ai4.transaction.handoff import (
    AI4_NETWORK_QUERY_KEY,
    PHANTOM_UL_BROWSE_PREFIX,
    phantom_browse_uri,
    solana_pay_transfer_uri,
)
from ai4.transaction.desktop_handoff import PHANTOM_BROWSE_CHANNEL
from tests.transaction_util import solana_address

DEST = solana_address(23)


def test_solana_pay_native_sol_uri_includes_cluster_marker():
    uri = solana_pay_transfer_uri(DEST, Decimal("0.10"), network="mainnet-beta")
    assert uri.startswith(f"solana:{DEST}?")
    assert "amount=0.1" in uri
    assert f"{AI4_NETWORK_QUERY_KEY}=mainnet-beta" in uri
    assert "Solana+mainnet-beta" in uri or "Solana mainnet-beta" in uri.replace("+", " ")
    assert "spl-token" not in uri


def test_solana_pay_rejects_amount_string_injection():
    with pytest.raises(TransactionValidationError):
        solana_pay_transfer_uri(DEST, "0.1&amount=9", network="devnet")  # type: ignore[arg-type]


def test_solana_pay_rejects_destination_query_chars():
    with pytest.raises(TransactionValidationError):
        solana_pay_transfer_uri(DEST + "?amount=9", Decimal("0.1"), network="devnet")


def test_phantom_browse_wraps_encoded_inner():
    inner = solana_pay_transfer_uri(DEST, Decimal("1"), network="devnet")
    browse = phantom_browse_uri(inner, ref="https://www.thesingulant.ai")
    assert browse.startswith(PHANTOM_UL_BROWSE_PREFIX)
    encoded_part = browse[len(PHANTOM_UL_BROWSE_PREFIX) :].split("?", 1)[0]
    assert unquote(encoded_part) == inner
    assert "ref=" in browse
    assert "/ul/v1/signAndSendTransaction" not in browse
    assert PHANTOM_BROWSE_CHANNEL == "mobile_only"
