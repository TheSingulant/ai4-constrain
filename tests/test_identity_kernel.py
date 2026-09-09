"""PR-E adversarial oracles for the offline identity/provenance kernel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import rfc8785

from ai4.constrain import evaluate
from ai4.identity import (
    CANONICALIZATION_PROFILE,
    GOVERNING_PRINCIPLE,
    AgentAttestation,
    AgentIdentity,
    BindingResult,
    FixedClock,
    IdentityError,
    NameRecordSnapshot,
    RotationAttestation,
    TrustContext,
    bind_report,
    canonicalize,
    generate_ed25519_keypair,
    sign_attestation,
    sign_rotation,
    verify_attestation,
    verify_attestation_signature,
    verify_report_binding,
    verify_rotation,
)
from ai4.identity.canonical import canonicalize_utf8
from ai4.identity.crypto import LocalEd25519, encode_public_key, encode_signature
from ai4.identity.schemas import ClaimedProfile
from ai4.constrain.runtime import EVIDENCE_CLASS

CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)


def _identity(public: bytes, *, version: int = 1, uri: str = "", names=()) -> AgentIdentity:
    return AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=public,
        manifest_version=version,
        issued_at=NOW,
        expires_at=LATER,
        name_records=names,
        manifest_uri=uri,
    )


def _signed(identity: AgentIdentity, seed: bytes, **kwargs):
    return sign_attestation(
        identity,
        seed,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        **kwargs,
    )


def test_governing_principle_is_locked_in_module_and_docs():
    needle = (
        "A signed AI⁴ identity record binds claims and provenance to an agent "
        "identity; it does not prove the agent is aligned, safe, or correctly "
        "governed."
    )
    assert GOVERNING_PRINCIPLE == needle
    docs = Path("docs/identity.md").read_text(encoding="utf-8")
    module = Path("ai4/identity/__init__.py").read_text(encoding="utf-8")
    assert needle in docs
    assert needle in module
    assert "Identity is not trust" in docs
    assert CANONICALIZATION_PROFILE == "rfc8785-jcs"


def test_rfc8785_jcs_is_deterministic_and_key_order_independent():
    left = {"b": 2, "a": {"z": 1, "y": [True, False, None, 0]}}
    right = {"a": {"y": [True, False, None, 0], "z": 1}, "b": 2}
    assert canonicalize(left) == canonicalize(right) == rfc8785.dumps(left)
    assert canonicalize_utf8(left, identity_record=True) == '{"a":{"y":[true,false,null,0],"z":1},"b":2}'


def test_identity_canonicalization_rejects_floats_and_extra_types():
    with pytest.raises(IdentityError, match="forbids floats"):
        canonicalize({"score": 1.5}, identity_record=True)
    with pytest.raises(IdentityError, match="forbids bytes"):
        canonicalize({"k": b"nope"}, identity_record=True)
    with pytest.raises(IdentityError, match="forbids sets"):
        canonicalize({"k": {1}}, identity_record=True)
    with pytest.raises(IdentityError, match="keys must be strings"):
        canonicalize({1: "x"}, identity_record=True)


def test_malformed_and_extra_identity_fields_fail_closed():
    seed, public = generate_ed25519_keypair()
    del seed
    raw = _identity(public).to_dict()
    raw["wallet"] = "0xabc"
    with pytest.raises(IdentityError, match="Unknown AgentIdentity field"):
        AgentIdentity.from_dict(raw)
    missing = _identity(public).to_dict()
    missing.pop("controller_public_key")
    with pytest.raises(IdentityError, match="missing keys"):
        AgentIdentity.from_dict(missing)
    with pytest.raises(IdentityError, match="must be a JSON object"):
        AgentIdentity.from_dict([])
    bad_id = _identity(public).to_dict()
    bad_id["identity_id"] = "0x" + ("ab" * 20)
    with pytest.raises(IdentityError, match="wallet"):
        AgentIdentity.from_dict(bad_id)
    token_id = _identity(public).to_dict()
    token_id["identity_id"] = "token:usdc"
    with pytest.raises(IdentityError, match="wallet"):
        AgentIdentity.from_dict(token_id)
    version = _identity(public).to_dict()
    version["manifest_version"] = True
    with pytest.raises(IdentityError, match="integer"):
        AgentIdentity.from_dict(version)


def test_malformed_and_extra_attestation_fields_fail_closed():
    seed, public = generate_ed25519_keypair()
    att = _signed(_identity(public), seed)
    raw = att.to_dict()
    raw["tee_quote"] = "nope"
    with pytest.raises(IdentityError, match="Unknown AgentAttestation field"):
        AgentAttestation.from_dict(raw)
    raw = att.to_dict()
    raw.pop("signature")
    with pytest.raises(IdentityError, match="missing keys"):
        AgentAttestation.from_dict(raw)
    with pytest.raises(IdentityError, match="must be a JSON object"):
        AgentAttestation.from_dict("nope")


def test_unknown_signature_algorithm_fails_closed():
    seed, public = generate_ed25519_keypair()
    raw = _signed(_identity(public), seed).to_dict()
    raw["signature_algorithm"] = "rsa-pss"
    with pytest.raises(IdentityError, match="Unknown signature algorithm"):
        AgentAttestation.from_dict(raw)
    with pytest.raises(IdentityError, match="Unknown signature algorithm"):
        verify_attestation_signature(raw, clock=FixedClock(NOW))


def test_bad_controller_key_fails_closed():
    seed, public = generate_ed25519_keypair()
    other_seed, other_pub = generate_ed25519_keypair()
    identity = _identity(public)
    with pytest.raises(IdentityError, match="does not match identity"):
        sign_attestation(identity, other_seed, issued_at=NOW, expires_at=LATER)
    att = _signed(identity, seed)
    raw = att.to_dict()
    raw["identity"]["controller_public_key"] = encode_public_key(other_pub)
    with pytest.raises(IdentityError, match="manifest hash|signature|controller"):
        verify_attestation_signature(raw, clock=FixedClock(NOW))
    flipped = att.to_dict()
    flipped["signature"] = encode_signature(b"\x00" * 64)
    with pytest.raises(IdentityError, match="signature|controller"):
        verify_attestation_signature(flipped, clock=FixedClock(NOW))


def test_wrong_manifest_hash_fails_closed():
    seed, public = generate_ed25519_keypair()
    att = _signed(_identity(public), seed)
    raw = att.to_dict()
    raw["manifest_hash"] = "ab" * 32
    raw["signature"] = att.signature
    with pytest.raises(IdentityError, match="wrong manifest hash"):
        verify_attestation_signature(raw, clock=FixedClock(NOW))
    mutated = AgentIdentity.create(
        identity_id="agent-beta",
        controller_public_key=public,
        manifest_version=1,
        issued_at=NOW,
        expires_at=LATER,
    )
    raw = att.to_dict()
    raw["identity"] = mutated.to_dict()
    with pytest.raises(IdentityError, match="wrong manifest hash|signature"):
        verify_attestation_signature(raw, clock=FixedClock(NOW))


def test_expires_at_not_after_issued_at_fails_closed():
    seed, public = generate_ed25519_keypair()
    with pytest.raises(IdentityError, match="expires_at must be strictly later"):
        AgentIdentity.create(
            identity_id="agent-alpha",
            controller_public_key=public,
            manifest_version=1,
            issued_at=NOW,
            expires_at=NOW,
        )
    with pytest.raises(IdentityError, match="expires_at must be strictly later"):
        sign_attestation(_identity(public), seed, issued_at=LATER, expires_at=NOW)


def test_expired_attestation_fails_closed():
    seed, public = generate_ed25519_keypair()
    att = _signed(_identity(public), seed)
    with pytest.raises(IdentityError, match="expired"):
        verify_attestation_signature(att, clock=FixedClock(LATER + timedelta(seconds=1)))
    result = verify_report_binding(
        att,
        evaluate(CLEAN_TEXT),
        clock=FixedClock(LATER + timedelta(seconds=1)),
    )
    assert result.verdict == "expired"
    assert result.verdict not in ("accept", "revise", "refuse")


def test_replay_and_current_trust_semantics():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public, version=1)
    att = _signed(identity, seed)
    trust = TrustContext.from_identity(identity)
    verify_attestation(att, trust=trust, clock=FixedClock(NOW))
    future = sign_attestation(
        identity, seed, issued_at=NOW + timedelta(minutes=10), expires_at=LATER
    )
    with pytest.raises(IdentityError, match="not yet valid"):
        verify_attestation(future, trust=trust, clock=FixedClock(NOW))
    newer = AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=public,
        manifest_version=2,
        issued_at=NOW,
        expires_at=LATER,
    )
    advanced = TrustContext.from_identity(newer)
    with pytest.raises(IdentityError, match="not current|superseded|replay"):
        verify_attestation(att, trust=advanced, clock=FixedClock(NOW))
    report = evaluate(CLEAN_TEXT)
    bound = _signed(identity, seed, binding=bind_report(report))
    result = verify_report_binding(bound, report, trust=advanced, clock=FixedClock(NOW))
    assert result.verdict == "untrusted_signer"


def test_name_record_snapshot_is_local_only():
    seed, public = generate_ed25519_keypair()
    key = encode_public_key(public)
    record = NameRecordSnapshot.from_dict(
        {
            "schema_id": "ai4.identity.name_record.v1",
            "name": "agent-alpha.ai4",
            "subject_id": "agent-alpha",
            "controller_public_key": key,
            "captured_at": "2026-09-08T12:00:00Z",
            "source": "local_snapshot",
        }
    )
    identity = _identity(public, names=(record,))
    verify_attestation_signature(_signed(identity, seed), clock=FixedClock(NOW))
    raw = record.to_dict()
    raw["source"] = "unstoppable"
    with pytest.raises(IdentityError, match="local_snapshot"):
        NameRecordSnapshot.from_dict(raw)
    extra = record.to_dict()
    extra["wallet"] = "0x00"
    with pytest.raises(IdentityError, match="Unknown name_record field"):
        NameRecordSnapshot.from_dict(extra)


def test_sign_and_verify_round_trip_offline():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    att = _signed(identity, seed)
    verified = verify_attestation(att, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW))
    assert verified.identity.identity_id == "agent-alpha"
    assert verified.manifest_hash == identity.manifest_hash()
    assert verified.signature_algorithm == "ed25519"


def test_bind_and_verify_report_matched():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    report = evaluate(CLEAN_TEXT)
    binding = bind_report(report)
    att = _signed(identity, seed, binding=binding)
    result = verify_report_binding(
        att, report, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW)
    )
    assert result.verdict == "matched"
    assert result.report_hash == binding.report_hash
    assert isinstance(result, BindingResult)
    assert "accept" not in result.to_dict().values()


def test_wrong_report_hash_fails_closed_as_mismatch():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    report = evaluate(CLEAN_TEXT)
    other = evaluate("Just get over it. Nobody cares.")
    att = _signed(identity, seed, binding=bind_report(report))
    result = verify_report_binding(att, other, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW))
    assert result.verdict == "mismatch"
    assert "wrong report hash" in result.detail


def test_claim_mismatch_versus_bound_report_fails():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    report = evaluate(CLEAN_TEXT)
    binding = bind_report(report)
    mutated = ClaimedProfile.from_dict(
        {
            **binding.claimed_profile.to_dict(),
            "evidence_class": "identity_won",
        }
    )
    att = _signed(identity, seed, binding={"report_hash": binding.report_hash, "claimed_profile": mutated})
    result = verify_report_binding(
        att, report, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW)
    )
    assert result.verdict == "mismatch"
    assert "claim mismatch" in result.detail
    for field, value in (
        ("rubric_set", "v9.9"),
        ("evaluator_id", "llm-judge-v2"),
        ("runtime_version", "9.9.9"),
        ("arbitration", "off"),
        ("condition", "C"),
    ):
        profile = ClaimedProfile.from_dict({**binding.claimed_profile.to_dict(), field: value})
        att = _signed(
            identity,
            seed,
            binding={"report_hash": binding.report_hash, "claimed_profile": profile},
        )
        verdict = verify_report_binding(
            att, report, trust=TrustContext.from_identity(identity), clock=FixedClock(NOW)
        )
        assert verdict.verdict == "mismatch", field


def test_unbound_attestation_verdict():
    seed, public = generate_ed25519_keypair()
    att = _signed(_identity(public), seed)
    result = verify_report_binding(att, evaluate(CLEAN_TEXT), clock=FixedClock(NOW))
    assert result.verdict == "unbound"
    assert verify_report_binding(None, evaluate(CLEAN_TEXT)).verdict == "unbound"


def test_manifest_uri_cannot_override_hash_integrity():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public, uri="https://example.invalid/manifest.json")
    att = _signed(identity, seed)
    verify_attestation_signature(att, clock=FixedClock(NOW))
    raw = att.to_dict()
    raw["identity"]["manifest_uri"] = "https://evil.example/other.json"
    with pytest.raises(IdentityError, match="wrong manifest hash|signature"):
        verify_attestation_signature(raw, clock=FixedClock(NOW))
    raw = att.to_dict()
    raw["manifest_hash"] = "cd" * 32
    with pytest.raises(IdentityError, match="wrong manifest hash"):
        verify_attestation_signature(raw, clock=FixedClock(NOW))


def test_rotation_signed_by_old_key_advances_single_controller():
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
    old_trust = TrustContext.from_identity(previous)
    advanced = verify_rotation(rotation, old_trust, successor=successor, clock=FixedClock(NOW))
    assert advanced.identity_id == "agent-alpha"
    assert advanced.controller_public_key == successor.controller_public_key
    assert advanced.manifest_version == 2
    assert advanced.manifest_hash == successor.manifest_hash()
    assert advanced.manifest_hash != ""
    att = _signed(successor, new_seed, rotation=rotation)
    verify_attestation(att, trust=old_trust, clock=FixedClock(NOW))
    with pytest.raises(IdentityError, match="not current|superseded|controller"):
        verify_attestation(_signed(previous, old_seed), trust=TrustContext.from_identity(successor), clock=FixedClock(NOW))
    with pytest.raises(IdentityError, match="monotonic"):
        AgentIdentity.create(
            identity_id="agent-alpha",
            controller_public_key=new_pub,
            manifest_version=1,
            issued_at=NOW,
            expires_at=LATER,
        )
        RotationAttestation.from_dict({**rotation.to_dict(), "new_manifest_version": 1})


def test_rotation_not_signed_by_old_key_fails_closed():
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
    with pytest.raises(IdentityError, match="previous private key"):
        sign_rotation(
            previous_identity=previous,
            new_identity=successor,
            previous_private_key=new_seed,
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
    raw = rotation.to_dict()
    raw["signature"] = encode_signature(b"\x11" * 64)
    with pytest.raises(IdentityError, match="invalid"):
        verify_rotation(RotationAttestation.from_dict(raw), TrustContext.from_identity(previous), clock=FixedClock(NOW))


def test_binding_verdicts_never_include_constraint_decisions():
    from ai4.identity.binding import BINDING_VERDICTS

    assert BINDING_VERDICTS == ("matched", "unbound", "mismatch", "expired", "untrusted_signer")
    assert "accept" not in BINDING_VERDICTS
    assert "revise" not in BINDING_VERDICTS
    assert "refuse" not in BINDING_VERDICTS


def test_evidence_class_constant_unchanged_by_identity():
    assert EVIDENCE_CLASS == "null_retained_D_adds_cost"
    report = evaluate(CLEAN_TEXT)
    assert report.versions.evidence_class == "null_retained_D_adds_cost"
    binding = bind_report(report)
    assert binding.claimed_profile.evidence_class == "null_retained_D_adds_cost"


def test_injected_verifier_is_used(monkeypatch):
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    att = _signed(identity, seed)
    calls = {"n": 0}

    class Reject:
        def verify(self, public_key, message, signature):
            calls["n"] += 1
            return False

        def sign(self, private_key, message):
            raise AssertionError("sign must not be called")

        def public_key_bytes(self, private_key):
            return public

    with pytest.raises(IdentityError, match="signature|controller"):
        verify_attestation_signature(att, clock=FixedClock(NOW), verifier=Reject())
    assert calls["n"] == 1
    assert isinstance(LocalEd25519(), LocalEd25519)


def test_report_schema_has_no_signature_fields():
    report = evaluate(CLEAN_TEXT)
    payload = report.to_dict()
    assert "signature" not in payload
    assert "attestation" not in payload
    assert "controller_public_key" not in payload
    assert "manifest_hash" not in payload
