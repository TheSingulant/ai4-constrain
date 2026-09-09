"""PR-E review remediations S1-S5. Offline identity kernel only."""

from __future__ import annotations

from datetime import timedelta

import pytest
import rfc8785

from ai4.constrain import evaluate
from ai4.identity import (
    MANIFEST_VERSION_MAX,
    MANIFEST_VERSION_MIN,
    RFC8785_PACKAGE_VERSION,
    AgentIdentity,
    FixedClock,
    IdentityError,
    RotationAttestation,
    TrustContext,
    bind_report,
    canonicalize,
    generate_ed25519_keypair,
    report_digest,
    sign_attestation,
    sign_rotation,
    verify_attestation,
    verify_attestation_signature,
    verify_report_binding,
    verify_rotation,
)
from ai4.identity.crypto import encode_signature
from tests.test_identity_kernel import CLEAN_TEXT, LATER, NOW, _identity, _signed


def test_s1_signature_validity_is_not_current_trust():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public, version=1)
    att = _signed(identity, seed)
    historical = verify_attestation_signature(att, clock=FixedClock(NOW))
    assert historical.identity.manifest_version == 1
    with pytest.raises(IdentityError, match="TrustContext|current trust"):
        verify_attestation(att, None, clock=FixedClock(NOW))  # type: ignore[arg-type]
    report = evaluate(CLEAN_TEXT)
    bound = _signed(identity, seed, binding=bind_report(report))
    crypto_only = verify_report_binding(bound, report, clock=FixedClock(NOW))
    assert crypto_only.verdict == "untrusted_signer"
    assert "TrustContext required" in crypto_only.detail
    assert crypto_only.verdict != "matched"
    current = verify_report_binding(
        bound, report, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW)
    )
    assert current.verdict == "matched"


def test_s1_v1_remains_crypto_valid_after_v2_but_is_not_current():
    old_seed, old_pub = generate_ed25519_keypair()
    new_seed, new_pub = generate_ed25519_keypair()
    v1 = _identity(old_pub, version=1)
    v2 = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=new_pub,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
    )
    rotation = sign_rotation(
        previous_identity=v1,
        new_identity=v2,
        previous_private_key=old_seed,
        issued_at=NOW,
        expires_at=LATER,
    )
    v1_att = _signed(v1, old_seed)
    v2_att = _signed(v2, new_seed, rotation=rotation)
    verify_attestation_signature(v1_att, clock=FixedClock(NOW))
    verify_attestation(v2_att, TrustContext.from_identity(v1), clock=FixedClock(NOW))
    with pytest.raises(IdentityError, match="not current|superseded|controller"):
        verify_attestation(v1_att, TrustContext.from_identity(v2), clock=FixedClock(NOW))
    report = evaluate(CLEAN_TEXT)
    v1_bound = _signed(v1, old_seed, binding=bind_report(report))
    result = verify_report_binding(
        v1_bound, report, trust=TrustContext.from_identity(v2), clock=FixedClock(NOW)
    )
    assert result.verdict == "untrusted_signer"
    assert result.verdict != "matched"


def test_s2_rotation_binds_identity_and_successor_manifest():
    old_seed, old_pub = generate_ed25519_keypair()
    new_seed, new_pub = generate_ed25519_keypair()
    previous = _identity(old_pub, version=1)
    successor = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=new_pub,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
    )
    rotation = sign_rotation(
        previous_identity=previous,
        new_identity=successor,
        previous_private_key=old_seed,
        issued_at=NOW,
        expires_at=LATER,
    )
    assert rotation.identity_id == "agent-alpha"
    assert rotation.new_manifest_hash == successor.manifest_hash()
    advanced = verify_rotation(
        rotation, TrustContext.from_identity(previous), successor=successor, clock=FixedClock(NOW)
    )
    assert advanced == TrustContext.from_identity(successor)
    assert advanced.manifest_hash != ""


def test_s2_rotation_for_alpha_cannot_authorize_mallory():
    old_seed, old_pub = generate_ed25519_keypair()
    new_seed, new_pub = generate_ed25519_keypair()
    mallory_seed, mallory_pub = generate_ed25519_keypair()
    previous = _identity(old_pub, version=1)
    successor = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=new_pub,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
    )
    mallory = AgentIdentity.create(
        identity_id="mallory",
        controller_public_key=mallory_pub,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
    )
    with pytest.raises(IdentityError, match="identity_id mismatch|different agent"):
        sign_rotation(
            previous_identity=previous,
            new_identity=mallory,
            previous_private_key=old_seed,
            issued_at=NOW,
            expires_at=LATER,
        )
    rotation = sign_rotation(
        previous_identity=previous,
        new_identity=successor,
        previous_private_key=old_seed,
        issued_at=NOW,
        expires_at=LATER,
    )
    with pytest.raises(IdentityError, match="different agent|identity_id"):
        verify_rotation(
            rotation,
            TrustContext.from_identity(previous),
            successor=mallory,
            clock=FixedClock(NOW),
        )
    with pytest.raises(IdentityError, match="different agent|identity_id"):
        sign_attestation(
            mallory,
            mallory_seed,
            issued_at=NOW,
            expires_at=LATER,
            rotation=rotation,
        )


