"""Discovery / resolution adapter. Not the identity kernel.

A signed AI4 identity record binds claims and provenance to an agent identity;
it does not prove the agent is aligned, safe, or correctly governed.

Identity is not trust. Resolution is not verification. Naming is not policy
authority.

This subpackage is not exported from ``ai4.identity.__init__``. Kernel
modules must not import it. ``ai4.constrain`` must not import it.
"""

from __future__ import annotations

from ai4.identity.resolve.file_resolver import FileResolver
from ai4.identity.resolve.fetch import LocalFileFetcher, require_digest_agreement
from ai4.identity.resolve.pipeline import (
    bind_discovery_to_attestation,
    discover_and_verify,
    fetch_attestation_bytes,
    normalize_ai4_name,
    resolve_name,
    verify_resolved,
)
from ai4.identity.resolve.resolver import MemoryResolver, Resolver
from ai4.identity.resolve.types import (
    DISCOVERY_SCHEMA_ID,
    DiscoveryRecord,
    Freshness,
    ResolveResult,
    Status,
)

__all__ = [
    "DISCOVERY_SCHEMA_ID",
    "DiscoveryRecord",
    "FileResolver",
    "Freshness",
    "LocalFileFetcher",
    "MemoryResolver",
    "ResolveResult",
    "Resolver",
    "Status",
    "bind_discovery_to_attestation",
    "discover_and_verify",
    "fetch_attestation_bytes",
    "normalize_ai4_name",
    "require_digest_agreement",
    "resolve_name",
    "verify_resolved",
]
