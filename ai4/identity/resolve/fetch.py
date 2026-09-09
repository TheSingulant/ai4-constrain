"""Byte fetch for discovery. Not used by kernel verify_*.

Default path is local files only. HTTP(S) and ipfs are rejected unless a
caller injects a network fetcher. HTTPS is convenience, not a security
boundary. Hash mismatch still fails closed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from ai4.identity.digest import sha256_hex
from ai4.identity.errors import IdentityError
from ai4.identity.resolve.types import MAX_ATTESTATION_BYTES


class Fetcher(Protocol):
    def fetch(self, uri: str) -> bytes:
        """Return exact hosted bytes. Must not parse identity records."""


class LocalFileFetcher:
    """Read attestation bytes from a local path. No sockets, no redirects."""

    def __init__(self, base_dir: str | Path, *, max_bytes: int = MAX_ATTESTATION_BYTES) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.max_bytes = max_bytes

    def fetch(self, uri: str) -> bytes:
        if not isinstance(uri, str) or not uri:
            raise IdentityError("attestation_uri is missing")
        if _is_network_uri(uri):
            raise IdentityError(
                "network fetch is disabled; default discovery path is local files only"
            )
        if uri.startswith("file://"):
            raw_path = uri[len("file://") :]
        else:
            raw_path = uri
        path = Path(raw_path)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        else:
            path = path.resolve()
        try:
            path.relative_to(self.base_dir)
        except ValueError as exc:
            raise IdentityError("attestation path escapes fetcher base directory") from exc
        if not path.is_file():
            raise IdentityError(f"attestation file not found: {path}")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise IdentityError("attestation fetch exceeds size cap")
        data = path.read_bytes()
        if len(data) > self.max_bytes:
            raise IdentityError("attestation fetch exceeds size cap")
        return data


def require_digest_agreement(blobs: Sequence[bytes]) -> bytes:
    """Fail closed when gateways disagree. No majority vote."""
    if not blobs:
        raise IdentityError("no gateway payloads to compare")
    digests = {sha256_hex(blob) for blob in blobs}
    if len(digests) != 1:
        raise IdentityError("gateway digest disagreement; failing closed with no majority vote")
    return blobs[0]


def fetch_attestation_bytes(
    uri: str,
    fetcher: Fetcher,
    *,
    extra_fetchers: Sequence[Fetcher] = (),
) -> bytes:
    """Fetch attestation bytes. Optional extra fetchers must agree on digest."""
    if not uri:
        raise IdentityError("attestation_uri is missing")
    primary = fetcher.fetch(uri)
    if len(primary) > MAX_ATTESTATION_BYTES:
        raise IdentityError("attestation fetch exceeds size cap")
    if not extra_fetchers:
        return primary
    blobs = [primary]
    for extra in extra_fetchers:
        blobs.append(extra.fetch(uri))
    return require_digest_agreement(blobs)


def _is_network_uri(uri: str) -> bool:
    lowered = uri.lower()
    return lowered.startswith(("http://", "https://", "ipfs://", "ipns://"))