def test_s2_rotation_rejects_hash_mismatch_same_rollback_forged_expired_future():
    old_seed, old_pub = generate_ed25519_keypair()
    new_seed, new_pub = generate_ed25519_keypair()
    previous = _identity(old_pub, version=1)
    successor = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=new_pub,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
    )
    other = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=new_pub,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
        manifest_uri="https://example.invalid/other",
    )
    rotation = sign_rotation(
        previous_identity=previous,
        new_identity=successor,
        previous_private_key=old_seed,
        issued_at=NOW,
        expires_at=LATER,
    )
    trust = TrustContext.from_identity(previous)
    with pytest.raises(IdentityError, match="successor manifest-hash mismatch"):
        verify_rotation(rotation, trust, successor=other, clock=FixedClock(NOW))
    with pytest.raises(IdentityError, match="monotonic"):
        RotationAttestation.from_dict({**rotation.to_dict(), "new_manifest_version": 1})
    with pytest.raises(IdentityError, match="monotonic"):
        RotationAttestation.from_dict({**rotation.to_dict(), "new_manifest_version": 2, "previous_manifest_version": 2})
    forged = rotation.to_dict()
    forged["signature"] = encode_signature(b"\x22" * 64)
    with pytest.raises(IdentityError, match="invalid"):
        verify_rotation(RotationAttestation.from_dict(forged), trust, clock=FixedClock(NOW))
    expired = sign_rotation(
        previous_identity=previous,
        new_identity=successor,
        previous_private_key=old_seed,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(IdentityError, match="expired"):
        verify_rotation(expired, trust, clock=FixedClock(LATER))
    future = sign_rotation(
        previous_identity=previous,
        new_identity=successor,
        previous_private_key=old_seed,
        issued_at=NOW + timedelta(minutes=10),
        expires_at=LATER,
    )
    with pytest.raises(IdentityError, match="not yet valid"):
        verify_rotation(future, trust, clock=FixedClock(NOW))


def test_s2_skip_version_rotation_v1_to_v3_is_allowed():
    old_seed, old_pub = generate_ed25519_keypair()
    new_seed, new_pub = generate_ed25519_keypair()
    v1 = _identity(old_pub, version=1)
    v3 = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=new_pub,
        manifest_version=3,
        issued_at=NOW,
        expires_at=LATER,
    )
    rotation = sign_rotation(
        previous_identity=v1,
        new_identity=v3,
        previous_private_key=old_seed,
        issued_at=NOW,
        expires_at=LATER,
    )
    assert rotation.new_manifest_version == 3
    advanced = verify_rotation(
        rotation, TrustContext.from_identity(v1), successor=v3, clock=FixedClock(NOW)
    )
    assert advanced.manifest_version == 3
    assert advanced.manifest_hash == v3.manifest_hash()
    verify_attestation(_signed(v3, new_seed, rotation=rotation), TrustContext.from_identity(v1), clock=FixedClock(NOW))
    with pytest.raises(IdentityError, match="not current|superseded|controller"):
        verify_attestation(_signed(v1, old_seed), TrustContext.from_identity(v3), clock=FixedClock(NOW))


def test_s3_bind_report_ignores_forged_versions_attribute():
    report = evaluate(CLEAN_TEXT)
    honest = bind_report(report)

    class SplitBrain:
        def __init__(self) -> None:
            self.versions = type(
                "Forged",
                (),
                {
                    "to_dict": lambda self: {
                        **report.versions.to_dict(),
                        "evidence_class": "forged_from_versions",
                        "evaluator_id": "llm-judge-v2",
                    }
                },
            )()

        def to_dict(self):
            return report.to_dict()

    bound = bind_report(SplitBrain())
    assert bound.report_hash == honest.report_hash
    assert bound.claimed_profile.evidence_class == "null_retained_D_adds_cost"
    assert bound.claimed_profile.evaluator_id == honest.claimed_profile.evaluator_id
    assert bound.claimed_profile.evidence_class != "forged_from_versions"


def test_s4_rfc8785_is_pinned_and_signed_zero_collapses():
    assert RFC8785_PACKAGE_VERSION == "0.1.4"
    assert rfc8785.__version__ == "0.1.4"
    plus = canonicalize({"n": 0.0})
    minus = canonicalize({"n": -0.0})
    assert plus == minus == rfc8785.dumps({"n": 0.0}) == b'{"n":0}'
    telemetry = {
        "latency_ms": 12.5,
        "estimated_usd": 0.0,
        "score": 0.85,
        "prompt_tokens": 3,
    }
    locked = canonicalize(telemetry)
    assert locked == b'{"estimated_usd":0,"latency_ms":12.5,"prompt_tokens":3,"score":0.85}'
    report = evaluate(CLEAN_TEXT)
    first = report_digest(report)
    second = report_digest(report)
    third = report_digest(report.to_dict())
    assert first == second == third
    assert len(first) == 64


def test_s5_manifest_version_jcs_safe_domain():
    seed, public = generate_ed25519_keypair()
    del seed
    assert MANIFEST_VERSION_MIN == 1
    assert MANIFEST_VERSION_MAX == (2**53) - 1
    max_ok = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=public,
        manifest_version=MANIFEST_VERSION_MAX,
        issued_at=NOW,
        expires_at=LATER,
    )
    assert max_ok.manifest_hash()
    with pytest.raises(IdentityError, match="JCS-safe|must be <="):
        AgentIdentity.create(
            identity_id="agent-alpha",
            controller_public_key=public,
            manifest_version=MANIFEST_VERSION_MAX + 1,
            issued_at=NOW,
            expires_at=LATER,
        )
    raw = _identity(public).to_dict()
    raw["manifest_version"] = True
    with pytest.raises(IdentityError, match="integer"):
        AgentIdentity.from_dict(raw)
    raw["manifest_version"] = -1
    with pytest.raises(IdentityError, match="must be >= 1"):
        AgentIdentity.from_dict(raw)
    raw["manifest_version"] = 0
    with pytest.raises(IdentityError, match="must be >= 1"):
        AgentIdentity.from_dict(raw)
