"""V07-1 packaged mapping + packaged_fuse_v2 (standalone primitive).

Converts already-validated/bound semantic findings through the product-owned
V07-0 policy map into bounded shard penalties, then applies:

    fused[s] = clamp(det[s] - overlay[s], 0, det[s])

overlay[s] >= 0, and after aggregation overlay[s] = min(aggregate, packaged_cap[s]).
Invariant: 0 <= fused[s] <= det[s]. Semantic overlay may tighten a deterministic
score; it may never raise one. A det failure cannot be washed out.

This module is not operational in production. It does not call an examiner
backend, does not change run()/evaluate()/ConstraintMiddleware, and does
not define revision, refusal, arbitration, or terminal control.

Authority
---------
Findings are evidence only. The examiner must not define scores, routing,
penalty magnitudes, thresholds, arbitration, revision/refusal, or terminal
decisions. Only the packaged map translates
``class_id × confidence_bin → shard penalties``. The public
``map_and_fuse_v2`` path always loads the locked V07-0 packaged bytes
and records the SHA-256 of those exact bytes. It does not accept
``policy_map=`` or ``registry=``. Examiner-supplied routing, scores,
thresholds, deltas, weights, or policy fail closed. Provenance is audit
output and is never a policy input.

Aggregation / dedup semantics (Architecture C3, normative)
----------------------------------------------------------
1. Findings are already validated and bound upstream. This primitive
   consumes ``BoundFinding`` values that carry a runtime-owned
   ``claim_fingerprint``. It does not parse or bind examiner JSON.
2. Duplicate suppression identity is ``(class_id, claim_fingerprint)``.
   Two findings are equivalent iff both identity fields match.
   Among a duplicate group, retain exactly one survivor:
     - highest ``confidence_bin`` using the packaged order
       ``low < medium < high``;
     - if ``confidence_bin`` ties, retain the lexicographically smallest
       ``finding_id`` (penalty is identical for the same class × bin);
     - duplicate ``finding_id`` values in the input fail closed.
   Suppressed equivalents do not contribute overlay and cannot multiply
   penalties.
3. Initialize ``overlay[s] = 0`` for every required shard.
4. For each survivor, in deterministic order
   ``(class_id, claim_fingerprint, finding_id)``:
     shards = map.route[class_id]
     deltas = map.overlay[class_id][confidence_bin]
     for every required shard s: overlay[s] += deltas.get(s, 0)
   Route and deltas come only from the packaged map. Unknown/unmapped
   ``class_id`` fails closed. Invalid shard names, missing bins, negative
   or non-finite penalties fail closed.
5. ``overlay[s] = min(overlay[s], map.cap[s])`` for every required shard.
6. Apply ``packaged_fuse_v2``: ``fused[s] = clamp(det[s] - overlay[s], 0, det[s])``.
7. Assert ``0 <= fused[s] <= det[s]``. Det scores must be finite and in
   the product domain ``[0, 1]``. Empty findings yield overlay 0 and
   ``fused == det``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ai4.constrain.errors import SemanticFuseError
from ai4.constrain.semantic_findings import (
    POLICY_SMUGGLE_KEYS,
    BoundFinding,
    BoundSemanticFindings,
    SemanticFinding,
)
from ai4.constrain.semantic_taxonomy import (
    CONFIDENCE_BINS,
    FindingPolicyMapV1,
    FindingRegistryV1,
    POLICY_MAP_ARTIFACT_ID,
    POLICY_MAP_SCHEMA_VERSION,
    REQUIRED_SHARD_IDS,
    TAXONOMY_VERSION,
    load_finding_registry_v1,
    packaged_finding_policy_map_bytes,
    packaged_finding_registry_bytes,
    validate_finding_policy_map_payload,
    validate_finding_registry_payload,
)

PACKAGED_FUSE_ID = "packaged_fuse_v2"
FUSE_EQUATION = "fused[s] = clamp(det[s] - overlay[s], 0, det[s])"
PACKAGED_SOURCE = "packaged"
SYNTHETIC_TEST_SOURCE = "synthetic-test"

# Runtime authority is these exact packaged artifact identities.
LOCKED_REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
LOCKED_POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_PUBLIC_POLICY_OVERRIDE_KEYS = frozenset({"policy_map", "registry"})

# Caller/examiner fields that may not steer mapping or fusion.
_AUTHORITY_BOUNDARY_KEYS = frozenset(POLICY_SMUGGLE_KEYS) | frozenset(
    {
        "cap",
        "caps",
        "delta",
        "deltas",
        "overlay",
        "overlays",
        "overlay_deltas",
        "penalty",
        "penalties",
        "policy_map",
        "registry",
        "route",
        "routing",
        "weight",
        "weights",
    }
)


def _finite_number(raw: object, *, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SemanticFuseError(f"{field} must be a finite number")
    number = float(raw)
    if not math.isfinite(number):
        raise SemanticFuseError(f"{field} must be a finite number; got {number!r}")
    return number


def _require_nonnegative(value: float, *, field: str) -> float:
    if value < 0:
        raise SemanticFuseError(f"{field} must be nonnegative; failing closed")
    return value


def _sha256_hex(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise SemanticFuseError("SHA-256 identity requires bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def _reject_authority_kwargs(kwargs: Mapping[str, Any], *, label: str) -> None:
    if not kwargs:
        return
    overrides = sorted(key for key in kwargs if key in _PUBLIC_POLICY_OVERRIDE_KEYS)
    if overrides:
        raise SemanticFuseError(
            f"{label} does not accept policy substitution {overrides}; failing closed"
        )
    smuggled = sorted(key for key in kwargs if key in _AUTHORITY_BOUNDARY_KEYS)
    if smuggled:
        raise SemanticFuseError(
            f"{label} supplies policy/control field(s) {smuggled}; failing closed"
        )
    extra = sorted(str(key) for key in kwargs)
    raise SemanticFuseError(f"Unknown {label} argument(s) {extra}; failing closed")


def _require_shard_id(raw: object, *, field: str, allowed: frozenset[str]) -> str:
    if not isinstance(raw, str) or not raw:
        raise SemanticFuseError(f"{field} must be a non-empty shard id")
    if raw not in allowed:
        raise SemanticFuseError(f"Unknown extra shard name {raw!r} in {field}; failing closed")
    return raw


def _score_map(
    raw: object,
    *,
    label: str,
    required_shards: tuple[str, ...],
    maximum: float | None,
) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise SemanticFuseError(f"{label} must be a mapping of shard id to number")
    if any(not isinstance(key, str) for key in raw):
        raise SemanticFuseError(f"{label} keys must be strings")
    allowed = frozenset(required_shards)
    extra = sorted(str(key) for key in raw if key not in allowed)
    if extra:
        raise SemanticFuseError(f"Unknown extra shard name(s) in {label} {extra}; failing closed")
    missing = [shard_id for shard_id in required_shards if shard_id not in raw]
    if missing:
        raise SemanticFuseError(f"{label} missing required shards: {missing}")
    out: dict[str, float] = {}
    for shard_id in required_shards:
        value = _finite_number(raw[shard_id], field=f"{label}.{shard_id}")
        _require_nonnegative(value, field=f"{label}.{shard_id}")
        if maximum is not None and value > maximum:
            raise SemanticFuseError(
                f"{label}.{shard_id}={value} exceeds domain maximum {maximum}; failing closed"
            )
        out[shard_id] = value
    return out


def _pairs(values: Mapping[str, float], shards: tuple[str, ...]) -> tuple[tuple[str, float], ...]:
    return tuple((shard_id, values[shard_id]) for shard_id in shards)


def _clamp(value: float, lo: float, hi: float, *, field: str) -> float:
    if hi < lo:
        raise SemanticFuseError(f"{field} clamp bounds are inverted ({lo}, {hi}); failing closed")
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def packaged_fuse_v2(
    det_scores: Mapping[str, float],
    overlay: Mapping[str, float],
    **kwargs: Any,
) -> dict[str, float]:
    """Apply ``fused[s] = clamp(det[s] - overlay[s], 0, det[s])`` per required shard.

    Overlay values must be finite and nonnegative. Det scores must be finite
    and in ``[0, 1]``. Unknown extra shard names fail closed. This function
    does not apply packaged caps; caps are applied during aggregation.
    """
    _reject_authority_kwargs(kwargs, label="packaged_fuse_v2")
    required = REQUIRED_SHARD_IDS
    det = _score_map(det_scores, label="det", required_shards=required, maximum=1.0)
    over = _score_map(overlay, label="overlay", required_shards=required, maximum=None)
    fused: dict[str, float] = {}
    for shard_id in required:
        fused_value = _clamp(
            det[shard_id] - over[shard_id],
            0.0,
            det[shard_id],
            field=f"fused.{shard_id}",
        )
        if not math.isfinite(fused_value):
            raise SemanticFuseError(f"fused.{shard_id} is not finite; failing closed")
        if fused_value < 0 or fused_value > det[shard_id]:
            raise SemanticFuseError(
                f"fused.{shard_id}={fused_value} violates 0 <= fused <= det; failing closed"
            )
        fused[shard_id] = fused_value
    return fused


@dataclass(frozen=True)
class ConsumedFindingRecord:
    """Audit record for one bound finding after duplicate suppression."""

    finding_id: str
    class_id: str
    confidence_bin: str
    claim_fingerprint: str
    mapped_shards: tuple[str, ...]
    mapped_deltas: tuple[tuple[str, float], ...]
    suppressed: bool


@dataclass(frozen=True)
class PackagedFuseProvenance:
    """Structured audit trail. Not a policy input."""

    fuse_id: str
    equation: str
    det_scores: tuple[tuple[str, float], ...]
    findings_consumed: tuple[ConsumedFindingRecord, ...]
    findings_suppressed: tuple[ConsumedFindingRecord, ...]
    policy_map_artifact_id: str
    policy_map_schema_version: str
    policy_map_version: str
    policy_map_sha256: str
    policy_map_source: str
    taxonomy_version: str
    aggregate_overlay: tuple[tuple[str, float], ...]
    packaged_caps: tuple[tuple[str, float], ...]
    fused_scores: tuple[tuple[str, float], ...]

    def to_canonical_dict(self) -> dict[str, Any]:
        def _finding(record: ConsumedFindingRecord) -> dict[str, Any]:
            return {
                "finding_id": record.finding_id,
                "class_id": record.class_id,
                "confidence_bin": record.confidence_bin,
                "claim_fingerprint": record.claim_fingerprint,
                "mapped_shards": list(record.mapped_shards),
                "mapped_deltas": [[shard_id, value] for shard_id, value in record.mapped_deltas],
                "suppressed": record.suppressed,
            }

        return {
            "fuse_id": self.fuse_id,
            "equation": self.equation,
            "det_scores": [[shard_id, value] for shard_id, value in self.det_scores],
            "findings_consumed": [_finding(item) for item in self.findings_consumed],
            "findings_suppressed": [_finding(item) for item in self.findings_suppressed],
            "policy_map_artifact_id": self.policy_map_artifact_id,
            "policy_map_schema_version": self.policy_map_schema_version,
            "policy_map_version": self.policy_map_version,
            "policy_map_sha256": self.policy_map_sha256,
            "policy_map_source": self.policy_map_source,
            "taxonomy_version": self.taxonomy_version,
            "aggregate_overlay": [[shard_id, value] for shard_id, value in self.aggregate_overlay],
            "packaged_caps": [[shard_id, value] for shard_id, value in self.packaged_caps],
            "fused_scores": [[shard_id, value] for shard_id, value in self.fused_scores],
        }


@dataclass(frozen=True)
class PackagedFuseResult:
    det_scores: tuple[tuple[str, float], ...]
    overlay: tuple[tuple[str, float], ...]
    fused_scores: tuple[tuple[str, float], ...]
    provenance: PackagedFuseProvenance

    def det_map(self) -> dict[str, float]:
        return {shard_id: value for shard_id, value in self.det_scores}

    def overlay_map(self) -> dict[str, float]:
        return {shard_id: value for shard_id, value in self.overlay}

    def fused_map(self) -> dict[str, float]:
        return {shard_id: value for shard_id, value in self.fused_scores}

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "det_scores": [[shard_id, value] for shard_id, value in self.det_scores],
            "overlay": [[shard_id, value] for shard_id, value in self.overlay],
            "fused_scores": [[shard_id, value] for shard_id, value in self.fused_scores],
            "provenance": self.provenance.to_canonical_dict(),
        }

    def to_canonical_json(self) -> str:
        return json.dumps(self.to_canonical_dict(), sort_keys=True, separators=(",", ":"))


def _as_bound_findings(
    findings: BoundSemanticFindings | BoundFinding | Sequence[BoundFinding],
) -> tuple[BoundFinding, ...]:
    if isinstance(findings, BoundSemanticFindings):
        if findings.payload.status != "ok" and findings.findings:
            raise SemanticFuseError("non-ok findings must be empty; failing closed")
        return findings.findings
    if isinstance(findings, BoundFinding):
        return (findings,)
    if isinstance(findings, (str, bytes)) or not isinstance(findings, Sequence):
        raise SemanticFuseError(
            "findings must be BoundSemanticFindings or a BoundFinding sequence"
        )
    bound: list[BoundFinding] = []
    for index, item in enumerate(findings):
        if isinstance(item, Mapping):
            raise SemanticFuseError(
                f"findings[{index}] is a raw mapping; examiner dicts cannot "
                "supply routing, scores, or policy. Bind findings upstream."
            )
        if not isinstance(item, BoundFinding):
            raise SemanticFuseError(f"findings[{index}] is not a BoundFinding; failing closed")
        bound.append(item)
    return tuple(bound)


def _require_bound_finding(item: BoundFinding, *, index: int) -> BoundFinding:
    if not isinstance(item.finding, SemanticFinding):
        raise SemanticFuseError(f"findings[{index}].finding must be a SemanticFinding")
    fingerprint = item.claim_fingerprint
    if not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint):
        raise SemanticFuseError(
            f"findings[{index}].claim_fingerprint must be lowercase SHA-256 hex"
        )
    finding = item.finding
    if not isinstance(finding.finding_id, str) or not finding.finding_id:
        raise SemanticFuseError(f"findings[{index}].finding_id must be a non-empty string")
    if not isinstance(finding.class_id, str) or not finding.class_id:
        raise SemanticFuseError(f"findings[{index}].class_id must be a non-empty string")
    if finding.confidence_bin not in _CONFIDENCE_RANK:
        raise SemanticFuseError(
            f"findings[{index}].confidence_bin must be one of {list(CONFIDENCE_BINS)}"
        )
    return item


def _dedupe_findings(
    findings: tuple[BoundFinding, ...],
) -> tuple[tuple[BoundFinding, ...], tuple[BoundFinding, ...]]:
    seen_ids: set[str] = set()
    validated: list[BoundFinding] = []
    for index, item in enumerate(findings):
        bound = _require_bound_finding(item, index=index)
        finding_id = bound.finding.finding_id
        if finding_id in seen_ids:
            raise SemanticFuseError(f"Duplicate finding_id {finding_id!r}; failing closed")
        seen_ids.add(finding_id)
        validated.append(bound)

    groups: dict[tuple[str, str], list[BoundFinding]] = {}
    for item in validated:
        key = (item.finding.class_id, item.claim_fingerprint)
        groups.setdefault(key, []).append(item)

    survivors: list[BoundFinding] = []
    suppressed: list[BoundFinding] = []
    for key in sorted(groups):
        group = groups[key]

        def _rank(item: BoundFinding) -> tuple[int, str]:
            return (-_CONFIDENCE_RANK[item.finding.confidence_bin], item.finding.finding_id)

        ordered = sorted(group, key=_rank)
        survivors.append(ordered[0])
        suppressed.extend(ordered[1:])

    order = lambda item: (
        item.finding.class_id,
        item.claim_fingerprint,
        item.finding.finding_id,
    )
    return tuple(sorted(survivors, key=order)), tuple(sorted(suppressed, key=order))


def _index_policy_map(
    policy_map: FindingPolicyMapV1,
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, dict[str, dict[str, float]]],
    dict[str, float],
]:
    if policy_map.required_shards != REQUIRED_SHARD_IDS:
        raise SemanticFuseError(
            "required_shards must be exactly the frozen v0.1 shard ids "
            f"{list(REQUIRED_SHARD_IDS)}; failing closed"
        )
    if policy_map.confidence_bins != CONFIDENCE_BINS:
        raise SemanticFuseError(f"confidence_bins must be {list(CONFIDENCE_BINS)}")
    if policy_map.artifact_id != POLICY_MAP_ARTIFACT_ID:
        raise SemanticFuseError(f"artifact_id must be {POLICY_MAP_ARTIFACT_ID!r}")
    if policy_map.schema_version != POLICY_MAP_SCHEMA_VERSION:
        raise SemanticFuseError(
            f"schema_version must be {POLICY_MAP_SCHEMA_VERSION!r}"
        )
    if policy_map.version != TAXONOMY_VERSION:
        raise SemanticFuseError(f"policy map version must be {TAXONOMY_VERSION!r}")

    allowed = frozenset(REQUIRED_SHARD_IDS)
    caps: dict[str, float] = {}
    for item in policy_map.shard_caps:
        shard_id = _require_shard_id(item.shard_id, field="shard_caps", allowed=allowed)
        cap = _require_nonnegative(
            _finite_number(item.cap, field=f"shard_caps.{shard_id}.cap"),
            field=f"shard_caps.{shard_id}.cap",
        )
        if shard_id in caps:
            raise SemanticFuseError(f"Duplicate shard_caps entry for {shard_id!r}")
        caps[shard_id] = cap
    missing_caps = [shard_id for shard_id in REQUIRED_SHARD_IDS if shard_id not in caps]
    if missing_caps:
        raise SemanticFuseError(f"shard_caps missing required shards: {missing_caps}")

    route: dict[str, tuple[str, ...]] = {}
    overlays: dict[str, dict[str, dict[str, float]]] = {}
    if not policy_map.mappings:
        raise SemanticFuseError("policy map mappings must be non-empty; failing closed")
    for mapping in policy_map.mappings:
        if not isinstance(mapping.class_id, str) or not mapping.class_id:
            raise SemanticFuseError("mapping class_id must be a non-empty string")
        if mapping.class_id in route:
            raise SemanticFuseError(f"Duplicate mapping for class_id {mapping.class_id!r}")
        if not mapping.shards:
            raise SemanticFuseError(f"mappings.{mapping.class_id}.shards must be non-empty")
        shards: list[str] = []
        for shard_id in mapping.shards:
            checked = _require_shard_id(
                shard_id, field=f"mappings.{mapping.class_id}.shards", allowed=allowed
            )
            if checked in shards:
                raise SemanticFuseError(
                    f"mappings.{mapping.class_id}.shards has duplicate {checked!r}"
                )
            shards.append(checked)
        bins: dict[str, dict[str, float]] = {}
        present_bins = []
        for bin_name, deltas in mapping.overlay_deltas:
            if bin_name not in _CONFIDENCE_RANK:
                raise SemanticFuseError(
                    f"Unknown confidence_bin {bin_name!r} in mappings.{mapping.class_id}"
                )
            if bin_name in bins:
                raise SemanticFuseError(
                    f"Duplicate confidence_bin {bin_name!r} in mappings.{mapping.class_id}"
                )
            present_bins.append(bin_name)
            if not isinstance(deltas, Iterable):
                raise SemanticFuseError(
                    f"mappings.{mapping.class_id}.overlay_deltas.{bin_name} is malformed"
                )
            parsed: dict[str, float] = {}
            for item in deltas:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise SemanticFuseError(
                        f"malformed overlay delta in mappings.{mapping.class_id}.{bin_name}"
                    )
                shard_id, raw_delta = item
                checked = _require_shard_id(
                    shard_id,
                    field=f"mappings.{mapping.class_id}.overlay_deltas.{bin_name}",
                    allowed=allowed,
                )
                delta = _require_nonnegative(
                    _finite_number(
                        raw_delta,
                        field=f"overlay penalty for {mapping.class_id}/{bin_name}/{checked}",
                    ),
                    field=f"overlay penalty for {mapping.class_id}/{bin_name}/{checked}",
                )
                if delta > caps[checked]:
                    raise SemanticFuseError(
                        f"overlay penalty for {mapping.class_id}/{bin_name}/{checked}={delta} "
                        f"exceeds shard cap {caps[checked]}; failing closed"
                    )
                if checked in parsed:
                    raise SemanticFuseError(
                        f"duplicate overlay shard {checked!r} in "
                        f"mappings.{mapping.class_id}.{bin_name}"
                    )
                parsed[checked] = delta
            extra_overlay = sorted(set(parsed) - set(shards))
            if extra_overlay:
                raise SemanticFuseError(
                    f"Unknown extra shard name(s) {extra_overlay} in "
                    f"mappings.{mapping.class_id}.overlay_deltas.{bin_name}; failing closed"
                )
            missing_overlay = [shard_id for shard_id in shards if shard_id not in parsed]
            if missing_overlay:
                raise SemanticFuseError(
                    f"mappings.{mapping.class_id}.overlay_deltas.{bin_name} "
                    f"missing shards: {missing_overlay}"
                )
            bins[bin_name] = parsed
        missing_bins = [name for name in CONFIDENCE_BINS if name not in bins]
        if missing_bins:
            raise SemanticFuseError(
                f"mappings.{mapping.class_id}.overlay_deltas missing bins: {missing_bins}"
            )
        route[mapping.class_id] = tuple(shards)
        overlays[mapping.class_id] = bins
    return route, overlays, caps


def _load_json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SemanticFuseError(f"Malformed {label} JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemanticFuseError(f"{label} must be a JSON object")
    return payload


def _load_locked_packaged_map() -> tuple[FindingPolicyMapV1, str]:
    """Load the locked packaged map from the exact bytes used for the digest."""
    registry_bytes = packaged_finding_registry_bytes()
    registry_digest = _sha256_hex(registry_bytes)
    if registry_digest != LOCKED_REGISTRY_SHA256:
        raise SemanticFuseError(
            "packaged registry digest mismatch; failing closed"
        )
    map_bytes = packaged_finding_policy_map_bytes()
    map_digest = _sha256_hex(map_bytes)
    if map_digest != LOCKED_POLICY_MAP_SHA256:
        raise SemanticFuseError(
            "packaged policy-map digest mismatch; failing closed"
        )
    registry = validate_finding_registry_payload(
        _load_json_object(registry_bytes, label="finding_registry_v1"),
        sha256=registry_digest,
    )
    policy_map = validate_finding_policy_map_payload(
        _load_json_object(map_bytes, label="finding_policy_map_v1"),
        class_ids=registry.class_id_set(),
        sha256=map_digest,
    )
    return policy_map, map_digest


def _synthetic_map_digest(policy_map: FindingPolicyMapV1) -> str:
    """Digest of the mapping tables actually applied. Not the packaged file hash."""
    payload = {
        "artifact_id": policy_map.artifact_id,
        "confidence_bins": list(policy_map.confidence_bins),
        "mappings": {
            mapping.class_id: {
                "overlay_deltas": {
                    bin_name: {shard_id: value for shard_id, value in deltas}
                    for bin_name, deltas in mapping.overlay_deltas
                },
                "shards": list(mapping.shards),
            }
            for mapping in policy_map.mappings
        },
        "required_shards": list(policy_map.required_shards),
        "schema_version": policy_map.schema_version,
        "shard_caps": {item.shard_id: item.cap for item in policy_map.shard_caps},
        "version": policy_map.version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_hex(canonical)


def _record_for(
    item: BoundFinding,
    *,
    route: Mapping[str, tuple[str, ...]],
    overlays: Mapping[str, Mapping[str, Mapping[str, float]]],
    suppressed: bool,
) -> ConsumedFindingRecord:
    class_id = item.finding.class_id
    bin_name = item.finding.confidence_bin
    shards = route.get(class_id, ())
    deltas = overlays.get(class_id, {}).get(bin_name, {})
    mapped_deltas = tuple((shard_id, deltas[shard_id]) for shard_id in shards if shard_id in deltas)
    return ConsumedFindingRecord(
        finding_id=item.finding.finding_id,
        class_id=class_id,
        confidence_bin=bin_name,
        claim_fingerprint=item.claim_fingerprint,
        mapped_shards=tuple(shards),
        mapped_deltas=() if suppressed else mapped_deltas,
        suppressed=suppressed,
    )


def _fuse_bound_findings(
    det_scores: Mapping[str, float],
    findings: BoundSemanticFindings | BoundFinding | Sequence[BoundFinding],
    *,
    policy_map: FindingPolicyMapV1,
    policy_map_sha256: str,
    policy_map_source: str,
) -> PackagedFuseResult:
    """Apply C3 mapping + packaged_fuse_v2 using an already-resolved map.

    ``policy_map_sha256`` must be the digest of the bytes or canonical
    synthetic payload actually used. This function never reads
    ``FindingPolicyMapV1.sha256``.
    """
    if not isinstance(policy_map_sha256, str) or not _SHA256_RE.fullmatch(policy_map_sha256):
        raise SemanticFuseError("policy_map_sha256 must be lowercase SHA-256 hex")
    if policy_map_source not in {PACKAGED_SOURCE, SYNTHETIC_TEST_SOURCE}:
        raise SemanticFuseError("policy_map_source is not a recognized identity")
    if policy_map_source == PACKAGED_SOURCE and policy_map_sha256 != LOCKED_POLICY_MAP_SHA256:
        raise SemanticFuseError(
            "packaged provenance digest is not the locked policy-map identity; failing closed"
        )
    if policy_map_source == SYNTHETIC_TEST_SOURCE and policy_map_sha256 == LOCKED_POLICY_MAP_SHA256:
        raise SemanticFuseError(
            "synthetic test map cannot claim the locked packaged digest; failing closed"
        )
    route, overlays, caps = _index_policy_map(policy_map)
    required = policy_map.required_shards
    det = _score_map(det_scores, label="det", required_shards=required, maximum=1.0)
    bound = _as_bound_findings(findings)
    survivors, suppressed = _dedupe_findings(bound)

    aggregate = {shard_id: 0.0 for shard_id in required}
    for item in survivors:
        class_id = item.finding.class_id
        if class_id not in route or class_id not in overlays:
            raise SemanticFuseError(f"Unknown class_id {class_id!r}; failing closed")
        bin_name = item.finding.confidence_bin
        if bin_name not in overlays[class_id]:
            raise SemanticFuseError(
                f"Unmapped confidence_bin {bin_name!r} for class_id {class_id!r}; failing closed"
            )
        deltas = overlays[class_id][bin_name]
        extra_delta_shards = sorted(set(deltas) - set(required))
        if extra_delta_shards:
            raise SemanticFuseError(
                f"Unknown extra shard name(s) {extra_delta_shards} in packaged overlay; "
                "failing closed"
            )
        for shard_id in required:
            delta = deltas.get(shard_id, 0.0)
            penalty = _require_nonnegative(
                _finite_number(delta, field=f"overlay penalty for {class_id}/{bin_name}/{shard_id}"),
                field=f"overlay penalty for {class_id}/{bin_name}/{shard_id}",
            )
            aggregate[shard_id] += penalty

    capped = {}
    for shard_id in required:
        raw = _require_nonnegative(
            _finite_number(aggregate[shard_id], field=f"aggregate overlay.{shard_id}"),
            field=f"aggregate overlay.{shard_id}",
        )
        capped[shard_id] = min(raw, caps[shard_id])

    fused = packaged_fuse_v2(det, capped)
    det_pairs = _pairs(det, required)
    overlay_pairs = _pairs(capped, required)
    fused_pairs = _pairs(fused, required)
    cap_pairs = _pairs(caps, required)
    consumed_records = tuple(
        _record_for(item, route=route, overlays=overlays, suppressed=False) for item in survivors
    )
    suppressed_records = tuple(
        _record_for(item, route=route, overlays=overlays, suppressed=True) for item in suppressed
    )
    provenance = PackagedFuseProvenance(
        fuse_id=PACKAGED_FUSE_ID,
        equation=FUSE_EQUATION,
        det_scores=det_pairs,
        findings_consumed=consumed_records,
        findings_suppressed=suppressed_records,
        policy_map_artifact_id=policy_map.artifact_id,
        policy_map_schema_version=policy_map.schema_version,
        policy_map_version=policy_map.version,
        policy_map_sha256=policy_map_sha256,
        policy_map_source=policy_map_source,
        taxonomy_version=policy_map.version,
        aggregate_overlay=overlay_pairs,
        packaged_caps=cap_pairs,
        fused_scores=fused_pairs,
    )
    return PackagedFuseResult(
        det_scores=det_pairs,
        overlay=overlay_pairs,
        fused_scores=fused_pairs,
        provenance=provenance,
    )


def _map_and_fuse_v2_for_tests(
    det_scores: Mapping[str, float],
    findings: BoundSemanticFindings | BoundFinding | Sequence[BoundFinding],
    *,
    policy_map: FindingPolicyMapV1 | Mapping[str, Any],
    registry: FindingRegistryV1 | None = None,
) -> PackagedFuseResult:
    """Private unauthoritative helper for fail-closed / identity tests.

    Not exported from ``ai4.constrain``. Not a public policy-control surface.
    Provenance is marked ``synthetic-test`` and hashed from the synthetic
    payload actually supplied. It never reuses the locked packaged digest
    for a modified map, even if ``FindingPolicyMapV1.sha256`` still holds
    that digest after ``dataclasses.replace``.
    """
    if isinstance(policy_map, FindingPolicyMapV1):
        digest = _synthetic_map_digest(policy_map)
        return _fuse_bound_findings(
            det_scores,
            findings,
            policy_map=policy_map,
            policy_map_sha256=digest,
            policy_map_source=SYNTHETIC_TEST_SOURCE,
        )
    if isinstance(policy_map, Mapping):
        raw = dict(policy_map)
        digest = _sha256_hex(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        loaded_registry = registry if registry is not None else load_finding_registry_v1()
        loaded = validate_finding_policy_map_payload(
            raw, class_ids=loaded_registry.class_id_set(), sha256=digest
        )
        return _fuse_bound_findings(
            det_scores,
            findings,
            policy_map=loaded,
            policy_map_sha256=digest,
            policy_map_source=SYNTHETIC_TEST_SOURCE,
        )
    raise SemanticFuseError(
        "test helper policy_map must be FindingPolicyMapV1 or a JSON object"
    )


def map_and_fuse_v2(
    det_scores: Mapping[str, float],
    findings: BoundSemanticFindings | BoundFinding | Sequence[BoundFinding],
    **kwargs: Any,
) -> PackagedFuseResult:
    """Map bound findings through the locked packaged policy map and fuse.

    Public signature is ``(det_scores, findings)`` only. ``policy_map=`` and
    ``registry=`` are rejected. Packaged registry/policy-map bytes are loaded
    internally; provenance records the SHA-256 of those exact bytes.
    """
    _reject_authority_kwargs(kwargs, label="map_and_fuse_v2")
    loaded_map, map_digest = _load_locked_packaged_map()
    return _fuse_bound_findings(
        det_scores,
        findings,
        policy_map=loaded_map,
        policy_map_sha256=map_digest,
        policy_map_source=PACKAGED_SOURCE,
    )


__all__ = [
    "FUSE_EQUATION",
    "PACKAGED_FUSE_ID",
    "ConsumedFindingRecord",
    "PackagedFuseProvenance",
    "PackagedFuseResult",
    "map_and_fuse_v2",
    "packaged_fuse_v2",
]
