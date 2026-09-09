"""Narrow resolver boundary. Lookup only; never verification or trust."""

from __future__ import annotations

from typing import Mapping, Protocol

from ai4.identity.errors import IdentityError
from ai4.identity.resolve.types import (
    MAX_RECORD_STRING_LEN,
    MAX_RECORDS_PAYLOAD_BYTES,
    RESOLVER_IDS,
)


class Resolver(Protocol):
    """Return the raw key/value record set for a normalized .ai4 name.

    Must not verify signatures, must not fetch manifests, must not
    construct TrustContext, and must not talk to ai4.constrain.
    """

    def resolve(self, name: str) -> Mapping[str, str]:
        """Untrusted Unstoppable-style records. Not a DiscoveryRecord."""


class MemoryResolver:
    """In-memory resolver for tests. No network. Not a production name system."""

    resolver_id = "memory"

    def __init__(
        self,
        table: Mapping[str, Mapping[str, str]],
        *,
        captured_at: str,
        freshness_kind: str = "fixture",
    ) -> None:
        if self.resolver_id not in RESOLVER_IDS:
            raise IdentityError("unknown resolver_id")
        self._table = {str(key): dict(value) for key, value in table.items()}
        self.captured_at = captured_at
        self.freshness_kind = freshness_kind
        for records in self._table.values():
            validate_raw_records(records)

    def resolve(self, name: str) -> Mapping[str, str]:
        if name not in self._table:
            raise IdentityError(f"unresolved .ai4 name: {name!r}")
        return dict(self._table[name])


def validate_raw_records(records: Mapping[str, str]) -> None:
    """Fail closed on oversized or non-string resolver values. Extra keys are ignored later."""
    if not isinstance(records, dict):
        raise IdentityError("resolver records must be a JSON object")
    total = 0
    for key, value in records.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise IdentityError("resolver record keys and values must be strings")
        if len(key) > MAX_RECORD_STRING_LEN or len(value) > MAX_RECORD_STRING_LEN:
            raise IdentityError("resolver record string exceeds size cap")
        total += len(key) + len(value)
        if total > MAX_RECORDS_PAYLOAD_BYTES:
            raise IdentityError("resolver records exceed payload size cap")
