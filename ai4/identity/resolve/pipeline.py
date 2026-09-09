"""Honest discovery pipeline. Resolution is not verification.

.ai4 name -> Resolver -> DiscoveryRecord -> fetch bytes -> SHA-256 checks
-> parse AgentAttestation -> NameRecordSnapshot(source=local_snapshot)
-> existing kernel verify_*.

Does not write the capture snapshot back into the signed identity.
Does not auto-build TrustContext from resolver or name records.
Does not fetch identity.manifest_uri. Does not follow forwarding.url.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from ai4.identity.attestation import verify_attestation, verify_attestation_signature
from ai4.identity.binding import verify_report_binding
from ai4.identity.crypto import decode_public_key_hex, encode_public_key
from ai4.identity.digest import sha256_hex
from ai4.identity.errors import IdentityError
from ai4.identity.resolve.fetch import Fetcher, fetch_attestation_bytes as _fetch_bytes
from ai4.identity.resolve.file_resolver import FileResolver
from ai4.identity.resolve.resolver import Resolver, validate_raw_records
from ai4.identity.resolve.types import (
    INTEGRITY_REQUIRED_KEYS,
    KNOWN_RECORD_KEYS,
    RECORD_ATTESTATION_SHA256,
    RECORD_ATTESTATION_URI,
    RECORD_CONTROLLER_KEY,
    RECORD_IDENTITY_ID,
    RECORD_MANIFEST_SHA256,
    RECORD_MANIFEST_URI,
    DiscoveryRecord,
    ResolveResult,
    Status,
)
from ai4.identity.schemas import (
    NAME_RECORD_SCHEMA_ID,
    NAME_RECORD_SOURCE,
    AgentAttestation,
    NameRecordSnapshot,
    require_identity_id,
    require_sha256_hex,
)
from ai4.identity.timeutil import Clock, SystemClock, format_utc, parse_utc, require_aware_utc
from ai4.identity.trust import TrustContext

_KERNEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_AI4_TLD = "ai4"


def normalize_ai4_name(name: str) -> str:
    """ASCII lowercase, must match kernel name regex and end with .ai4."""
    if not isinstance(name, str) or not name:
        raise IdentityError("name must be a non-empty string")
    try:
        name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise IdentityError("non-ASCII .ai4 names are rejected") from exc
    lowered = name.lower()
    if "xn--" in lowered:
        raise IdentityError("punycode xn-- names are rejected")
    if any(ord(ch) > 127 for ch in name):
        raise IdentityError("Unicode homoglyph .ai4 names are rejected")
    if not lowered.endswith(".ai4"):
        raise IdentityError("name must end with .ai4; other TLDs are rejected")
    if not _KERNEL_NAME_RE.fullmatch(lowered):
        raise IdentityError("malformed .ai4 name")
    labels = lowered.split(".")
    if any(label == "" for label in labels):
        raise IdentityError("malformed .ai4 name")
    if labels[-1] != _AI4_TLD:
        raise IdentityError("non-.ai4 TLD")
    return lowered


def resolve_name(
    name: str,
    resolver: Resolver,
    *,
    clock: Clock | None = None,
    max_age_s: int | None = None,
) -> DiscoveryRecord:
    """Untrusted naming lookup. Never returns TrustContext. Never calls verify_*."""
    normalized = normalize_ai4_name(name)
    when = require_aware_utc((clock or SystemClock()).now())
    records = resolver.resolve(normalized)
    validate_raw_records(records)
    captured_at = _resolver_captured_at(resolver, normalized, when)
    kind = _resolver_freshness_kind(resolver)
    resolver_id = str(getattr(resolver, "resolver_id", "") or "")
    if hasattr(resolver, "freshness_kind_for"):
        kind = str(resolver.freshness_kind_for(normalized))
    discovery = discovery_from_records(
        normalized,
        records,
        captured_at=captured_at,
        freshness_kind=kind,
        resolver_id=resolver_id,
        now=when,
        max_age_s=max_age_s,
    )
    return discovery


def discovery_from_records(
    name: str,
    records: Mapping[str, str],
    *,
    captured_at: str,
    freshness_kind: str,
    resolver_id: str,
    now: datetime,
    max_age_s: int | None = None,
) -> DiscoveryRecord:
    """Schema-validate adapter keys. Ignore wallet/token/meta/forwarding/policy keys."""
    normalized = normalize_ai4_name(name)
    missing = [key for key in INTEGRITY_REQUIRED_KEYS if not records.get(key)]
    if missing:
        raise IdentityError(f"resolver records missing integrity-critical key(s) {missing}")
    identity_id_raw = records.get(RECORD_IDENTITY_ID, "")
    identity_id = require_identity_id(identity_id_raw) if identity_id_raw else ""
    attestation_sha = records.get(RECORD_ATTESTATION_SHA256, "")
    if attestation_sha:
        attestation_sha = require_sha256_hex(attestation_sha, field="attestation_sha256")
    # Locative only; never used to override hashes.
    _ = records.get(RECORD_MANIFEST_URI, "")
    captured = format_utc(captured_at)
    captured_dt = parse_utc(captured)
    if captured_dt > now:
        raise IdentityError("discovery captured_at is in the future")
    age_s = int((now - captured_dt).total_seconds())
    if max_age_s is not None:
        if max_age_s < 0:
            raise IdentityError("max_age_s must be >= 0")
        if age_s > max_age_s:
            raise IdentityError("discovery record is stale past max-age")
    return DiscoveryRecord.from_dict(
        {
            "schema_id": "ai4.identity.discovery.v1",
            "name": normalized,
            "identity_id": identity_id,
            "controller_public_key": encode_public_key(
                decode_public_key_hex(records[RECORD_CONTROLLER_KEY])
            ),
            "manifest_sha256": require_sha256_hex(
                records[RECORD_MANIFEST_SHA256], field="manifest_sha256"
            ),
            "attestation_sha256": attestation_sha,
            "attestation_uri": records.get(RECORD_ATTESTATION_URI, ""),
            "captured_at": captured,
            "freshness": {
                "kind": freshness_kind,
                "age_s": age_s,
                "max_age_s": max_age_s,
            },
            "resolver_id": resolver_id,
        }
    )


def fetch_attestation_bytes(
    discovery: DiscoveryRecord,
    fetcher: Fetcher,
    *,
    extra_fetchers: Sequence[Fetcher] = (),
) -> bytes:
    """Network/file fetch. Fail closed on size, type, missing URI."""
    if discovery.attestation_uri.lower().startswith("forwarding"):
        raise IdentityError("forwarding.url must not be fetched as identity records")
    return _fetch_bytes(
        discovery.attestation_uri,
        fetcher,
        extra_fetchers=extra_fetchers,
    )


def bind_discovery_to_attestation(
    discovery: DiscoveryRecord,
    raw_bytes: bytes,
    *,
    clock: Clock | None = None,
) -> tuple[AgentAttestation, NameRecordSnapshot]:
    """SHA-256 checks, parse via AgentAttestation.from_dict, local_snapshot capture."""
    if discovery.attestation_sha256:
        actual = sha256_hex(raw_bytes)
        if actual != discovery.attestation_sha256:
            raise IdentityError("raw attestation SHA-256 mismatch")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityError(f"malformed attestation bytes: {exc}") from exc
    attestation = AgentAttestation.from_dict(payload)
    identity = attestation.identity
    recomputed = identity.manifest_hash()
    if recomputed != discovery.manifest_sha256:
        raise IdentityError("parsed identity manifest SHA-256 does not match published hash")
    if attestation.manifest_hash != discovery.manifest_sha256:
        raise IdentityError("attestation.manifest_hash does not match published hash")
    if identity.controller_public_key != discovery.controller_public_key:
        raise IdentityError("published controller public key does not match identity")
    if discovery.identity_id and discovery.identity_id != identity.identity_id:
        raise IdentityError("published identity_id does not match identity")
    claimed = {record.name for record in identity.name_records}
    if discovery.name not in claimed:
        raise IdentityError(
            "queried .ai4 name is absent from signed name_records; "
            "cross-name substitution is rejected"
        )
    when = require_aware_utc((clock or SystemClock()).now())
    snapshot = NameRecordSnapshot.from_dict(
        {
            "schema_id": NAME_RECORD_SCHEMA_ID,
            "name": discovery.name,
            "subject_id": identity.identity_id,
            "controller_public_key": identity.controller_public_key,
            "captured_at": format_utc(when),
            "source": NAME_RECORD_SOURCE,
        }
    )
    # Do not write this snapshot back into the signed identity.
    if identity.manifest_hash() != recomputed:
        raise IdentityError("capture snapshot mutated identity bytes")
    return attestation, snapshot


def verify_resolved(
    attestation: AgentAttestation,
    *,
    trust: TrustContext | None = None,
    report: object | None = None,
    clock: Clock | None = None,
    discovery: DiscoveryRecord | None = None,
    name_snapshot: NameRecordSnapshot | None = None,
) -> ResolveResult:
    """Calls existing verify_attestation_signature / verify_attestation / verify_report_binding."""
    impl_clock = clock or SystemClock()
    signature_valid: str = "no"
    current_trust: str = "not_requested" if trust is None else "no"
    report_binding: str = "not_requested" if report is None else "no"
    binding_verdict = ""
    detail = ""

    try:
        verify_attestation_signature(attestation, clock=impl_clock)
        signature_valid = "yes"
    except IdentityError as exc:
        message = str(exc)
        detail = message
        if "expired" in message or "not yet valid" in message:
            signature_valid = "yes"
            if report is not None:
                report_binding = "expired"
                binding_verdict = "expired"
            return ResolveResult(
                status=Status(
                    "yes",
                    "yes",
                    signature_valid,  # type: ignore[arg-type]
                    current_trust,  # type: ignore[arg-type]
                    report_binding,  # type: ignore[arg-type]
                ),
                detail=detail,
                discovery=discovery,
                attestation=attestation,
                name_snapshot=name_snapshot,
                binding_verdict=binding_verdict,
            )
        if report is not None:
            report_binding = "untrusted_signer"
            binding_verdict = "untrusted_signer"
        return ResolveResult(
            status=Status(
                "yes",
                "yes",
                "no",
                current_trust,  # type: ignore[arg-type]
                report_binding,  # type: ignore[arg-type]
            ),
            detail=detail,
            discovery=discovery,
            attestation=attestation,
            name_snapshot=name_snapshot,
            binding_verdict=binding_verdict,
        )

    if trust is not None:
        try:
            verify_attestation(attestation, trust, clock=impl_clock)
            current_trust = "yes"
        except IdentityError as exc:
            current_trust = "no"
            detail = str(exc)

    if report is not None:
        binding = verify_report_binding(
            attestation, report, trust=trust, clock=impl_clock
        )
        binding_verdict = binding.verdict
        report_binding = "yes" if binding.verdict == "matched" else binding.verdict
        if binding.verdict != "matched" and not detail:
            detail = binding.detail

    if not detail:
        detail = "discovery integrity checks passed"
    return ResolveResult(
        status=Status(
            "yes",
            "yes",
            "yes",
            current_trust,  # type: ignore[arg-type]
            report_binding,  # type: ignore[arg-type]
        ),
        detail=detail,
        discovery=discovery,
        attestation=attestation,
        name_snapshot=name_snapshot,
        binding_verdict=binding_verdict,
    )


def discover_and_verify(
    name: str,
    resolver: Resolver,
    *,
    fetcher: Fetcher | None = None,
    clock: Clock | None = None,
    max_age_s: int | None = None,
    trust: TrustContext | None = None,
    report: object | None = None,
    extra_fetchers: Sequence[Fetcher] = (),
    verify_signature: bool = True,
) -> ResolveResult:
    """Compose lookup, fetch, integrity, and optional kernel verify into one result."""
    impl_clock = clock or SystemClock()
    try:
        discovery = resolve_name(name, resolver, clock=impl_clock, max_age_s=max_age_s)
    except IdentityError as exc:
        return ResolveResult(
            status=_blank_status(trust, report, name_resolved="no"),
            detail=str(exc),
        )
    if fetcher is None:
        return ResolveResult(
            status=Status("yes", "no", "not_requested", "not_requested", "not_requested"),
            detail="name resolved; attestation fetch not requested",
            discovery=discovery,
        )
    try:
        raw = fetch_attestation_bytes(
            discovery, fetcher, extra_fetchers=extra_fetchers
        )
        attestation, snapshot = bind_discovery_to_attestation(
            discovery, raw, clock=impl_clock
        )
    except IdentityError as exc:
        return ResolveResult(
            status=Status(
                "yes",
                "no",
                "not_requested" if not verify_signature else "no",
                "not_requested" if trust is None else "no",
                "not_requested" if report is None else "no",
            ),
            detail=str(exc),
            discovery=discovery,
        )
    if not verify_signature:
        return ResolveResult(
            status=Status("yes", "yes", "not_requested", "not_requested", "not_requested"),
            detail="name resolved; manifest integrity verified; signature not requested",
            discovery=discovery,
            attestation=attestation,
            name_snapshot=snapshot,
        )
    return verify_resolved(
        attestation,
        trust=trust,
        report=report,
        clock=impl_clock,
        discovery=discovery,
        name_snapshot=snapshot,
    )


def file_resolver_from_path(records_path: str | Path, *, captured_at: str | None = None) -> FileResolver:
    return FileResolver(records_path, captured_at=captured_at)


def known_record_keys() -> frozenset[str]:
    return KNOWN_RECORD_KEYS


def _resolver_captured_at(resolver: Resolver, name: str, now: datetime) -> str:
    if hasattr(resolver, "captured_at_for"):
        return format_utc(resolver.captured_at_for(name))
    captured = getattr(resolver, "captured_at", None)
    if isinstance(captured, str) and captured:
        return format_utc(captured)
    return format_utc(now.replace(tzinfo=now.tzinfo or timezone.utc))


def _resolver_freshness_kind(resolver: Resolver) -> str:
    kind = getattr(resolver, "freshness_kind", "fixture")
    if kind not in ("live", "cached", "fixture"):
        raise IdentityError(f"Unknown freshness.kind {kind!r}")
    return str(kind)


def _blank_status(
    trust: TrustContext | None,
    report: object | None,
    *,
    name_resolved: str,
) -> Status:
    return Status(
        name_resolved,  # type: ignore[arg-type]
        "no",
        "no" if name_resolved == "no" else "not_requested",
        "not_requested" if trust is None else "no",
        "not_requested" if report is None else "no",
    )
