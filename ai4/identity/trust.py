"""Single-controller current-trust context. No CRL, no network revocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai4.identity.crypto import (
    Verifier,
    decode_public_key_hex,
    decode_signature_hex,
    default_verifier,
    encode_public_key,
)
from ai4.identity.errors import IdentityError
from ai4.identity.schemas import (
    AgentIdentity,
    RotationAttestation,
    require_identity_id,
    require_manifest_version,
    require_sha256_hex,
)
from ai4.identity.timeutil import Clock, SystemClock, is_expired, is_not_yet_valid, require_aware_utc

TRUST_KEYS = (
    "identity_id",
    "controller_public_key",
    "manifest_version",
    "manifest_hash",
)


@dataclass(frozen=True)
class TrustContext:
    """The single current controller for this verifier.

    Identity is not trust. This object is the caller's trust input.
    Cryptographic signature validity is not current trust.
    """

    identity_id: str
    controller_public_key: str
    manifest_version: int
    manifest_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "controller_public_key": self.controller_public_key,
            "manifest_version": self.manifest_version,
            "manifest_hash": self.manifest_hash,
        }

    @classmethod
    def from_identity(cls, identity: AgentIdentity) -> TrustContext:
        return cls(
            identity_id=identity.identity_id,
            controller_public_key=identity.controller_public_key,
            manifest_version=identity.manifest_version,
            manifest_hash=identity.manifest_hash(),
        )

    @classmethod
    def from_dict(cls, raw: object) -> TrustContext:
        if not isinstance(raw, dict):
            raise IdentityError("TrustContext must be a JSON object")
        extra = sorted(str(key) for key in raw if key not in TRUST_KEYS)
        if extra:
            raise IdentityError(f"Unknown TrustContext field(s) {extra}; failing closed")
        missing = [key for key in TRUST_KEYS if key not in raw]
        if missing:
            raise IdentityError(f"TrustContext missing keys: {missing}")
        return cls(
            identity_id=require_identity_id(raw["identity_id"]),
            controller_public_key=encode_public_key(
                decode_public_key_hex(raw["controller_public_key"])
            ),
            manifest_version=require_manifest_version(raw["manifest_version"]),
            manifest_hash=require_sha256_hex(raw["manifest_hash"], field="manifest_hash"),
        )


def verify_rotation(
    rotation: RotationAttestation,
    trust: TrustContext,
    *,
    successor: AgentIdentity | None = None,
    clock: Clock | None = None,
    verifier: Verifier | None = None,
    now: datetime | None = None,
) -> TrustContext:
    """Accept a rotation signed by the current (old) controller key.

    Returns a complete TrustContext for the successor (identity_id, new
    controller, new version, new manifest hash). Does not write a CRL.
    Compromised-key recovery remains a residual risk.

    Versions must be strictly monotonic. Skipping (for example v1→v3) is
    allowed and abandons intermediate versions; those versions are not
    current and are not listed on a CRL.
    """
    when = _now(clock, now)
    if is_not_yet_valid(rotation.issued_at, now=when):
        raise IdentityError("rotation attestation is not yet valid")
    if is_expired(rotation.expires_at, now=when):
        raise IdentityError("rotation attestation expired")
    if rotation.identity_id != trust.identity_id:
        raise IdentityError(
            "rotation identity_id does not match current trust; "
            "a rotation cannot authorize a different agent"
        )
    if rotation.previous_controller_public_key != trust.controller_public_key:
        raise IdentityError("rotation previous controller does not match current trust")
    if rotation.previous_manifest_version != trust.manifest_version:
        raise IdentityError("rotation previous manifest_version does not match current trust")
    if rotation.previous_manifest_hash != trust.manifest_hash:
        raise IdentityError("rotation previous manifest_hash does not match current trust")
    if rotation.new_manifest_version <= trust.manifest_version:
        raise IdentityError("rotation manifest_version is not monotonic")
    if successor is not None:
        if successor.identity_id != rotation.identity_id:
            raise IdentityError(
                "rotation identity_id does not match successor identity; "
                "a rotation cannot authorize a different agent"
            )
        if successor.controller_public_key != rotation.new_controller_public_key:
            raise IdentityError("rotation new controller does not match successor identity")
        if successor.manifest_version != rotation.new_manifest_version:
            raise IdentityError("rotation new manifest_version does not match successor identity")
        if successor.manifest_hash() != rotation.new_manifest_hash:
            raise IdentityError("successor manifest-hash mismatch")
    impl = verifier or default_verifier()
    ok = impl.verify(
        decode_public_key_hex(rotation.previous_controller_public_key),
        rotation.tbs_bytes(),
        decode_signature_hex(rotation.signature),
    )
    if not ok:
        raise IdentityError("rotation signature is invalid")
    return TrustContext(
        identity_id=rotation.identity_id,
        controller_public_key=rotation.new_controller_public_key,
        manifest_version=rotation.new_manifest_version,
        manifest_hash=rotation.new_manifest_hash,
    )


def assert_current_trust(identity: AgentIdentity, trust: TrustContext) -> None:
    if identity.identity_id != trust.identity_id:
        raise IdentityError("identity_id is not the current trusted identity")
    if identity.controller_public_key != trust.controller_public_key:
        raise IdentityError("controller public key is not the current trusted controller")
    if identity.manifest_version != trust.manifest_version:
        raise IdentityError(
            "manifest_version is not current; superseded identity replay is rejected"
        )
    if identity.manifest_hash() != trust.manifest_hash:
        raise IdentityError("manifest hash does not match current trust")


def _now(clock: Clock | None, now: datetime | None) -> datetime:
    if now is not None:
        return require_aware_utc(now)
    return require_aware_utc((clock or SystemClock()).now())
