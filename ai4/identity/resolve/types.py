"""Discovery types. Untrusted naming metadata, not kernel records.

A signed AI4 identity record binds claims and provenance to an agent identity;
it does not prove the agent is aligned, safe, or correctly governed.

Identity is not trust. Resolution is not verification. Naming is not policy
authority.

These objects never become TrustContext, SessionPolicyIdentity, or RuntimeConfig.
Extra fields fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from ai4.identity.crypto import decode_public_key_hex, encode_public_key
from ai4.identity.errors import IdentityError
from ai4.identity.schemas import require_identity_id, require_sha256_hex
from ai4.identity.timeutil import format_utc

DISCOVERY_SCHEMA_ID = "ai4.identity.discovery.v1"
MAX_RECORD_STRING_LEN = 4096
MAX_RECORDS_PAYLOAD_BYTES = 65_536
MAX_ATTESTATION_BYTES = 262_144

FRESHNESS_KINDS = ("live", "cached", "fixture")
RESOLVER_IDS = ("file", "memory", "uns_rest")

NameResolvedStatus = Literal["yes", "no"]
IntegrityStatus = Literal["yes", "no"]
SignatureStatus = Literal["yes", "no", "not_requested"]
TrustStatus = Literal["yes", "no", "not_requested"]
BindingStatus = Literal[
    "yes",
    "no",
    "unbound",
    "mismatch",
    "expired",
    "untrusted_signer",
    "not_requested",
]

DISCOVERY_KEYS = (
    "schema_id",
    "name",
    "identity_id",
    "controller_public_key",
    "manifest_sha256",
    "attestation_sha256",
    "attestation_uri",
    "captured_at",
    "freshness",
    "resolver_id",
)
FRESHNESS_KEYS = ("kind", "age_s", "max_age_s")
STATUS_KEYS = (
    "name_resolved",
    "manifest_integrity_verified",
    "signature_valid",
    "current_trust_matched",
    "report_binding_matched",
)
FORBIDDEN_JSON_KEYS = frozenset(
    {"safe", "aligned", "accept", "revise", "refuse", "decision"}
)

RECORD_CONTROLLER_KEY = "ai4.identity.controller_public_key"
RECORD_MANIFEST_SHA256 = "ai4.identity.manifest_sha256"
RECORD_IDENTITY_ID = "ai4.identity.identity_id"
RECORD_ATTESTATION_SHA256 = "ai4.identity.attestation_sha256"
RECORD_ATTESTATION_URI = "ai4.identity.attestation_uri"
RECORD_MANIFEST_URI = "ai4.identity.manifest_uri"

INTEGRITY_REQUIRED_KEYS = (RECORD_CONTROLLER_KEY, RECORD_MANIFEST_SHA256)
KNOWN_RECORD_KEYS = frozenset(
    {
        RECORD_CONTROLLER_KEY,
        RECORD_MANIFEST_SHA256,
        RECORD_IDENTITY_ID,
        RECORD_ATTESTATION_SHA256,
        RECORD_ATTESTATION_URI,
        RECORD_MANIFEST_URI,
    }
)


def _require_object(raw: object, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise IdentityError(f"{label} must be a JSON object")
    return raw


def _reject_extra(raw: Mapping[str, Any], keys: tuple[str, ...], *, label: str) -> None:
    extra = sorted(str(key) for key in raw if key not in keys)
    if extra:
        raise IdentityError(f"Unknown {label} field(s) {extra}; failing closed")
    missing = [key for key in keys if key not in raw]
    if missing:
        raise IdentityError(f"{label} missing keys: {missing}")


def _require_str(raw: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(raw, str):
        raise IdentityError(f"{field} must be a string")
    if not allow_empty and not raw:
        raise IdentityError(f"{field} must be non-empty")
    return raw


def _require_int(raw: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise IdentityError(f"{field} must be an integer")
    if raw < minimum:
        raise IdentityError(f"{field} must be >= {minimum}")
    return raw


def assert_no_forbidden_json_keys(payload: Mapping[str, Any]) -> None:
    overlap = FORBIDDEN_JSON_KEYS.intersection(payload)
    if overlap:
        raise IdentityError(
            f"discovery JSON must not carry policy/alignment key(s) {sorted(overlap)}"
        )


@dataclass(frozen=True)
class Freshness:
    """Resolver cache metadata. Not NameRecordSnapshot.source and not trust."""

    kind: Literal["live", "cached", "fixture"]
    age_s: int
    max_age_s: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "age_s": self.age_s, "max_age_s": self.max_age_s}

    @classmethod
    def from_dict(cls, raw: object) -> Freshness:
        payload = _require_object(raw, label="freshness")
        _reject_extra(payload, FRESHNESS_KEYS, label="freshness")
        kind = _require_str(payload["kind"], field="freshness.kind")
        if kind not in FRESHNESS_KINDS:
            raise IdentityError(f"Unknown freshness.kind {kind!r}")
        max_age_raw = payload["max_age_s"]
        max_age: int | None
        if max_age_raw is None:
            max_age = None
        else:
            max_age = _require_int(max_age_raw, field="freshness.max_age_s", minimum=0)
        return cls(
            kind=kind,  # type: ignore[arg-type]
            age_s=_require_int(payload["age_s"], field="freshness.age_s", minimum=0),
            max_age_s=max_age,
        )


@dataclass(frozen=True)
class DiscoveryRecord:
    """Untrusted discovery metadata for a normalized .ai4 name.

    Resolver output is not verification, not current trust, and not policy.
    """

    name: str
    controller_public_key: str
    manifest_sha256: str
    captured_at: str
    freshness: Freshness
    resolver_id: str
    identity_id: str = ""
    attestation_sha256: str = ""
    attestation_uri: str = ""
    schema_id: str = DISCOVERY_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_id": self.schema_id,
            "name": self.name,
            "identity_id": self.identity_id,
            "controller_public_key": self.controller_public_key,
            "manifest_sha256": self.manifest_sha256,
            "attestation_sha256": self.attestation_sha256,
            "attestation_uri": self.attestation_uri,
            "captured_at": self.captured_at,
            "freshness": self.freshness.to_dict(),
            "resolver_id": self.resolver_id,
        }
        assert_no_forbidden_json_keys(payload)
        return payload

    @classmethod
    def from_dict(cls, raw: object) -> DiscoveryRecord:
        payload = _require_object(raw, label="DiscoveryRecord")
        _reject_extra(payload, DISCOVERY_KEYS, label="DiscoveryRecord")
        schema_id = _require_str(payload["schema_id"], field="schema_id")
        if schema_id != DISCOVERY_SCHEMA_ID:
            raise IdentityError(f"Unsupported DiscoveryRecord schema_id {schema_id!r}")
        identity_id_raw = _require_str(
            payload["identity_id"], field="identity_id", allow_empty=True
        )
        identity_id = require_identity_id(identity_id_raw) if identity_id_raw else ""
        attestation_sha = require_sha256_hex(
            payload["attestation_sha256"],
            field="attestation_sha256",
            allow_empty=True,
        )
        resolver_id = _require_str(payload["resolver_id"], field="resolver_id")
        if resolver_id not in RESOLVER_IDS:
            raise IdentityError(f"Unknown resolver_id {resolver_id!r}")
        return cls(
            name=_require_str(payload["name"], field="name"),
            identity_id=identity_id,
            controller_public_key=encode_public_key(
                decode_public_key_hex(payload["controller_public_key"])
            ),
            manifest_sha256=require_sha256_hex(
                payload["manifest_sha256"], field="manifest_sha256"
            ),
            attestation_sha256=attestation_sha,
            attestation_uri=_require_str(
                payload["attestation_uri"], field="attestation_uri", allow_empty=True
            ),
            captured_at=format_utc(payload["captured_at"]),
            freshness=Freshness.from_dict(payload["freshness"]),
            resolver_id=resolver_id,
        )


@dataclass(frozen=True)
class Status:
    """Five independent discovery/verify statuses. Never SAFE/ALIGNED/accept."""

    name_resolved: NameResolvedStatus
    manifest_integrity_verified: IntegrityStatus
    signature_valid: SignatureStatus
    current_trust_matched: TrustStatus
    report_binding_matched: BindingStatus

    def to_dict(self) -> dict[str, str]:
        payload = {
            "name_resolved": self.name_resolved,
            "manifest_integrity_verified": self.manifest_integrity_verified,
            "signature_valid": self.signature_valid,
            "current_trust_matched": self.current_trust_matched,
            "report_binding_matched": self.report_binding_matched,
        }
        assert_no_forbidden_json_keys(payload)
        return payload

    def human_lines(self) -> str:
        return "\n".join(
            [
                f"NAME RESOLVED: {self.name_resolved}",
                f"MANIFEST INTEGRITY VERIFIED: {self.manifest_integrity_verified}",
                f"SIGNATURE VALID: {self.signature_valid}",
                f"CURRENT TRUST MATCHED: {self.current_trust_matched}",
                f"REPORT BINDING MATCHED: {self.report_binding_matched}",
            ]
        )


@dataclass(frozen=True)
class ResolveResult:
    """Adapter result. Not a constraint decision and not current trust."""

    status: Status
    detail: str = ""
    discovery: DiscoveryRecord | None = None
    attestation: object | None = None
    name_snapshot: object | None = None
    binding_verdict: str = ""

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = dict(self.status.to_dict())
        payload["detail"] = self.detail
        if self.binding_verdict:
            payload["binding_verdict"] = self.binding_verdict
        if self.discovery is not None:
            payload["name"] = self.discovery.name
            payload["identity_id"] = self.discovery.identity_id
            payload["manifest_sha256"] = self.discovery.manifest_sha256
            payload["resolver_id"] = self.discovery.resolver_id
            payload["freshness_kind"] = self.discovery.freshness.kind
        assert_no_forbidden_json_keys(payload)
        return payload
