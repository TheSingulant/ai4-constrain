"""Sign and verify AgentAttestation records. Fully offline.

Signature validity is not current trust. Historical / cryptographic
verification is ``verify_attestation_signature``. Current identity
requires an explicit ``TrustContext`` via ``verify_attestation``.
"""

from __future__ import annotations

from datetime import datetime

from ai4.identity.crypto import (
    Signer,
    Verifier,
    decode_public_key_hex,
    decode_signature_hex,
    default_signer,
    default_verifier,
    encode_signature,
)
from ai4.identity.errors import IdentityError
from ai4.identity.schemas import (
    SIGNATURE_ALGORITHM,
    AgentAttestation,
    AgentIdentity,
    ClaimedProfile,
    RotationAttestation,
)
from ai4.identity.timeutil import (
    Clock,
    SystemClock,
    format_utc,
    is_expired,
    is_not_yet_valid,
    require_aware_utc,
    require_expiry_window,
)
from ai4.identity.trust import TrustContext, assert_current_trust, verify_rotation


def sign_attestation(
    identity: AgentIdentity,
    private_key: bytes,
    *,
    issued_at: datetime | str,
    expires_at: datetime | str,
    binding: object | None = None,
    rotation: RotationAttestation | None = None,
    signer: Signer | None = None,
) -> AgentAttestation:
    """Sign an identity record (and optional report binding) with Ed25519.

    The private key never enters the attestation. The resulting record
    binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.
    """
    if not isinstance(identity, AgentIdentity):
        raise IdentityError("sign_attestation requires a frozen AgentIdentity")
    impl = signer or default_signer()
    public = impl.public_key_bytes(private_key)
    if public.hex() != identity.controller_public_key:
        raise IdentityError("private key does not match identity.controller_public_key")
    issued = format_utc(issued_at)
    expires = format_utc(expires_at)
    require_expiry_window(issued, expires)
    report_hash = ""
    claimed_profile: ClaimedProfile | None = None
    if binding is not None:
        report_hash, claimed_profile = _extract_binding(binding)
    if rotation is not None:
        _assert_rotation_matches_identity(rotation, identity)
    unsigned = AgentAttestation(
        identity=identity,
        manifest_hash=identity.manifest_hash(),
        signature="0" * 128,
        issued_at=issued,
        expires_at=expires,
        report_hash=report_hash,
        claimed_profile=claimed_profile,
        rotation=rotation,
        signature_algorithm=SIGNATURE_ALGORITHM,
    )
    signature = encode_signature(impl.sign(private_key, unsigned.tbs_bytes()))
    return AgentAttestation.from_dict({**unsigned.to_dict(), "signature": signature})


def sign_rotation(
    *,
    previous_identity: AgentIdentity,
    new_identity: AgentIdentity,
    previous_private_key: bytes,
    issued_at: datetime | str,
    expires_at: datetime | str,
    signer: Signer | None = None,
) -> RotationAttestation:
    """Sign a single-controller rotation with the previous key.

    Binds identity_id, the new controller public key, the new manifest
    version, and the new manifest hash. Skip-version rotations
    (new_version > old_version + 1) are allowed and abandon skipped
    versions.
    """
    if previous_identity.identity_id != new_identity.identity_id:
        raise IdentityError(
            "rotation identity_id mismatch; a rotation cannot authorize a different agent"
        )
    if new_identity.manifest_version <= previous_identity.manifest_version:
        raise IdentityError("rotation manifest_version must be strictly monotonic")
    if new_identity.controller_public_key == previous_identity.controller_public_key:
        raise IdentityError("rotation must introduce a new controller public key")
    impl = signer or default_signer()
    if impl.public_key_bytes(previous_private_key).hex() != previous_identity.controller_public_key:
        raise IdentityError("previous private key does not match previous identity")
    issued = format_utc(issued_at)
    expires = format_utc(expires_at)
    require_expiry_window(issued, expires)
    unsigned = RotationAttestation(
        identity_id=previous_identity.identity_id,
        previous_controller_public_key=previous_identity.controller_public_key,
        previous_manifest_version=previous_identity.manifest_version,
        previous_manifest_hash=previous_identity.manifest_hash(),
        new_controller_public_key=new_identity.controller_public_key,
        new_manifest_version=new_identity.manifest_version,
        new_manifest_hash=new_identity.manifest_hash(),
        issued_at=issued,
        expires_at=expires,
        signature="0" * 128,
    )
    signature = encode_signature(impl.sign(previous_private_key, unsigned.tbs_bytes()))
    return RotationAttestation.from_dict({**unsigned.to_dict(), "signature": signature})


