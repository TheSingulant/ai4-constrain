"""Load/hash packaged V07-0 finding taxonomy and policy-map artifacts.

These artifacts are product-owned closed vocabulary and placeholder overlay
tables. V07-0 loads and hashes them only. V07-1 may consume a loaded map
through the standalone ``semantic_fuse`` primitive. ConstraintMiddleware,
revision integration, and accept/revise/refuse still do not consume them.

C3 overlay convention (validated here): overlay[s] is a
nonnegative penalty magnitude in [0, cap]. Conceptual fusion is
fused[s] = clamp(det[s] - overlay[s], 0, det[s]). This module does not
apply that equation to decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Mapping

from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import SemanticFindingsError

_PACKAGE = "ai4.data"
_RELATIVE = ("semantic_v07",)

REGISTRY_ARTIFACT_ID = "finding_registry_v1"
POLICY_MAP_ARTIFACT_ID = "finding_policy_map_v1"
REGISTRY_SCHEMA_VERSION = "ai4.finding_registry.v1"
POLICY_MAP_SCHEMA_VERSION = "ai4.finding_policy_map.v1"
TAXONOMY_VERSION = "0.7.0"

CONFIDENCE_BINS = ("low", "medium", "high")
REQUIRED_SHARD_IDS = REQUIRED_IDS

REGISTRY_KEYS = (
    "schema_version",
    "artifact_id",
    "version",
    "class_ids",
    "observation_codes",
    "injection_signal_codes",
)
POLICY_MAP_KEYS = (
    "schema_version",
    "artifact_id",
    "version",
    "required_shards",
    "confidence_bins",
    "shard_caps",
    "mappings",
)
CLASS_ENTRY_KEYS = ("doc",)
CODE_ENTRY_KEYS = ("doc",)
MAPPING_KEYS = ("shards", "overlay_deltas")
# Per-shard maximum overlay penalty. Overlay ∈ [0, cap]; cap >= 0.
CAP_KEYS = ("cap",)


def _sha256_hex(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise SemanticFindingsError("SHA-256 identity requires bytes")
    return hashlib.sha256(data).hexdigest()


def _artifact_bytes(filename: str) -> bytes:
    traversable = files(_PACKAGE).joinpath(*_RELATIVE, filename)
    try:
        payload = traversable.read_bytes()
    except Exception as exc:
        raise SemanticFindingsError(
            f"Packaged semantic artifact {filename!r} is missing or unreadable: {exc}"
        ) from exc
    if not payload.strip():
        raise SemanticFindingsError(f"Packaged semantic artifact {filename!r} is empty")
    return bytes(payload)


def _load_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SemanticFindingsError(f"Malformed {label} JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemanticFindingsError(f"{label} must be a JSON object")
    if any(not isinstance(key, str) for key in payload):
        raise SemanticFindingsError(f"{label} keys must be strings")
    return payload


def _reject_extra(raw: Mapping[str, Any], keys: tuple[str, ...], *, label: str) -> None:
    extra = sorted(str(key) for key in raw if key not in keys)
    if extra:
        raise SemanticFindingsError(f"Unknown {label} field(s) {extra}; failing closed")
    missing = [key for key in keys if key not in raw]
    if missing:
        raise SemanticFindingsError(f"{label} missing keys: {missing}")


def _require_str(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SemanticFindingsError(f"{field} must be a non-empty string")
    return raw


def _require_doc_map(raw: object, *, field: str) -> dict[str, str]:
    if not isinstance(raw, dict) or not raw:
        raise SemanticFindingsError(f"{field} must be a non-empty object")
    docs: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise SemanticFindingsError(f"{field} keys must be non-empty strings")
        if not isinstance(value, dict):
            raise SemanticFindingsError(f"{field}.{key} must be an object")
        _reject_extra(value, CLASS_ENTRY_KEYS, label=f"{field}.{key}")
        docs[key] = _require_str(value["doc"], field=f"{field}.{key}.doc")
    return docs


def _finite_number(raw: object, *, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SemanticFindingsError(f"{field} must be a finite number")
    number = float(raw)
    if not math.isfinite(number):
        raise SemanticFindingsError(f"{field} must be a finite number; got {number!r}")
    return number


def _require_shard_id(raw: object, *, field: str, allowed: frozenset[str]) -> str:
    shard_id = _require_str(raw, field=field)
    if shard_id not in allowed:
        raise SemanticFindingsError(
            f"Unknown extra shard name {shard_id!r} in {field}; failing closed"
        )
    return shard_id


@dataclass(frozen=True)
class FindingClassEntry:
    class_id: str
    doc: str


@dataclass(frozen=True)
class FindingCodeEntry:
    code: str
    doc: str


@dataclass(frozen=True)
class FindingRegistryV1:
    schema_version: str
    artifact_id: str
    version: str
    class_ids: tuple[FindingClassEntry, ...]
    observation_codes: tuple[FindingCodeEntry, ...]
    injection_signal_codes: tuple[FindingCodeEntry, ...]
    sha256: str

    def class_id_set(self) -> frozenset[str]:
        return frozenset(item.class_id for item in self.class_ids)

    def observation_code_set(self) -> frozenset[str]:
        return frozenset(item.code for item in self.observation_codes)

    def injection_signal_code_set(self) -> frozenset[str]:
        return frozenset(item.code for item in self.injection_signal_codes)


@dataclass(frozen=True)
class ShardCap:
    """Maximum permitted overlay penalty for one shard.

    ``cap`` is a nonnegative upper bound. Overlay penalties must satisfy
    ``0 <= overlay[s] <= cap``. Negative caps fail closed.
    """

    shard_id: str
    cap: float


@dataclass(frozen=True)
class FindingClassMapping:
    class_id: str
    shards: tuple[str, ...]
    overlay_deltas: tuple[tuple[str, tuple[tuple[str, float], ...]], ...]


@dataclass(frozen=True)
class FindingPolicyMapV1:
    schema_version: str
    artifact_id: str
    version: str
    required_shards: tuple[str, ...]
    confidence_bins: tuple[str, ...]
    shard_caps: tuple[ShardCap, ...]
    mappings: tuple[FindingClassMapping, ...]
    sha256: str


def _validate_registry(payload: dict[str, Any], *, sha256: str) -> FindingRegistryV1:
    _reject_extra(payload, REGISTRY_KEYS, label="finding_registry_v1")
    schema_version = _require_str(payload["schema_version"], field="schema_version")
    if schema_version != REGISTRY_SCHEMA_VERSION:
        raise SemanticFindingsError(
            f"finding_registry_v1 schema_version must be {REGISTRY_SCHEMA_VERSION!r}"
        )
    artifact_id = _require_str(payload["artifact_id"], field="artifact_id")
    if artifact_id != REGISTRY_ARTIFACT_ID:
        raise SemanticFindingsError(f"artifact_id must be {REGISTRY_ARTIFACT_ID!r}")
    version = _require_str(payload["version"], field="version")
    if version != TAXONOMY_VERSION:
        raise SemanticFindingsError(f"finding_registry_v1 version must be {TAXONOMY_VERSION!r}")
    class_docs = _require_doc_map(payload["class_ids"], field="class_ids")
    observation_docs = _require_doc_map(payload["observation_codes"], field="observation_codes")
    injection_docs = _require_doc_map(
        payload["injection_signal_codes"], field="injection_signal_codes"
    )
    class_ids = tuple(
        FindingClassEntry(class_id=key, doc=class_docs[key]) for key in sorted(class_docs)
    )
    observation_codes = tuple(
        FindingCodeEntry(code=key, doc=observation_docs[key]) for key in sorted(observation_docs)
    )
    injection_signal_codes = tuple(
        FindingCodeEntry(code=key, doc=injection_docs[key]) for key in sorted(injection_docs)
    )
    if not class_ids:
        raise SemanticFindingsError("finding_registry_v1 class_ids must be non-empty")
    return FindingRegistryV1(
        schema_version=schema_version,
        artifact_id=artifact_id,
        version=version,
        class_ids=class_ids,
        observation_codes=observation_codes,
        injection_signal_codes=injection_signal_codes,
        sha256=sha256,
    )


def _validate_caps(
    raw: object, *, required_shards: tuple[str, ...]
) -> tuple[ShardCap, ...]:
    if not isinstance(raw, dict):
        raise SemanticFindingsError("shard_caps must be an object")
    allowed = frozenset(required_shards)
    extra = sorted(str(key) for key in raw if key not in allowed)
    if extra:
        raise SemanticFindingsError(
            f"Unknown extra shard name(s) in shard_caps {extra}; failing closed"
        )
    missing = [item for item in required_shards if item not in raw]
    if missing:
        raise SemanticFindingsError(f"shard_caps missing required shards: {missing}")
    caps: list[ShardCap] = []
    for shard_id in required_shards:
        entry = raw[shard_id]
        if not isinstance(entry, dict):
            raise SemanticFindingsError(f"shard_caps.{shard_id} must be an object")
        _reject_extra(entry, CAP_KEYS, label=f"shard_caps.{shard_id}")
        cap = _finite_number(entry["cap"], field=f"shard_caps.{shard_id}.cap")
        if cap < 0:
            raise SemanticFindingsError(
                f"shard_caps.{shard_id}.cap must be nonnegative; failing closed"
            )
        caps.append(ShardCap(shard_id=shard_id, cap=cap))
    return tuple(caps)


def _validate_mapping(
    class_id: str,
    raw: object,
    *,
    allowed_shards: frozenset[str],
    caps: dict[str, ShardCap],
    confidence_bins: tuple[str, ...],
) -> FindingClassMapping:
    if not isinstance(raw, dict):
        raise SemanticFindingsError(f"mappings.{class_id} must be an object")
    _reject_extra(raw, MAPPING_KEYS, label=f"mappings.{class_id}")
    shards_raw = raw["shards"]
    if not isinstance(shards_raw, list) or not shards_raw:
        raise SemanticFindingsError(f"mappings.{class_id}.shards must be a non-empty array")
    shards: list[str] = []
    for index, item in enumerate(shards_raw):
        shard_id = _require_shard_id(
            item, field=f"mappings.{class_id}.shards[{index}]", allowed=allowed_shards
        )
        if shard_id in shards:
            raise SemanticFindingsError(
                f"mappings.{class_id}.shards has duplicate {shard_id!r}"
            )
        shards.append(shard_id)
    overlays_raw = raw["overlay_deltas"]
    if not isinstance(overlays_raw, dict):
        raise SemanticFindingsError(f"mappings.{class_id}.overlay_deltas must be an object")
    extra_bins = sorted(str(key) for key in overlays_raw if key not in confidence_bins)
    if extra_bins:
        raise SemanticFindingsError(
            f"Unknown confidence_bin(s) {extra_bins} in mappings.{class_id}"
        )
    missing_bins = [item for item in confidence_bins if item not in overlays_raw]
    if missing_bins:
        raise SemanticFindingsError(
            f"mappings.{class_id}.overlay_deltas missing bins: {missing_bins}"
        )
    overlay_deltas: list[tuple[str, tuple[tuple[str, float], ...]]] = []
    mapped = frozenset(shards)
    for bin_name in confidence_bins:
        deltas_raw = overlays_raw[bin_name]
        if not isinstance(deltas_raw, dict) or not deltas_raw:
            raise SemanticFindingsError(
                f"mappings.{class_id}.overlay_deltas.{bin_name} must be a non-empty object"
            )
        extra_overlay = sorted(str(key) for key in deltas_raw if key not in mapped)
        if extra_overlay:
            raise SemanticFindingsError(
                f"Unknown extra shard name(s) {extra_overlay} in "
                f"mappings.{class_id}.overlay_deltas.{bin_name}; failing closed"
            )
        missing_overlay = [item for item in shards if item not in deltas_raw]
        if missing_overlay:
            raise SemanticFindingsError(
                f"mappings.{class_id}.overlay_deltas.{bin_name} missing shards: {missing_overlay}"
            )
        deltas: list[tuple[str, float]] = []
        for shard_id in shards:
            delta = _finite_number(
                deltas_raw[shard_id],
                field=f"mappings.{class_id}.overlay_deltas.{bin_name}.{shard_id}",
            )
            cap = caps[shard_id]
            # C3: overlay[s] ∈ [0, cap]. Negative penalties fail closed.
            if delta < 0:
                raise SemanticFindingsError(
                    f"overlay penalty for {class_id}/{bin_name}/{shard_id}={delta} "
                    "must be nonnegative; failing closed"
                )
            if delta > cap.cap:
                raise SemanticFindingsError(
                    f"overlay penalty for {class_id}/{bin_name}/{shard_id}={delta} "
                    f"exceeds shard cap {cap.cap}; failing closed"
                )
            deltas.append((shard_id, delta))
        overlay_deltas.append((bin_name, tuple(deltas)))
    return FindingClassMapping(
        class_id=class_id,
        shards=tuple(shards),
        overlay_deltas=tuple(overlay_deltas),
    )


def _validate_policy_map(
    payload: dict[str, Any],
    *,
    sha256: str,
    class_ids: frozenset[str],
) -> FindingPolicyMapV1:
    _reject_extra(payload, POLICY_MAP_KEYS, label="finding_policy_map_v1")
    schema_version = _require_str(payload["schema_version"], field="schema_version")
    if schema_version != POLICY_MAP_SCHEMA_VERSION:
        raise SemanticFindingsError(
            f"finding_policy_map_v1 schema_version must be {POLICY_MAP_SCHEMA_VERSION!r}"
        )
    artifact_id = _require_str(payload["artifact_id"], field="artifact_id")
    if artifact_id != POLICY_MAP_ARTIFACT_ID:
        raise SemanticFindingsError(f"artifact_id must be {POLICY_MAP_ARTIFACT_ID!r}")
    version = _require_str(payload["version"], field="version")
    if version != TAXONOMY_VERSION:
        raise SemanticFindingsError(f"finding_policy_map_v1 version must be {TAXONOMY_VERSION!r}")
    shards_raw = payload["required_shards"]
    if not isinstance(shards_raw, list):
        raise SemanticFindingsError("required_shards must be an array")
    required_shards = tuple(
        _require_shard_id(item, field=f"required_shards[{i}]", allowed=frozenset(REQUIRED_SHARD_IDS))
        for i, item in enumerate(shards_raw)
    )
    if required_shards != REQUIRED_SHARD_IDS:
        raise SemanticFindingsError(
            "required_shards must be exactly the frozen v0.1 shard ids "
            f"{list(REQUIRED_SHARD_IDS)}; extra shard names fail closed"
        )
    bins_raw = payload["confidence_bins"]
    if not isinstance(bins_raw, list):
        raise SemanticFindingsError("confidence_bins must be an array")
    confidence_bins = tuple(_require_str(item, field=f"confidence_bins[{i}]") for i, item in enumerate(bins_raw))
    if confidence_bins != CONFIDENCE_BINS:
        raise SemanticFindingsError(f"confidence_bins must be {list(CONFIDENCE_BINS)}")
    caps = _validate_caps(payload["shard_caps"], required_shards=required_shards)
    cap_by_id = {item.shard_id: item for item in caps}
    mappings_raw = payload["mappings"]
    if not isinstance(mappings_raw, dict) or not mappings_raw:
        raise SemanticFindingsError("mappings must be a non-empty object")
    extra_classes = sorted(str(key) for key in mappings_raw if key not in class_ids)
    if extra_classes:
        raise SemanticFindingsError(
            f"Unknown class_id(s) in finding_policy_map_v1 {extra_classes}; failing closed"
        )
    missing_classes = sorted(class_ids - set(mappings_raw))
    if missing_classes:
        raise SemanticFindingsError(
            f"finding_policy_map_v1 missing class_id mappings: {missing_classes}"
        )
    allowed_shards = frozenset(required_shards)
    mappings = tuple(
        _validate_mapping(
            class_id,
            mappings_raw[class_id],
            allowed_shards=allowed_shards,
            caps=cap_by_id,
            confidence_bins=confidence_bins,
        )
        for class_id in sorted(class_ids)
    )
    return FindingPolicyMapV1(
        schema_version=schema_version,
        artifact_id=artifact_id,
        version=version,
        required_shards=required_shards,
        confidence_bins=confidence_bins,
        shard_caps=caps,
        mappings=mappings,
        sha256=sha256,
    )


def packaged_finding_registry_bytes() -> bytes:
    return _artifact_bytes("finding_registry_v1.json")


def packaged_finding_policy_map_bytes() -> bytes:
    return _artifact_bytes("finding_policy_map_v1.json")


def finding_registry_sha256() -> str:
    return _sha256_hex(packaged_finding_registry_bytes())


def finding_policy_map_sha256() -> str:
    return _sha256_hex(packaged_finding_policy_map_bytes())


def load_finding_registry_v1() -> FindingRegistryV1:
    raw = packaged_finding_registry_bytes()
    return _validate_registry(_load_json_object(raw, label="finding_registry_v1"), sha256=_sha256_hex(raw))


def load_finding_policy_map_v1(
    registry: FindingRegistryV1 | None = None,
) -> FindingPolicyMapV1:
    loaded_registry = registry if registry is not None else load_finding_registry_v1()
    raw = packaged_finding_policy_map_bytes()
    return _validate_policy_map(
        _load_json_object(raw, label="finding_policy_map_v1"),
        sha256=_sha256_hex(raw),
        class_ids=loaded_registry.class_id_set(),
    )


def validate_finding_registry_payload(
    payload: Mapping[str, Any],
    *,
    sha256: str = "",
) -> FindingRegistryV1:
    if not isinstance(payload, dict):
        raise SemanticFindingsError("finding_registry_v1 must be a JSON object")
    return _validate_registry(dict(payload), sha256=sha256)


def validate_finding_policy_map_payload(
    payload: Mapping[str, Any],
    *,
    class_ids: frozenset[str],
    sha256: str = "",
) -> FindingPolicyMapV1:
    if not isinstance(payload, dict):
        raise SemanticFindingsError("finding_policy_map_v1 must be a JSON object")
    return _validate_policy_map(dict(payload), sha256=sha256, class_ids=class_ids)


__all__ = [
    "CONFIDENCE_BINS",
    "FindingClassEntry",
    "FindingClassMapping",
    "FindingCodeEntry",
    "FindingPolicyMapV1",
    "FindingRegistryV1",
    "POLICY_MAP_ARTIFACT_ID",
    "POLICY_MAP_SCHEMA_VERSION",
    "REGISTRY_ARTIFACT_ID",
    "REGISTRY_SCHEMA_VERSION",
    "REQUIRED_SHARD_IDS",
    "ShardCap",
    "TAXONOMY_VERSION",
    "finding_policy_map_sha256",
    "finding_registry_sha256",
    "load_finding_policy_map_v1",
    "load_finding_registry_v1",
    "packaged_finding_policy_map_bytes",
    "packaged_finding_registry_bytes",
    "validate_finding_policy_map_payload",
    "validate_finding_registry_payload",
]
