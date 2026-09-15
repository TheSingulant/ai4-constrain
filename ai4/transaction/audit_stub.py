"""Stub interface only for a future agent audit-log SaaS.

This module is not an implementation. It does not write logs, open sockets,
or persist receipts. A later host may implement the protocol without changing
the prepare/firewall call shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Protocol


class AuditLogSink(Protocol):
    """Structural interface for a future audit-log writer."""

    def record(self, event: Mapping[str, Any]) -> None:
        """Record one audit event. Implementations do not exist in this scaffold."""


class AuditLogService(ABC):
    """Abstract service boundary for a future hosted audit-log SaaS.

    Do not instantiate this class. Do not add a default filesystem or HTTP
    implementation in this repository until that product is scoped separately.
    """

    @abstractmethod
    def record(self, event: Mapping[str, Any]) -> None:
        raise NotImplementedError("audit-log SaaS is not implemented in this scaffold")

    @abstractmethod
    def fetch(self, event_id: str) -> Mapping[str, Any]:
        raise NotImplementedError("audit-log SaaS is not implemented in this scaffold")
