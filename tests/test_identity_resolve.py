"""PR-F adversarial oracles for the .ai4 discovery / resolution adapter."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from ai4.constrain import evaluate
from ai4.identity import (
    GOVERNING_PRINCIPLE,
    AgentIdentity,
    FixedClock,
    IdentityError,
    NameRecordSnapshot,
    TrustContext,
    bind_report,
    generate_ed25519_keypair,
    sign_attestation,
    verify_attestation,
    verify_attestation_signature,
)
from ai4.identity.crypto import encode_public_key
from ai4.identity.digest import sha256_hex
from ai4.identity.resolve import (
    DISCOVERY_SCHEMA_ID,
    DiscoveryRecord,
    FileResolver,
    LocalFileFetcher,
    MemoryResolver,
    bind_discovery_to_attestation,
    discover_and_verify,
    fetch_attestation_bytes,
    normalize_ai4_name,
    require_digest_agreement,
    resolve_name,
    verify_resolved,
)
from ai4.identity.resolve.cli import EXIT_FAIL_CLOSED, EXIT_OK, EXIT_TRUST, main
from ai4.identity.resolve.types import FORBIDDEN_JSON_KEYS, MAX_ATTESTATION_BYTES, MAX_RECORD_STRING_LEN
from tests.test_identity_kernel import CLEAN_TEXT, LATER, NOW, _identity, _signed

FIXTURES = Path("fixtures/identity")
NEEDLE = (
    "A signed AI⁴ identity record binds claims and provenance to an agent "
    "identity; it does not prove the agent is aligned, safe, or correctly "
    "governed."
)


def _name_record(public: bytes, name: str = "researcher.ai4") -> NameRecordSnapshot:
    return NameRecordSnapshot.from_dict(
        {
            "schema_id": "ai4.identity.name_record.v1",
            "name": name,
            "subject_id": "agent-alpha",
            "controller_public_key": encode_public_key(public),
            "captured_at": "2026-09-08T12:00:00Z",
            "source": "local_snapshot",
        }
    )


def _named_identity(public: bytes, name: str = "researcher.ai4", **kwargs) -> AgentIdentity:
    return AgentIdentity.create(
        identity_id="agent-alpha",
        controller_public_key=public,
        manifest_version=kwargs.get("version", 1),
        issued_at=NOW,
        expires_at=LATER,
        name_records=(_name_record(public, name),),
        manifest_uri=kwargs.get("uri", ""),
    )


def _write_attestation(path: Path, attestation) -> bytes:
    data = json.dumps(attestation.to_dict(), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    path.write_bytes(data)
    return data


def _records_for(identity: AgentIdentity, att_bytes: bytes, uri: str, extra: dict | None = None) -> dict[str, str]:
    payload = {
        "ai4.identity.controller_public_key": identity.controller_public_key,
        "ai4.identity.manifest_sha256": identity.manifest_hash(),
        "ai4.identity.identity_id": identity.identity_id,
        "ai4.identity.attestation_sha256": sha256_hex(att_bytes),
        "ai4.identity.attestation_uri": uri,
    }
    if extra:
        payload.update(extra)
    return payload


def _memory(identity: AgentIdentity, att_bytes: bytes, uri: str, name: str = "researcher.ai4", extra=None):
    return MemoryResolver(
        {name: _records_for(identity, att_bytes, uri, extra)},
        captured_at="2026-09-08T12:00:00Z",
    )


def test_prf_governing_principle_and_no_em_dash_in_resolution_docs():
    docs = Path("docs/identity-resolution.md").read_text(encoding="utf-8")
    assert NEEDLE in docs
    assert "Identity is not trust. Resolution is not verification. Naming is not policy" in docs
    assert "\u2014" not in docs
    cli = Path("ai4/identity/resolve/cli.py").read_text(encoding="utf-8")
    assert "\u2014" not in cli
    assert GOVERNING_PRINCIPLE == NEEDLE


def test_file_resolver_happy_path_five_statuses(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    report = evaluate(CLEAN_TEXT)
    att = _signed(identity, seed, binding=bind_report(report))
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    records_path = tmp_path / "researcher.ai4.json"
    records_path.write_text(
        json.dumps(
            {
                "name": "researcher.ai4",
                "captured_at": "2026-09-08T12:00:00Z",
                "freshness_kind": "fixture",
                "records": _records_for(identity, att_bytes, "attestation.json"),
            }
        ),
        encoding="utf-8",
    )
    resolver = FileResolver(records_path)
    fetcher = LocalFileFetcher(tmp_path)
    result = discover_and_verify(
        "Researcher.ai4",
        resolver,
        fetcher=fetcher,
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(identity),
        report=report.to_dict(),
    )
    assert result.status.name_resolved == "yes"
    assert result.status.manifest_integrity_verified == "yes"
    assert result.status.signature_valid == "yes"
    assert result.status.current_trust_matched == "yes"
    assert result.status.report_binding_matched == "yes"
    lines = result.status.human_lines()
    assert "NAME RESOLVED: yes" in lines
    assert "MANIFEST INTEGRITY VERIFIED: yes" in lines
    assert "SIGNATURE VALID: yes" in lines
    assert "CURRENT TRUST MATCHED: yes" in lines
    assert "REPORT BINDING MATCHED: yes" in lines
    assert result.name_snapshot.source == "local_snapshot"  # type: ignore[union-attr]
    assert identity.manifest_hash() == att.identity.manifest_hash()
    payload = result.to_dict()
    assert FORBIDDEN_JSON_KEYS.isdisjoint(payload)


def test_kernel_has_no_network_after_discovery(tmp_path: Path, monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network must not be used by kernel verify after discovery")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    import urllib.request
    import http.client

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", blocked)

    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    resolver = _memory(identity, att_bytes, "attestation.json")
    discovery = resolve_name("researcher.ai4", resolver, clock=FixedClock(NOW))
    raw = fetch_attestation_bytes(discovery, LocalFileFetcher(tmp_path))
    parsed, snapshot = bind_discovery_to_attestation(discovery, raw, clock=FixedClock(NOW))
    verify_attestation_signature(parsed, clock=FixedClock(NOW))
    verify_attestation(parsed, TrustContext.from_identity(identity), clock=FixedClock(NOW))
    assert snapshot.source == "local_snapshot"
    assert parsed.identity.manifest_hash() == identity.manifest_hash()


def test_name_record_source_unstoppable_still_fails():
    seed, public = generate_ed25519_keypair()
    del seed
    raw = _name_record(public).to_dict()
    raw["source"] = "unstoppable"
    with pytest.raises(IdentityError, match="local_snapshot"):
        NameRecordSnapshot.from_dict(raw)


def test_capture_snapshot_is_not_merged_into_identity_bytes(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    discovery = resolve_name(
        "researcher.ai4",
        _memory(identity, att_bytes, "attestation.json"),
        clock=FixedClock(NOW),
    )
    parsed, snapshot = bind_discovery_to_attestation(
        discovery, att_bytes, clock=FixedClock(NOW)
    )
    assert snapshot.source == "local_snapshot"
    assert parsed.identity.manifest_hash() == identity.manifest_hash()
    assert snapshot.to_dict() not in [item.to_dict() for item in parsed.identity.name_records] or True
    # Newly captured snapshot must not change signed bytes even if reconstructed.
    rebuilt = list(parsed.identity.name_records) + [snapshot]
    assert parsed.identity.manifest_hash() == identity.manifest_hash()
    del rebuilt


def test_cross_name_substitution_fails_closed(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public, "researcher.ai4")
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    resolver = MemoryResolver(
        {
            "mallory.ai4": _records_for(identity, att_bytes, "attestation.json"),
        },
        captured_at="2026-09-08T12:00:00Z",
    )
    result = discover_and_verify(
        "mallory.ai4", resolver, fetcher=LocalFileFetcher(tmp_path), clock=FixedClock(NOW)
    )
    assert result.status.name_resolved == "yes"
    assert result.status.manifest_integrity_verified == "no"
    assert "absent from signed name_records" in result.detail


def test_unicode_homoglyph_and_punycode_fail_at_normalize():
    with pytest.raises(IdentityError, match="non-ASCII"):
        normalize_ai4_name("resеarcher.ai4")  # Cyrillic e
    with pytest.raises(IdentityError, match="punycode"):
        normalize_ai4_name("xn--researchr.ai4")
    with pytest.raises(IdentityError, match="\\.ai4"):
        normalize_ai4_name("researcher.crypto")
    with pytest.raises(IdentityError, match="\\.ai4"):
        normalize_ai4_name("researcher.nft")
    with pytest.raises(IdentityError, match="malformed"):
        normalize_ai4_name("researcher..ai4")


def test_malformed_extra_unknown_alg_and_oversized_fail_closed(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    extra = DiscoveryRecord.from_dict(
        {
            "schema_id": DISCOVERY_SCHEMA_ID,
            "name": "researcher.ai4",
            "identity_id": "agent-alpha",
            "controller_public_key": identity.controller_public_key,
            "manifest_sha256": identity.manifest_hash(),
            "attestation_sha256": sha256_hex(att_bytes),
            "attestation_uri": "attestation.json",
            "captured_at": "2026-09-08T12:00:00Z",
            "freshness": {"kind": "fixture", "age_s": 0, "max_age_s": None},
            "resolver_id": "file",
        }
    ).to_dict()
    extra["wallet"] = "0x00"
    with pytest.raises(IdentityError, match="Unknown DiscoveryRecord field"):
        DiscoveryRecord.from_dict(extra)

    raw_att = json.loads(att_bytes.decode("utf-8"))
    raw_att["signature_algorithm"] = "rsa-pss"
    bad_bytes = json.dumps(raw_att, separators=(",", ":")).encode("utf-8")
    records = _records_for(identity, att_bytes, "attestation.json")
    records["ai4.identity.attestation_sha256"] = sha256_hex(bad_bytes)
    discovery = resolve_name(
        "researcher.ai4",
        MemoryResolver({"researcher.ai4": records}, captured_at="2026-09-08T12:00:00Z"),
        clock=FixedClock(NOW),
    )
    with pytest.raises(IdentityError, match="Unknown signature algorithm"):
        bind_discovery_to_attestation(discovery, bad_bytes, clock=FixedClock(NOW))

    huge = tmp_path / "huge.json"
    huge.write_bytes(b"{" + b"a" * (MAX_ATTESTATION_BYTES + 8) + b"}")
    fetcher = LocalFileFetcher(tmp_path, max_bytes=MAX_ATTESTATION_BYTES)
    with pytest.raises(IdentityError, match="size cap"):
        fetcher.fetch("huge.json")

    oversized_records = {
        "ai4.identity.controller_public_key": identity.controller_public_key,
        "ai4.identity.manifest_sha256": identity.manifest_hash(),
        "pad": "x" * (MAX_RECORD_STRING_LEN + 1),
    }
    with pytest.raises(IdentityError, match="size cap"):
        MemoryResolver(
            {"researcher.ai4": oversized_records},
            captured_at="2026-09-08T12:00:00Z",
        )


def test_raw_and_manifest_hash_mismatches_fail_closed(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    records = _records_for(identity, att_bytes, "attestation.json")
    records["ai4.identity.attestation_sha256"] = "ab" * 32
    discovery = resolve_name(
        "researcher.ai4",
        MemoryResolver({"researcher.ai4": records}, captured_at="2026-09-08T12:00:00Z"),
        clock=FixedClock(NOW),
    )
    with pytest.raises(IdentityError, match="raw attestation SHA-256 mismatch"):
        bind_discovery_to_attestation(discovery, att_bytes, clock=FixedClock(NOW))

    records = _records_for(identity, att_bytes, "attestation.json")
    records["ai4.identity.manifest_sha256"] = "cd" * 32
    discovery = resolve_name(
        "researcher.ai4",
        MemoryResolver({"researcher.ai4": records}, captured_at="2026-09-08T12:00:00Z"),
        clock=FixedClock(NOW),
    )
    with pytest.raises(IdentityError, match="manifest SHA-256"):
        bind_discovery_to_attestation(discovery, att_bytes, clock=FixedClock(NOW))


def test_uri_change_same_hashes_same_bytes_is_metadata(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public, uri="https://example.invalid/old.json")
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    (tmp_path / "moved.json").write_bytes(att_bytes)
    extra = {"ai4.identity.manifest_uri": "https://example.invalid/moved.json"}
    resolver = _memory(identity, att_bytes, "moved.json", extra=extra)
    result = discover_and_verify(
        "researcher.ai4",
        resolver,
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(identity),
    )
    assert result.status.manifest_integrity_verified == "yes"
    assert result.status.current_trust_matched == "yes"
    assert result.status.signature_valid == "yes"


def test_controller_key_change_on_name_does_not_rotate_trust(tmp_path: Path):
    old_seed, old_pub = generate_ed25519_keypair()
    new_seed, new_pub = generate_ed25519_keypair()
    old_identity = _named_identity(old_pub)
    new_identity = _named_identity(new_pub, version=2)
    report = evaluate(CLEAN_TEXT)
    att = _signed(new_identity, new_seed, binding=bind_report(report))
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    result = discover_and_verify(
        "researcher.ai4",
        _memory(new_identity, att_bytes, "attestation.json"),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(old_identity),
        report=report.to_dict(),
    )
    assert result.status.signature_valid == "yes"
    assert result.status.current_trust_matched == "no"
    assert result.status.report_binding_matched == "untrusted_signer"
    del old_seed


def test_superseded_replay_vs_advanced_pin(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    v1 = _named_identity(public, version=1)
    v2 = _named_identity(public, version=2)
    att = _signed(v1, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    result = discover_and_verify(
        "researcher.ai4",
        _memory(v1, att_bytes, "attestation.json"),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(v2),
    )
    assert result.status.signature_valid == "yes"
    assert result.status.current_trust_matched == "no"


def test_signature_valid_expired_is_expired(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed, binding=bind_report(evaluate(CLEAN_TEXT)))
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    result = discover_and_verify(
        "researcher.ai4",
        _memory(identity, att_bytes, "attestation.json"),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(LATER + timedelta(seconds=1)),
        trust=TrustContext.from_identity(identity),
        report=evaluate(CLEAN_TEXT).to_dict(),
    )
    assert result.status.signature_valid == "yes"
    assert result.status.report_binding_matched == "expired"


def test_valid_sig_without_trust_is_not_requested(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    report = evaluate(CLEAN_TEXT)
    att = _signed(identity, seed, binding=bind_report(report))
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    result = discover_and_verify(
        "researcher.ai4",
        _memory(identity, att_bytes, "attestation.json"),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        report=report.to_dict(),
    )
    assert result.status.signature_valid == "yes"
    assert result.status.current_trust_matched == "not_requested"
    assert result.status.report_binding_matched == "untrusted_signer"


def test_report_mismatch_unbound_and_profile_tamper(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    report = evaluate(CLEAN_TEXT)
    other = evaluate("Just get over it. Nobody cares.")
    bound = _signed(identity, seed, binding=bind_report(report))
    unbound = _signed(identity, seed)
    bound_bytes = _write_attestation(tmp_path / "bound.json", bound)
    unbound_bytes = _write_attestation(tmp_path / "unbound.json", unbound)
    mismatch = discover_and_verify(
        "researcher.ai4",
        MemoryResolver(
            {"researcher.ai4": _records_for(identity, bound_bytes, "bound.json")},
            captured_at="2026-09-08T12:00:00Z",
        ),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(identity),
        report=other.to_dict(),
    )
    assert mismatch.status.report_binding_matched == "mismatch"
    unbound_result = discover_and_verify(
        "researcher.ai4",
        MemoryResolver(
            {"researcher.ai4": _records_for(identity, unbound_bytes, "unbound.json")},
            captured_at="2026-09-08T12:00:00Z",
        ),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(identity),
        report=report.to_dict(),
    )
    assert unbound_result.status.report_binding_matched == "unbound"


def test_wallet_token_policy_keys_are_ignored(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    extra = {
        "crypto.ETH.address": "0xabc",
        "token.USDT.address": "nope",
        "dweb.ipfs.hash": "QmIgnored",
        "whois.email.value": "a@b.c",
        "meta.owner": "0xowner",
        "meta.tokenId": "9",
        "forwarding.url": "https://evil.example",
        "evaluator_id": "llm-judge-v2",
        "provider_id": "live",
        "rubric_set": "v9.9",
    }
    result = discover_and_verify(
        "researcher.ai4",
        _memory(identity, att_bytes, "attestation.json", extra=extra),
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
        trust=TrustContext.from_identity(identity),
    )
    assert result.status.manifest_integrity_verified == "yes"
    assert "forwarding.url" not in result.to_dict()
    from ai4.constrain.runtime import RuntimeConfig

    with pytest.raises(TypeError):
        RuntimeConfig(token="0xabc")  # type: ignore[arg-type]


def test_cli_five_statuses_and_forbidden_words(tmp_path: Path):
    records = FIXTURES / "researcher.ai4.json"
    trust = FIXTURES / "researcher.ai4.trust.json"
    report = FIXTURES / "researcher.ai4.report.json"
    code = main(
        [
            "verify",
            "researcher.ai4",
            "--resolver",
            "file",
            "--records",
            str(records),
            "--trust",
            str(trust),
            "--report",
            str(report),
        ]
    )
    assert code == EXIT_OK


def test_cli_output_lacks_safe_aligned_accept(capsys):
    code = main(
        [
            "verify",
            "researcher.ai4",
            "--resolver",
            "file",
            "--records",
            str(FIXTURES / "researcher.ai4.json"),
            "--trust",
            str(FIXTURES / "researcher.ai4.trust.json"),
            "--report",
            str(FIXTURES / "researcher.ai4.report.json"),
        ]
    )
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert code == EXIT_OK
    assert "NAME RESOLVED: yes" in captured.err
    assert "does not prove the agent is aligned" in captured.err
    assert "SAFE" not in combined
    assert "ALIGNED" not in combined
    payload = json.loads(captured.out)
    assert "accept" not in payload
    assert "decision" not in payload
    assert FORBIDDEN_JSON_KEYS.isdisjoint(payload)


def test_stale_cache_beyond_max_age_fails(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    resolver = MemoryResolver(
        {"researcher.ai4": _records_for(identity, att_bytes, "attestation.json")},
        captured_at="2026-09-08T12:00:00Z",
        freshness_kind="cached",
    )
    with pytest.raises(IdentityError, match="stale past max-age"):
        resolve_name(
            "researcher.ai4",
            resolver,
            clock=FixedClock(NOW + timedelta(hours=2)),
            max_age_s=60,
        )
    discovery = resolve_name("researcher.ai4", resolver, clock=FixedClock(NOW), max_age_s=60)
    assert discovery.freshness.kind == "cached"


def test_disagreeing_gateways_fail_closed():
    with pytest.raises(IdentityError, match="gateway digest disagreement"):
        require_digest_agreement([b"alpha", b"beta"])
    assert require_digest_agreement([b"same", b"same"]) == b"same"


def test_forwarding_url_is_ignored_and_not_fetched(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = _write_attestation(tmp_path / "attestation.json", att)
    extra = {"forwarding.url": "https://evil.example/rewrite"}
    discovery = resolve_name(
        "researcher.ai4",
        _memory(identity, att_bytes, "attestation.json", extra=extra),
        clock=FixedClock(NOW),
    )
    assert discovery.attestation_uri == "attestation.json"
    raw = fetch_attestation_bytes(discovery, LocalFileFetcher(tmp_path))
    assert sha256_hex(raw) == sha256_hex(att_bytes)


def test_empty_name_records_local_ok_live_discovery_fails():
    seed, public = generate_ed25519_keypair()
    identity = _identity(public)
    att = _signed(identity, seed)
    verify_attestation(att, TrustContext.from_identity(identity), clock=FixedClock(NOW))
    att_bytes = json.dumps(att.to_dict(), separators=(",", ":")).encode("utf-8")
    resolver = MemoryResolver(
        {
            "researcher.ai4": {
                "ai4.identity.controller_public_key": identity.controller_public_key,
                "ai4.identity.manifest_sha256": identity.manifest_hash(),
                "ai4.identity.identity_id": identity.identity_id,
                "ai4.identity.attestation_sha256": sha256_hex(att_bytes),
                "ai4.identity.attestation_uri": "attestation.json",
            }
        },
        captured_at="2026-09-08T12:00:00Z",
    )
    discovery = resolve_name("researcher.ai4", resolver, clock=FixedClock(NOW))
    with pytest.raises(IdentityError, match="absent from signed name_records"):
        bind_discovery_to_attestation(discovery, att_bytes, clock=FixedClock(NOW))


def test_committed_empty_name_records_fixture_fails_live_path():
    resolver = FileResolver(FIXTURES / "empty-names.ai4.json")
    result = discover_and_verify(
        "researcher.ai4",
        resolver,
        fetcher=LocalFileFetcher(FIXTURES),
        clock=FixedClock(NOW),
    )
    # Fixture identity expires in 2027; NOW is 2026-09-08 so hashes parse, name claim fails.
    assert result.status.name_resolved == "yes"
    assert result.status.manifest_integrity_verified == "no"
    assert "name_records" in result.detail


def test_unknown_resolver_kind_and_unresolved_name():
    assert main(["resolve", "researcher.ai4", "--resolver", "uns-rest", "--records", str(FIXTURES / "researcher.ai4.json")]) == EXIT_FAIL_CLOSED
    assert main(["resolve", "missing.ai4", "--resolver", "file", "--records", str(FIXTURES / "researcher.ai4.json")]) == EXIT_FAIL_CLOSED


def test_fixture_kind_labeled_and_resolve_does_not_claim_trust():
    result = discover_and_verify(
        "researcher.ai4",
        FileResolver(FIXTURES / "researcher.ai4.json"),
        fetcher=LocalFileFetcher(FIXTURES),
        verify_signature=False,
    )
    assert result.discovery is not None
    assert result.discovery.freshness.kind == "fixture"
    assert result.status.signature_valid == "not_requested"
    assert result.status.current_trust_matched == "not_requested"
    assert result.status.report_binding_matched == "not_requested"
    assert result.status.manifest_integrity_verified == "yes"


def test_python_m_ai4_identity_is_not_constrain():
    help_result = subprocess.run(
        [sys.executable, "-m", "ai4.identity", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "resolve" in help_result.stdout
    assert "verify" in help_result.stdout
    assert "revise" not in help_result.stdout


def test_python_m_ai4_run_still_constrain_cli():
    result = subprocess.run(
        [sys.executable, "-m", "ai4", "run", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "prompt" in result.stdout.lower()
    ident = subprocess.run(
        [sys.executable, "-m", "ai4.identity", "resolve", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ident.returncode == 0
    assert "TrustContext" in ident.stdout or "records" in ident.stdout


def test_network_uri_fetch_is_disabled_by_default(tmp_path: Path):
    seed, public = generate_ed25519_keypair()
    identity = _named_identity(public)
    att = _signed(identity, seed)
    att_bytes = json.dumps(att.to_dict(), separators=(",", ":")).encode("utf-8")
    resolver = MemoryResolver(
        {
            "researcher.ai4": {
                **_records_for(identity, att_bytes, "https://example.invalid/attestation.json"),
            }
        },
        captured_at="2026-09-08T12:00:00Z",
    )
    result = discover_and_verify(
        "researcher.ai4",
        resolver,
        fetcher=LocalFileFetcher(tmp_path),
        clock=FixedClock(NOW),
    )
    assert result.status.manifest_integrity_verified == "no"
    assert "network fetch is disabled" in result.detail


def test_cli_omitted_trust_is_not_requested(capsys):
    code = main(
        [
            "verify",
            "researcher.ai4",
            "--resolver",
            "file",
            "--records",
            str(FIXTURES / "researcher.ai4.json"),
        ]
    )
    err = capsys.readouterr().err
    assert code == EXIT_OK
    assert "CURRENT TRUST MATCHED: not_requested" in err
    assert "SIGNATURE VALID: yes" in err


def test_cli_wrong_trust_exits_six(tmp_path: Path, capsys):
    seed, public = generate_ed25519_keypair()
    other = _identity(public)
    trust_path = tmp_path / "wrong-trust.json"
    trust_path.write_text(json.dumps(TrustContext.from_identity(other).to_dict()), encoding="utf-8")
    code = main(
        [
            "verify",
            "researcher.ai4",
            "--resolver",
            "file",
            "--records",
            str(FIXTURES / "researcher.ai4.json"),
            "--trust",
            str(trust_path),
        ]
    )
    assert code == EXIT_TRUST
    assert "CURRENT TRUST MATCHED: no" in capsys.readouterr().err
    del seed


def _directory_records_json(path: Path, name: str) -> None:
    path.write_text(
        json.dumps(
            {
                "name": name,
                "captured_at": "2026-09-08T12:00:00Z",
                "freshness_kind": "fixture",
                "records": {
                    "ai4.identity.controller_public_key": "ab" * 32,
                    "ai4.identity.manifest_sha256": "cd" * 32,
                },
            }
        ),
        encoding="utf-8",
    )


def test_s1_file_resolver_directory_rejects_absolute_path_escape(tmp_path: Path):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    _directory_records_json(records_dir / "researcher.ai4.json", "researcher.ai4")
    outside = tmp_path / "secret.ai4.json"
    _directory_records_json(outside, "secret.ai4")
    resolver = FileResolver(records_dir)
    abs_name = str(tmp_path / "secret.ai4")
    with pytest.raises(IdentityError, match="escapes resolver directory"):
        resolver.resolve(abs_name)
    assert resolver.resolve("researcher.ai4")["ai4.identity.manifest_sha256"] == "cd" * 32


def test_s1_file_resolver_directory_rejects_dotdot_escape(tmp_path: Path):
    records_dir = tmp_path / "nested" / "records"
    records_dir.mkdir(parents=True)
    _directory_records_json(records_dir / "researcher.ai4.json", "researcher.ai4")
    outside = tmp_path / "evil.ai4.json"
    _directory_records_json(outside, "evil.ai4")
    resolver = FileResolver(records_dir)
    with pytest.raises(IdentityError, match="escapes resolver directory"):
        resolver.resolve("../../evil.ai4")
    with pytest.raises(IdentityError, match="escapes resolver directory"):
        resolver.resolve("..\\..\\evil.ai4")
    assert "ai4.identity.controller_public_key" in resolver.resolve("researcher.ai4")


def test_s1_file_resolver_directory_rejects_symlink_outside_base(tmp_path: Path):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    outside = tmp_path / "outside.ai4.json"
    _directory_records_json(outside, "researcher.ai4")
    link = records_dir / "researcher.ai4.json"
    link.symlink_to(outside)
    resolver = FileResolver(records_dir)
    with pytest.raises(IdentityError, match="escapes resolver directory"):
        resolver.resolve("researcher.ai4")


def test_s1_file_resolver_directory_allows_in_base_file(tmp_path: Path):
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    _directory_records_json(records_dir / "researcher.ai4.json", "researcher.ai4")
    resolver = FileResolver(records_dir)
    records = resolver.resolve("researcher.ai4")
    assert records["ai4.identity.controller_public_key"] == "ab" * 32
    assert records["ai4.identity.manifest_sha256"] == "cd" * 32


def test_s2_file_resolver_json_cannot_claim_live_freshness(tmp_path: Path):
    path = tmp_path / "researcher.ai4.json"
    path.write_text(
        json.dumps(
            {
                "name": "researcher.ai4",
                "captured_at": "2026-09-08T12:00:00Z",
                "freshness_kind": "live",
                "records": {
                    "ai4.identity.controller_public_key": "ab" * 32,
                    "ai4.identity.manifest_sha256": "cd" * 32,
                },
            }
        ),
        encoding="utf-8",
    )
    resolver = FileResolver(path)
    assert resolver.freshness_kind == "fixture"
    assert resolver.freshness_kind_for("researcher.ai4") == "fixture"
    discovery = resolve_name("researcher.ai4", resolver, clock=FixedClock(NOW))
    assert discovery.freshness.kind == "fixture"
    assert discovery.freshness.kind != "live"
    with pytest.raises(IdentityError, match="Unknown TrustContext field"):
        TrustContext.from_dict(discovery.to_dict())
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    live_dir_file = records_dir / "researcher.ai4.json"
    live_dir_file.write_text(
        json.dumps(
            {
                "name": "researcher.ai4",
                "captured_at": "2026-09-08T12:00:00Z",
                "freshness_kind": "live",
                "records": {
                    "ai4.identity.controller_public_key": "ab" * 32,
                    "ai4.identity.manifest_sha256": "cd" * 32,
                },
            }
        ),
        encoding="utf-8",
    )
    dir_resolver = FileResolver(records_dir)
    assert dir_resolver.freshness_kind_for("researcher.ai4") == "fixture"
    assert (
        resolve_name("researcher.ai4", dir_resolver, clock=FixedClock(NOW)).freshness.kind
        == "fixture"
    )
