"""Frozen, strict identity and attestation records.

A signed AI⁴ identity record binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.

These records are not session policy, not RuntimeConfig, not a provider,
and not an evaluator. Extra fields fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from ai4.identity.canonical import canonicalize
from ai4.identity.crypto import decode_public_key_hex, decode_signature_hex, encode_public_key
from ai4.identity.digest import sha256_hex
from ai4.identity.errors import IdentityError
from ai4.identity.timeutil import format_utc, require_expiry_window

IDENTITY_SCHEMA_ID = "ai4.identity.agent.v1"
NAME_RECORD_SCHEMA_ID = "ai4.identity.name_record.v1"
ATTESTATION_SCHEMA_ID = "ai4.identity.attestation.v1"
ROTATION_SCHEMA_ID = "ai4.identity.rotation.v1"
CLAIMED_PROFILE_SCHEMA_ID = "ai4.identity.claimed_profile.v1"
NAME_RECORD_SOURCE = "local_snapshot"
SIGNATURE_ALGORITHM = "ed25519"
# RFC 8785 JCS numbers are IEEE-754. Manifest versions must be exact
# JSON-safe integers so hash bytes cannot depend on float rounding.
JCS_SAFE_INTEGER_MAX = (2**53) - 1
MANIFEST_VERSION_MIN = 1
MANIFEST_VERSION_MAX = JCS_SAFE_INTEGER_MAX

IDENTITY_KEYS = (
    "schema_id",
    "identity_id",
    "controller_public_key",
    "manifest_version",
    "issued_at",
    "expires_at",
    "name_records",
    "manifest_uri",
)
NAME_RECORD_KEYS = (
    "schema_id",
    "name",
    "subject_id",
    "controller_public_key",
    "captured_at",
    "source",
)
CLAIMED_PROFILE_KEYS = (
    "schema_id",
    "runtime_version",
    "report_schema_version",
    "protocol",
    "condition",
    "evidence_class",
    "rubric_set",
    "evaluator_id",
    "evaluator_version",
    "arbitration",
    "rubric_versions",
)
ROTATION_KEYS = (
    "schema_id",
    "identity_id",
    "previous_controller_public_key",
    "previous_manifest_version",
    "previous_manifest_hash",
    "new_controller_public_key",
    "new_manifest_version",
    "new_manifest_hash",
    "issued_at",
    "expires_at",
    "signature_algorithm",
    "signature",
)
ATTESTATION_KEYS = (
    "schema_id",
    "identity",
    "manifest_hash",
    "signature_algorithm",
    "signature",
    "issued_at",
    "expires_at",
    "report_hash",
    "claimed_profile",
    "rotation",
)

_IDENTITY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_WALLET_RE = re.compile(
    r"^(?:0x[0-9a-fA-F]{40}|wallet:|did:pkh:|did:ethr:|nft:|token:)",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_NAME_SOURCES = frozenset(
    {
        "unstoppable",
        "uns",
        "onchain",
        "on-chain",
        "http",
        "https",
        "network",
        "wallet",
        "tee",
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


def _require_int(raw: object, *, field: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise IdentityError(f"{field} must be an integer")
    if raw < minimum:
        raise IdentityError(f"{field} must be >= {minimum}")
    if maximum is not None and raw > maximum:
        raise IdentityError(f"{field} must be <= {maximum} (JCS-safe integer domain)")
    return raw


def require_manifest_version(raw: object, *, field: str = "manifest_version") -> int:
    """Fail closed before hashing or signing if the version is not JCS-safe."""
    return _require_int(
        raw,
        field=field,
        minimum=MANIFEST_VERSION_MIN,
        maximum=MANIFEST_VERSION_MAX,
    )


def require_identity_id(value: object) -> str:
    text = _require_str(value, field="identity_id")
    if _WALLET_RE.match(text):
        raise IdentityError(
            "identity_id must not be a wallet, token, NFT, or chain address; "
            "wallet-as-identity is out of scope"
        )
    if not _IDENTITY_ID_RE.fullmatch(text):
        raise IdentityError("identity_id must match [A-Za-z0-9._:-]{1,128}")
    return text


def require_sha256_hex(value: object, *, field: str, allow_empty: bool = False) -> str:
    text = _require_str(value, field=field, allow_empty=allow_empty)
    if allow_empty and text == "":
        return text
    if not _SHA256_RE.fullmatch(text):
        raise IdentityError(f"{field} must be lowercase SHA-256 hex")
    return text


def require_algorithm(value: object) -> str:
    text = _require_str(value, field="signature_algorithm")
    if text != SIGNATURE_ALGORITHM:
        raise IdentityError(
            f"Unknown signature algorithm {text!r}; only {SIGNATURE_ALGORITHM} is accepted"
        )
    return text


@dataclass(frozen=True)
class NameRecordSnapshot:
    """Local name snapshot. Not a live name-system lookup and not session state."""

    name: str
    subject_id: str
    controller_public_key: str
    captured_at: str
    source: Literal["local_snapshot"] = NAME_RECORD_SOURCE
    schema_id: str = NAME_RECORD_SCHEMA_ID

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_id": self.schema_id,
            "name": self.name,
            "subject_id": self.subject_id,
            "controller_public_key": self.controller_public_key,
            "captured_at": self.captured_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: object) -> NameRecordSnapshot:
        payload = _require_object(raw, label="name_record")
        _reject_extra(payload, NAME_RECORD_KEYS, label="name_record")
        schema_id = _require_str(payload["schema_id"], field="name_record.schema_id")
        if schema_id != NAME_RECORD_SCHEMA_ID:
            raise IdentityError(f"Unsupported name_record schema_id {schema_id!r}")
        source = _require_str(payload["source"], field="name_record.source")
        if source.lower() in _FORBIDDEN_NAME_SOURCES:
            raise IdentityError(
                "name_record.source must be local_snapshot; network/on-chain/"
                "wallet name resolution is out of scope"
            )
        if source != NAME_RECORD_SOURCE:
            raise IdentityError(f"Unknown name_record.source {source!r}")
        name = _require_str(payload["name"], field="name_record.name")
        if not _NAME_RE.fullmatch(name):
            raise IdentityError("name_record.name is malformed")
        subject_id = require_identity_id(payload["subject_id"])
        key = encode_public_key(decode_public_key_hex(payload["controller_public_key"]))
        captured_at = format_utc(payload["captured_at"])
        return cls(
            name=name,
            subject_id=subject_id,
            controller_public_key=key,
            captured_at=captured_at,
        )


@dataclass(frozen=True)
class AgentIdentity:
    """Strict agent identity record. Not trust, alignment, or governance proof."""

    identity_id: str
    controller_public_key: str
    manifest_version: int
    issued_at: str
    expires_at: str
    name_records: tuple[NameRecordSnapshot, ...] = ()
    manifest_uri: str = ""
    schema_id: str = IDENTITY_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "identity_id": self.identity_id,
            "controller_public_key": self.controller_public_key,
            "manifest_version": self.manifest_version,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "name_records": [item.to_dict() for item in self.name_records],
            "manifest_uri": self.manifest_uri,
        }

    def manifest_bytes(self) -> bytes:
        return canonicalize(self.to_dict(), identity_record=True)

    def manifest_hash(self) -> str:
        return sha256_hex(self.manifest_bytes())

    @classmethod
    def create(
        cls,
        *,
        identity_id: str,
        controller_public_key: str | bytes,
        manifest_version: int,
        issued_at: object,
        expires_at: object,
        name_records: tuple[NameRecordSnapshot, ...] | list[NameRecordSnapshot] = (),
        manifest_uri: str = "",
    ) -> AgentIdentity:
        key = (
            encode_public_key(controller_public_key)
            if isinstance(controller_public_key, (bytes, bytearray))
            else encode_public_key(decode_public_key_hex(controller_public_key))
        )
        issued = format_utc(issued_at)  # type: ignore[arg-type]
        expires = format_utc(expires_at)  # type: ignore[arg-type]
        require_expiry_window(issued, expires)
        if manifest_uri:
            _require_str(manifest_uri, field="manifest_uri")
        return cls.from_dict(
            {
                "schema_id": IDENTITY_SCHEMA_ID,
                "identity_id": identity_id,
                "controller_public_key": key,
                "manifest_version": manifest_version,
                "issued_at": issued,
                "expires_at": expires,
                "name_records": [item.to_dict() for item in name_records],
                "manifest_uri": manifest_uri,
            }
        )

    @classmethod
    def from_dict(cls, raw: object) -> AgentIdentity:
        payload = _require_object(raw, label="AgentIdentity")
        _reject_extra(payload, IDENTITY_KEYS, label="AgentIdentity")
        schema_id = _require_str(payload["schema_id"], field="schema_id")
        if schema_id != IDENTITY_SCHEMA_ID:
            raise IdentityError(f"Unsupported AgentIdentity schema_id {schema_id!r}")
        identity_id = require_identity_id(payload["identity_id"])
        key = encode_public_key(decode_public_key_hex(payload["controller_public_key"]))
        version = require_manifest_version(payload["manifest_version"])
        issued_at = format_utc(payload["issued_at"])
        expires_at = format_utc(payload["expires_at"])
        require_expiry_window(issued_at, expires_at)
        records_raw = payload["name_records"]
        if not isinstance(records_raw, list):
            raise IdentityError("name_records must be an array")
        name_records = tuple(NameRecordSnapshot.from_dict(item) for item in records_raw)
        for record in name_records:
            if record.subject_id != identity_id:
                raise IdentityError("name_record.subject_id must match identity_id")
            if record.controller_public_key != key:
                raise IdentityError("name_record.controller_public_key must match identity")
        manifest_uri = _require_str(payload["manifest_uri"], field="manifest_uri", allow_empty=True)
        if manifest_uri.startswith(("http://", "https://", "uns:", "onchain:")):
            # Allowed as an informational string only. Integrity is the hash.
            pass
        return cls(
            identity_id=identity_id,
            controller_public_key=key,
            manifest_version=version,
            issued_at=issued_at,
            expires_at=expires_at,
            name_records=name_records,
            manifest_uri=manifest_uri,
        )


@dataclass(frozen=True)
class ClaimedProfile:
    """VersionInfo claims copied at bind time. Not a policy override."""

    runtime_version: str
    report_schema_version: str
    protocol: str
    condition: str
    evidence_class: str
    rubric_set: str
    evaluator_id: str
    evaluator_version: str
    arbitration: str
    rubric_versions: dict[str, str]
    schema_id: str = CLAIMED_PROFILE_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "runtime_version": self.runtime_version,
            "report_schema_version": self.report_schema_version,
            "protocol": self.protocol,
            "condition": self.condition,
            "evidence_class": self.evidence_class,
            "rubric_set": self.rubric_set,
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "arbitration": self.arbitration,
            "rubric_versions": dict(self.rubric_versions),
        }

    def comparable(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("schema_id")
        return payload

    @classmethod
    def from_versions(cls, versions: object) -> ClaimedProfile:
        if hasattr(versions, "to_dict"):
            raw = versions.to_dict()
        elif isinstance(versions, dict):
            raw = dict(versions)
        else:
            raise IdentityError("claimed profile requires VersionInfo or an object")
        return cls.from_dict(
            {
                "schema_id": CLAIMED_PROFILE_SCHEMA_ID,
                "runtime_version": raw.get("runtime_version"),
                "report_schema_version": raw.get("report_schema_version"),
                "protocol": raw.get("protocol"),
                "condition": raw.get("condition"),
                "evidence_class": raw.get("evidence_class"),
                "rubric_set": raw.get("rubric_set"),
                "evaluator_id": raw.get("evaluator_id"),
                "evaluator_version": raw.get("evaluator_version"),
                "arbitration": raw.get("arbitration"),
                "rubric_versions": raw.get("rubric_versions") or {},
            }
        )

    @classmethod
    def from_dict(cls, raw: object) -> ClaimedProfile:
        payload = _require_object(raw, label="claimed_profile")
        _reject_extra(payload, CLAIMED_PROFILE_KEYS, label="claimed_profile")
        schema_id = _require_str(payload["schema_id"], field="claimed_profile.schema_id")
        if schema_id != CLAIMED_PROFILE_SCHEMA_ID:
            raise IdentityError(f"Unsupported claimed_profile schema_id {schema_id!r}")
        versions = payload["rubric_versions"]
        if not isinstance(versions, dict):
            raise IdentityError("claimed_profile.rubric_versions must be an object")
        cleaned: dict[str, str] = {}
        for key, value in versions.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise IdentityError("rubric_versions keys and values must be strings")
            cleaned[key] = value
        return cls(
            runtime_version=_require_str(payload["runtime_version"], field="runtime_version"),
            report_schema_version=_require_str(
                payload["report_schema_version"], field="report_schema_version"
            ),
            protocol=_require_str(payload["protocol"], field="protocol"),
            condition=_require_str(payload["condition"], field="condition"),
            evidence_class=_require_str(payload["evidence_class"], field="evidence_class"),
            rubric_set=_require_str(payload["rubric_set"], field="rubric_set"),
            evaluator_id=_require_str(payload["evaluator_id"], field="evaluator_id"),
            evaluator_version=_require_str(
                payload["evaluator_version"], field="evaluator_version", allow_empty=True
            ),
            arbitration=_require_str(payload["arbitration"], field="arbitration"),
            rubric_versions=cleaned,
        )


@dataclass(frozen=True)
class RotationAttestation:
    """Optional single-controller rotation signed by the previous key.

    Binds ``identity_id`` plus the successor controller key, version, and
    manifest hash. A rotation for one identity cannot authorize another.
    Versions are strictly monotonic; skipping is allowed and abandons
    intermediate versions. There is no CRL. Compromised-key recovery
    remains a residual risk.
    """

    identity_id: str
    previous_controller_public_key: str
    previous_manifest_version: int
    previous_manifest_hash: str
    new_controller_public_key: str
    new_manifest_version: int
    new_manifest_hash: str
    issued_at: str
    expires_at: str
    signature: str
    signature_algorithm: str = SIGNATURE_ALGORITHM
    schema_id: str = ROTATION_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "identity_id": self.identity_id,
            "previous_controller_public_key": self.previous_controller_public_key,
            "previous_manifest_version": self.previous_manifest_version,
            "previous_manifest_hash": self.previous_manifest_hash,
            "new_controller_public_key": self.new_controller_public_key,
            "new_manifest_version": self.new_manifest_version,
            "new_manifest_hash": self.new_manifest_hash,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature_algorithm": self.signature_algorithm,
            "signature": self.signature,
        }

    def tbs_bytes(self) -> bytes:
        payload = self.to_dict()
        payload["signature"] = ""
        return canonicalize(payload, identity_record=True)

    @classmethod
    def from_dict(cls, raw: object) -> RotationAttestation:
        payload = _require_object(raw, label="rotation")
        _reject_extra(payload, ROTATION_KEYS, label="rotation")
        schema_id = _require_str(payload["schema_id"], field="rotation.schema_id")
        if schema_id != ROTATION_SCHEMA_ID:
            raise IdentityError(f"Unsupported rotation schema_id {schema_id!r}")
        previous_key = encode_public_key(
            decode_public_key_hex(payload["previous_controller_public_key"])
        )
        new_key = encode_public_key(decode_public_key_hex(payload["new_controller_public_key"]))
        if previous_key == new_key:
            raise IdentityError("rotation must change the controller public key")
        previous_version = require_manifest_version(
            payload["previous_manifest_version"], field="previous_manifest_version"
        )
        new_version = require_manifest_version(
            payload["new_manifest_version"], field="new_manifest_version"
        )
        if new_version <= previous_version:
            raise IdentityError("rotation manifest_version must be strictly monotonic")
        issued_at = format_utc(payload["issued_at"])
        expires_at = format_utc(payload["expires_at"])
        require_expiry_window(issued_at, expires_at)
        return cls(
            identity_id=require_identity_id(payload["identity_id"]),
            previous_controller_public_key=previous_key,
            previous_manifest_version=previous_version,
            previous_manifest_hash=require_sha256_hex(
                payload["previous_manifest_hash"], field="previous_manifest_hash"
            ),
            new_controller_public_key=new_key,
            new_manifest_version=new_version,
            new_manifest_hash=require_sha256_hex(
                payload["new_manifest_hash"], field="new_manifest_hash"
            ),
            issued_at=issued_at,
            expires_at=expires_at,
            signature_algorithm=require_algorithm(payload["signature_algorithm"]),
            signature=decode_signature_hex(payload["signature"]).hex(),
        )


@dataclass(frozen=True)
class AgentAttestation:
    """Signed provenance record. Not an accept/revise/refuse decision."""

    identity: AgentIdentity
    manifest_hash: str
    signature: str
    issued_at: str
    expires_at: str
    report_hash: str = ""
    claimed_profile: ClaimedProfile | None = None
    rotation: RotationAttestation | None = None
    signature_algorithm: str = SIGNATURE_ALGORITHM
    schema_id: str = ATTESTATION_SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "identity": self.identity.to_dict(),
            "manifest_hash": self.manifest_hash,
            "signature_algorithm": self.signature_algorithm,
            "signature": self.signature,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "report_hash": self.report_hash,
            "claimed_profile": None if self.claimed_profile is None else self.claimed_profile.to_dict(),
            "rotation": None if self.rotation is None else self.rotation.to_dict(),
        }

    def tbs_bytes(self) -> bytes:
        payload = self.to_dict()
        payload["signature"] = ""
        return canonicalize(payload, identity_record=True)

    @classmethod
    def from_dict(cls, raw: object) -> AgentAttestation:
        payload = _require_object(raw, label="AgentAttestation")
        _reject_extra(payload, ATTESTATION_KEYS, label="AgentAttestation")
        schema_id = _require_str(payload["schema_id"], field="schema_id")
        if schema_id != ATTESTATION_SCHEMA_ID:
            raise IdentityError(f"Unsupported AgentAttestation schema_id {schema_id!r}")
        identity = AgentIdentity.from_dict(payload["identity"])
        issued_at = format_utc(payload["issued_at"])
        expires_at = format_utc(payload["expires_at"])
        require_expiry_window(issued_at, expires_at)
        profile_raw = payload["claimed_profile"]
        if profile_raw is None:
            claimed_profile = None
        else:
            claimed_profile = ClaimedProfile.from_dict(profile_raw)
        rotation_raw = payload["rotation"]
        if rotation_raw is None:
            rotation = None
        else:
            rotation = RotationAttestation.from_dict(rotation_raw)
            if rotation.identity_id != identity.identity_id:
                raise IdentityError(
                    "rotation identity_id does not match attestation identity; "
                    "a rotation cannot authorize a different agent"
                )
        report_hash = require_sha256_hex(
            payload["report_hash"], field="report_hash", allow_empty=True
        )
        if (report_hash == "") != (claimed_profile is None):
            raise IdentityError(
                "report_hash and claimed_profile must both be present or both be absent"
            )
        return cls(
            identity=identity,
            manifest_hash=require_sha256_hex(payload["manifest_hash"], field="manifest_hash"),
            signature_algorithm=require_algorithm(payload["signature_algorithm"]),
            signature=decode_signature_hex(payload["signature"]).hex(),
            issued_at=issued_at,
            expires_at=expires_at,
            report_hash=report_hash,
            claimed_profile=claimed_profile,
            rotation=rotation,
        )
