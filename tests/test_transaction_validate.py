"""Deterministic validators fail closed."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai4.transaction.errors import TransactionValidationError
from ai4.transaction.types import TransferConfig, TransferIntent
from ai4.transaction.validate import (
    parse_asset,
    parse_network,
    validate_solana_address,
    validate_solana_signature,
    validate_transfer_intent,
)
from tests.transaction_util import solana_address, solana_signature

DEST = solana_address()


def _intent(**overrides) -> TransferIntent:
    payload = {
        "network": "mainnet-beta",
        "asset": "SOL",
        "amount": "0.1",
        "destination": DEST,
    }
    payload.update(overrides)
    return TransferIntent(**payload)


def test_happy_path_normalizes_intent():
    normalized = validate_transfer_intent(_intent())
    assert normalized.network.value == "mainnet-beta"
    assert normalized.asset.value == "SOL"
    assert normalized.amount == Decimal("0.1")
    assert normalized.lamports == 100_000_000
    assert normalized.destination == DEST


def test_local_alias_maps_to_localnet():
    normalized = validate_transfer_intent(_intent(network="local"))
    assert normalized.network.value == "localnet"


def test_deny_wrong_network():
    with pytest.raises(TransactionValidationError) as exc:
        validate_transfer_intent(_intent(network="polygon"))
    assert "unsupported network" in exc.value.reasons[0]


def test_deny_evm_mainnet_alias():
    with pytest.raises(TransactionValidationError):
        parse_network("ethereum")


def test_deny_wrong_asset():
    with pytest.raises(TransactionValidationError) as exc:
        validate_transfer_intent(_intent(asset="USDC"))
    assert "native SOL" in exc.value.reasons[0]


def test_deny_wrapped_or_spl_shaped_asset():
    with pytest.raises(TransactionValidationError):
        parse_asset("wSOL")
    with pytest.raises(TransactionValidationError):
        parse_asset("SOLANA")


def test_deny_over_cap():
    with pytest.raises(TransactionValidationError) as exc:
        validate_transfer_intent(
            _intent(amount="2"),
            config=TransferConfig(max_amount_sol="1"),
        )
    assert "exceeds cap" in exc.value.reasons[0]


def test_deny_zero_and_negative_amount():
    with pytest.raises(TransactionValidationError):
        validate_transfer_intent(_intent(amount="0"))
    with pytest.raises(TransactionValidationError):
        validate_transfer_intent(_intent(amount="-0.1"))


def test_deny_boolean_amount():
    with pytest.raises(TransactionValidationError):
        validate_transfer_intent(_intent(amount=True))


def test_deny_too_many_decimals():
    with pytest.raises(TransactionValidationError):
        validate_transfer_intent(_intent(amount="0.1234567891"))


def test_deny_bad_address_charset():
    with pytest.raises(TransactionValidationError):
        validate_solana_address("0x" + "ab" * 20)


def test_deny_short_address():
    with pytest.raises(TransactionValidationError):
        validate_solana_address("ShortAddr")


def test_deny_invalid_base58_address():
    with pytest.raises(TransactionValidationError):
        validate_solana_address("0" * 32)


def test_system_program_address_is_valid_shape():
    assert validate_solana_address("1" * 32)


def test_deny_custody_requested():
    with pytest.raises(TransactionValidationError) as exc:
        validate_transfer_intent(_intent(request_custody=True))
    assert any("custody" in item for item in exc.value.reasons)


def test_deny_server_sign():
    with pytest.raises(TransactionValidationError) as exc:
        validate_transfer_intent(_intent(server_sign=True))
    assert any("server signing" in item for item in exc.value.reasons)


def test_deny_server_broadcast():
    with pytest.raises(TransactionValidationError) as exc:
        validate_transfer_intent(_intent(server_broadcast=True))
    assert any("server broadcast" in item for item in exc.value.reasons)


def test_signature_must_be_64_bytes():
    assert validate_solana_signature(solana_signature())
    with pytest.raises(TransactionValidationError):
        validate_solana_signature(DEST)
