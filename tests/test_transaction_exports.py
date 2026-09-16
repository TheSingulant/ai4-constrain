"""Public package exports stay importable."""

from __future__ import annotations

from ai4.transaction import (
    AI4Receipt,
    AuditLogService,
    Decision,
    Network,
    TransferIntent,
    prepare_transfer,
    require_devnet,
    run_devnet_e2e,
    status,
    validate_transfer_intent,
)


def test_public_exports():
    assert Decision.ALLOW.value == "ALLOW"
    assert Network.MAINNET_BETA.value == "mainnet-beta"
    assert callable(prepare_transfer)
    assert callable(status)
    assert callable(validate_transfer_intent)
    assert callable(require_devnet)
    assert callable(run_devnet_e2e)
    assert TransferIntent.__name__ == "TransferIntent"
    assert AuditLogService.__name__ == "AuditLogService"
    assert AI4Receipt.__name__ == "AI4Receipt"
