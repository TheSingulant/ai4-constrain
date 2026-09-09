"""Ed25519 signing and verification with inverted dependencies.

Default implementations use the ``cryptography`` library's Ed25519
primitive. They perform no I/O, open no sockets, and never contact a
wallet, chain, TEE, or HTTP service.

Callers may inject their own ``Signer`` / ``Verifier``. The kernel does
not invent cryptography.
"""

from __future__ import annotations

from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from ai4.identity.errors import IdentityError

SIGNATURE_ALGORITHM = "ed25519"
PUBLIC_KEY_HEX_LEN = 64
SIGNATURE_HEX_LEN = 128
SEED_LEN = 32
PUBLIC_KEY_LEN = 32
SIGNATURE_LEN = 64


class Signer(Protocol):
    def sign(self, private_key: bytes, message: bytes) -> bytes:
        """Return a 64-byte Ed25519 signature."""

    def public_key_bytes(self, private_key: bytes) -> bytes:
        """Return the 32-byte public key for ``private_key``."""


class Verifier(Protocol):
    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        """Return True if the signature is valid. Must not raise on bad sigs."""


class LocalEd25519:
    """Offline Ed25519 using ``cryptography``. No network, no key store."""

    def sign(self, private_key: bytes, message: bytes) -> bytes:
        key = _private_key(private_key)
        if not isinstance(message, (bytes, bytearray)):
            raise IdentityError("Ed25519 message must be bytes")
        return key.sign(bytes(message))

    def public_key_bytes(self, private_key: bytes) -> bytes:
        return _raw_public_bytes(_private_key(private_key).public_key())

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        try:
            pub = _public_key(public_key)
            if not isinstance(message, (bytes, bytearray)):
                raise IdentityError("Ed25519 message must be bytes")
            if not isinstance(signature, (bytes, bytearray)) or len(signature) != SIGNATURE_LEN:
                return False
            pub.verify(bytes(signature), bytes(message))
            return True
        except (IdentityError, InvalidSignature, ValueError):
            return False


def generate_ed25519_keypair(signer: Signer | None = None) -> tuple[bytes, bytes]:
    """Return ``(private_seed, public_key)`` raw bytes. For tests and local use."""
    del signer
    private = Ed25519PrivateKey.generate()
    return _raw_private_bytes(private), _raw_public_bytes(private.public_key())


def encode_hex(raw: bytes) -> str:
    if not isinstance(raw, (bytes, bytearray)):
        raise IdentityError("hex encoding requires bytes")
    return bytes(raw).hex()


def decode_public_key_hex(value: object) -> bytes:
    text = _hex_blob(value, field="controller_public_key", length=PUBLIC_KEY_HEX_LEN)
    return bytes.fromhex(text)


def decode_signature_hex(value: object) -> bytes:
    text = _hex_blob(value, field="signature", length=SIGNATURE_HEX_LEN)
    return bytes.fromhex(text)


def encode_public_key(raw: bytes) -> str:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != PUBLIC_KEY_LEN:
        raise IdentityError("Ed25519 public key must be 32 raw bytes")
    return encode_hex(raw)


def encode_signature(raw: bytes) -> str:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != SIGNATURE_LEN:
        raise IdentityError("Ed25519 signature must be 64 raw bytes")
    return encode_hex(raw)


def default_signer() -> LocalEd25519:
    return LocalEd25519()


def default_verifier() -> LocalEd25519:
    return LocalEd25519()


def _private_key(private_key: bytes) -> Ed25519PrivateKey:
    if not isinstance(private_key, (bytes, bytearray)) or len(private_key) != SEED_LEN:
        raise IdentityError("Ed25519 private key must be 32 raw seed bytes")
    try:
        return Ed25519PrivateKey.from_private_bytes(bytes(private_key))
    except ValueError as exc:
        raise IdentityError(f"Invalid Ed25519 private key: {exc}") from exc


def _public_key(public_key: bytes) -> Ed25519PublicKey:
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != PUBLIC_KEY_LEN:
        raise IdentityError("Ed25519 public key must be 32 raw bytes")
    try:
        return Ed25519PublicKey.from_public_bytes(bytes(public_key))
    except ValueError as exc:
        raise IdentityError(f"Invalid Ed25519 public key: {exc}") from exc


def _raw_private_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def _raw_public_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _hex_blob(value: object, *, field: str, length: int) -> str:
    if not isinstance(value, str) or len(value) != length:
        raise IdentityError(f"{field} must be {length}-char lowercase hex")
    if value != value.lower() or any(ch not in "0123456789abcdef" for ch in value):
        raise IdentityError(f"{field} must be lowercase hex")
    return value
