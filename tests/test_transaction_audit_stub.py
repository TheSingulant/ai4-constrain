"""Audit-log SaaS remains a stub interface."""

from __future__ import annotations

import pytest

from ai4.transaction.audit_stub import AuditLogService


def test_audit_service_cannot_be_instantiated():
    with pytest.raises(TypeError):
        AuditLogService()  # type: ignore[misc]


def test_concrete_subclass_still_has_no_default_writer():
    class Memory(AuditLogService):
        def record(self, event):
            raise NotImplementedError("still a stub in tests")

        def fetch(self, event_id: str):
            raise NotImplementedError("still a stub in tests")

    sink = Memory()
    with pytest.raises(NotImplementedError):
        sink.record({"kind": "prepare"})