def verify_attestation_signature(
    attestation: AgentAttestation | object,
    *,
    clock: Clock | None = None,
    verifier: Verifier | None = None,
    now: datetime | None = None,
) -> AgentAttestation:
    """Historical / cryptographic verification. Not current trust.

    Checks schema, expiry window against the supplied clock, manifest
    hash integrity, and Ed25519 signature. A success means the record
    is well-formed and the signature is valid for the embedded
    controller key. It does **not** mean the identity is current.
    """
    record = (
        attestation
        if isinstance(attestation, AgentAttestation)
        else AgentAttestation.from_dict(attestation)
    )
    when = require_aware_utc(now) if now is not None else require_aware_utc((clock or SystemClock()).now())
    if is_not_yet_valid(record.issued_at, now=when) or is_not_yet_valid(
        record.identity.issued_at, now=when
    ):
        raise IdentityError("attestation is not yet valid")
    if is_expired(record.expires_at, now=when) or is_expired(record.identity.expires_at, now=when):
        raise IdentityError("attestation expired")
    expected_hash = record.identity.manifest_hash()
    if record.manifest_hash != expected_hash:
        raise IdentityError("wrong manifest hash")
    _assert_uri_does_not_override(record)
    impl = verifier or default_verifier()
    if not impl.verify(
        decode_public_key_hex(record.identity.controller_public_key),
        record.tbs_bytes(),
        decode_signature_hex(record.signature),
    ):
        raise IdentityError("bad controller key or invalid Ed25519 signature")
    return record


def verify_attestation(
    attestation: AgentAttestation | object,
    trust: TrustContext,
    *,
    clock: Clock | None = None,
    verifier: Verifier | None = None,
    now: datetime | None = None,
) -> AgentAttestation:
    """Verify that an attestation is cryptographically valid **and current**.

    Requires an explicit ``TrustContext``. Signature validity alone is
    not current identity; use ``verify_attestation_signature`` for
    historical / cryptographic verification.

    Fails closed on malformed records, extra fields, unknown algorithms,
    bad controller keys, wrong manifest hashes, expiry, identity-id
    mismatch, and replay of a superseded identity. Does not consult a
    network, wallet, or CRL.
    """
    if not isinstance(trust, TrustContext):
        raise IdentityError(
            "verify_attestation requires TrustContext for current trust; "
            "use verify_attestation_signature for historical/crypto-only verification"
        )
    record = verify_attestation_signature(
        attestation, clock=clock, verifier=verifier, now=now
    )
    when = require_aware_utc(now) if now is not None else require_aware_utc((clock or SystemClock()).now())
    current_trust = trust
    if record.rotation is not None:
        current_trust = verify_rotation(
            record.rotation,
            trust,
            successor=record.identity,
            clock=clock,
            verifier=verifier or default_verifier(),
            now=when,
        )
    assert_current_trust(record.identity, current_trust)
    return record


def _assert_rotation_matches_identity(rotation: RotationAttestation, identity: AgentIdentity) -> None:
    if rotation.identity_id != identity.identity_id:
        raise IdentityError(
            "rotation identity_id must match identity; a rotation cannot authorize a different agent"
        )
    if rotation.new_controller_public_key != identity.controller_public_key:
        raise IdentityError("rotation new controller must match identity")
    if rotation.new_manifest_version != identity.manifest_version:
        raise IdentityError("rotation new manifest_version must match identity")
    if rotation.new_manifest_hash != identity.manifest_hash():
        raise IdentityError("rotation new manifest_hash must match identity")


def _assert_uri_does_not_override(record: AgentAttestation) -> None:
    """Integrity is the hash of local canonical identity bytes, never a URI fetch."""
    uri = record.identity.manifest_uri
    if not uri:
        return
    recomputed = record.identity.manifest_hash()
    if recomputed != record.manifest_hash:
        raise IdentityError("manifest URI cannot override hash integrity")


def _extract_binding(binding: object) -> tuple[str, ClaimedProfile]:
    report_hash = getattr(binding, "report_hash", None)
    claimed = getattr(binding, "claimed_profile", None)
    if isinstance(binding, dict):
        report_hash = binding.get("report_hash")
        claimed = binding.get("claimed_profile")
    if not isinstance(report_hash, str) or not report_hash:
        raise IdentityError("binding.report_hash is required")
    if isinstance(claimed, ClaimedProfile):
        profile = claimed
    else:
        profile = ClaimedProfile.from_dict(claimed)
    return report_hash, profile
