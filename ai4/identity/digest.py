"""SHA-256 digests over canonical bytes. No other hash functions."""

from __future__ import annotations

import hashlib

from ai4.identity.canonical import canonicalize


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256 of raw bytes."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("sha256_hex requires bytes")
    return hashlib.sha256(data).hexdigest()


def digest_canonical(value: object, *, identity_record: bool = False) -> str:
    """SHA-256 of RFC 8785 JCS bytes."""
    return sha256_hex(canonicalize(value, identity_record=identity_record))
