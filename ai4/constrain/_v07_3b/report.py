"""Semantic DecisionReport schema 0.2.0 (V07-3B §7).

Additive schema / parser / redaction for semantic success and abort
blocks, deterministic / overlay / fused score maps, finding IDs/codes,
runtime claim fingerprints, artifact hashes, and provenance evidence.

Semantic blocks cannot set decision, threshold, passed, arbitration, or
terminal. Public redaction omits secrets and sensitive infra. ``semantic``
must not be JSON ``null``. Product paths do not emit 0.2.0 reports.

Existing OFF ``DecisionReport`` serialization is unchanged unless a
caller constructs an explicit 0.2.0 object through this internal module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HYBRID_ABORT_CLASSES, HybridExecutionAbort
from ai4.constrain._v07_3a.report import FORBIDDEN_SEMANTIC_REPORT_FIELDS
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import REPORT_SCHEMA_VERSION
from ai4.constrain.semantic_taxonomy import load_finding_registry_v1
from ai4.constrain._v07_3b.provenance import (
    PROVENANCE_CLAIMS,
    ProvenanceClaim,
    ProvenanceEvidenceBundle,
    bundle_claims,
    collect_account_observed,
    collect_configured,
    collect_origin_allowlisted,
    collect_provider_session_bound,
    collect_served_model_observed,
    collect_transport_bound,
)

REPORT_SCHEMA_VERSION_0_1_0 = "0.1.0"
REPORT_SCHEMA_VERSION_0_2_0 = "0.2.0"
SEMANTIC_DOCUMENT_SCHEMA_VERSION = "ai4.semantic_report.v0.7-3b"
BLOCK_KIND_SUCCESS = "success"
BLOCK_KIND_ABORT = "abort"
VISIBILITY_PUBLIC = "public"
VISIBILITY_INTERNAL = "internal"

_SCORE_MAP_NAMES = ("deterministic", "overlay", "fused")
_FINDING_AUDIT_KEYS = ("finding_id", "class_id", "observation_code")
_PUBLIC_SEMANTIC_KEYS = (
    "block_kind",
    "schema_version",
    "status",
    "abort_class",
    "findings_count",
    "finding_ids",
    "class_ids",
    "observation_codes",
    "observation_prompt_sha256",
    "registry_sha256",
    "policy_map_sha256",
    "score_maps",
    "visibility",
)
_INTERNAL_ONLY_KEYS = frozenset(
    {
        "examiner_id",
        "examiner_version",
        "provider_id",
        "model_id",
        "claim_fingerprints",
        "provenance",
        "detail",
        "origin",
        "account",
        "api_base",
        "api_key",
    }
)
_COLLECTORS = {
    "configured": collect_configured,
    "transport_bound": collect_transport_bound,
    "origin_allowlisted": collect_origin_allowlisted,
    "provider_session_bound": collect_provider_session_bound,
    "served_model_observed": collect_served_model_observed,
    "account_observed": collect_account_observed,
}


def _reject_forbidden(raw: Mapping[str, Any], *, label: str) -> None:
    blocked = sorted(str(key) for key in raw if key in FORBIDDEN_SEMANTIC_REPORT_FIELDS)
    if blocked:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"{label} cannot carry governing field(s) {blocked}",
        )


def _require_count(raw: object, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise HybridExecutionAbort("schema_invalid", f"{field} must be a nonnegative int")
    return raw


def _score_map(raw: object, *, label: str) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise HybridExecutionAbort("schema_invalid", f"{label} must be an object")
    extra = sorted(str(key) for key in raw if key not in REQUIRED_IDS)
    missing = [shard_id for shard_id in REQUIRED_IDS if shard_id not in raw]
    if extra or missing:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"{label} shard set mismatch; missing={missing}, extra={extra}",
        )
    out: dict[str, float] = {}
    for shard_id in REQUIRED_IDS:
        value = raw[shard_id]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HybridExecutionAbort("schema_invalid", f"{label}.{shard_id} must be a number")
        number = float(value)
        if number != number or number in {float("inf"), float("-inf")}:  # NaN / Inf
            raise HybridExecutionAbort("schema_invalid", f"{label}.{shard_id} must be finite")
        out[shard_id] = number
    return out


@dataclass(frozen=True)
class FindingAudit:
    finding_id: str
    class_id: str
    observation_code: str

    def __post_init__(self) -> None:
        require_str(self.finding_id, field="finding_id")
        require_str(self.class_id, field="class_id")
        require_str(self.observation_code, field="observation_code")
        registry = load_finding_registry_v1()
        if self.class_id not in registry.class_id_set():
            raise HybridExecutionAbort("schema_invalid", f"unknown class_id {self.class_id!r}")
        if self.observation_code not in registry.observation_code_set():
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unknown observation_code {self.observation_code!r}",
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "finding_id": self.finding_id,
            "class_id": self.class_id,
            "observation_code": self.observation_code,
        }


@dataclass(frozen=True)
class SemanticDocument:
    """Closed semantic audit document. Not a DecisionReport decision."""

    block_kind: str
    observation_prompt_sha256: str
    registry_sha256: str
    policy_map_sha256: str
    score_maps: dict[str, dict[str, float]]
    findings: tuple[FindingAudit, ...]
    claim_fingerprints: tuple[str, ...]
    provenance: ProvenanceEvidenceBundle
    status: str | None = None
    abort_class: str | None = None
    detail: str | None = None
    examiner_id: str | None = None
    examiner_version: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    schema_version: str = SEMANTIC_DOCUMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_DOCUMENT_SCHEMA_VERSION:
            raise HybridExecutionAbort("schema_invalid", "semantic document schema mismatch")
        if self.block_kind == BLOCK_KIND_SUCCESS:
            if self.status != "ok":
                raise HybridExecutionAbort("schema_invalid", "success status must be ok")
            if self.abort_class is not None:
                raise HybridExecutionAbort("schema_invalid", "success block cannot carry abort_class")
        elif self.block_kind == BLOCK_KIND_ABORT:
            if self.abort_class not in HYBRID_ABORT_CLASSES:
                raise HybridExecutionAbort(
                    "schema_invalid",
                    f"abort_class {self.abort_class!r} is not in the closed vocabulary",
                )
            if self.status is not None:
                raise HybridExecutionAbort("schema_invalid", "abort block cannot carry success status")
        else:
            raise HybridExecutionAbort("schema_invalid", f"unknown block_kind {self.block_kind!r}")
        require_str(self.observation_prompt_sha256, field="observation_prompt_sha256")
        require_str(self.registry_sha256, field="registry_sha256")
        require_str(self.policy_map_sha256, field="policy_map_sha256")
        if set(self.score_maps) != set(_SCORE_MAP_NAMES):
            raise HybridExecutionAbort("schema_invalid", "score_maps must be deterministic/overlay/fused")
        for name in _SCORE_MAP_NAMES:
            _score_map(self.score_maps[name], label=f"score_maps.{name}")
        if not isinstance(self.findings, tuple):
            raise HybridExecutionAbort("schema_invalid", "findings must be a tuple")
        if not isinstance(self.claim_fingerprints, tuple):
            raise HybridExecutionAbort("schema_invalid", "claim_fingerprints must be a tuple")
        for item in self.claim_fingerprints:
            require_str(item, field="claim_fingerprint")
        if not isinstance(self.provenance, ProvenanceEvidenceBundle):
            raise HybridExecutionAbort("schema_invalid", "provenance type mismatch")
        if self.block_kind == BLOCK_KIND_SUCCESS and len(self.findings) == 0 and self.status != "ok":
            raise HybridExecutionAbort("schema_invalid", "success findings/status inconsistent")

    @property
    def findings_count(self) -> int:
        return len(self.findings)

    def to_dict(self, *, visibility: str = VISIBILITY_INTERNAL) -> dict[str, Any]:
        if visibility not in {VISIBILITY_PUBLIC, VISIBILITY_INTERNAL}:
            raise HybridExecutionAbort("schema_invalid", "unknown visibility")
        payload: dict[str, Any] = {
            "block_kind": self.block_kind,
            "schema_version": self.schema_version,
            "findings_count": self.findings_count,
            "finding_ids": [item.finding_id for item in self.findings],
            "class_ids": [item.class_id for item in self.findings],
            "observation_codes": [item.observation_code for item in self.findings],
            "observation_prompt_sha256": self.observation_prompt_sha256,
            "registry_sha256": self.registry_sha256,
            "policy_map_sha256": self.policy_map_sha256,
            "score_maps": {name: dict(self.score_maps[name]) for name in _SCORE_MAP_NAMES},
            "visibility": visibility,
        }
        if self.block_kind == BLOCK_KIND_SUCCESS:
            payload["status"] = self.status
        else:
            payload["abort_class"] = self.abort_class
        if visibility == VISIBILITY_INTERNAL:
            payload["findings"] = [item.to_dict() for item in self.findings]
            payload["claim_fingerprints"] = list(self.claim_fingerprints)
            payload["provenance"] = [
                {"claim": item.claim, "value": item.value, "minted_by": item.minted_by}
                for item in self.provenance.claims
            ]
            payload["examiner_id"] = self.examiner_id
            payload["examiner_version"] = self.examiner_version
            payload["provider_id"] = self.provider_id
            payload["model_id"] = self.model_id
            payload["detail"] = self.detail
        _reject_forbidden(payload, label="SemanticDocument")
        return payload


def redact_semantic_document(
    document: SemanticDocument | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    reject_authority_kwargs(kwargs, label="redact_semantic_document")
    if isinstance(document, SemanticDocument):
        payload = document.to_dict(visibility=VISIBILITY_PUBLIC)
    elif isinstance(document, Mapping):
        _reject_forbidden(document, label="redact_semantic_document")
        payload = {key: document[key] for key in _PUBLIC_SEMANTIC_KEYS if key in document}
        payload["visibility"] = VISIBILITY_PUBLIC
    else:
        raise HybridExecutionAbort("schema_invalid", "redact_semantic_document needs a semantic document")
    leaked = sorted(key for key in payload if key in _INTERNAL_ONLY_KEYS)
    if leaked:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"public redaction leaked infra field(s) {leaked}",
        )
    return payload


def parse_semantic_document(raw: object, **kwargs: Any) -> SemanticDocument:
    reject_authority_kwargs(kwargs, label="parse_semantic_document")
    if raw is None:
        raise HybridExecutionAbort("schema_invalid", "semantic cannot be null")
    if not isinstance(raw, Mapping):
        raise HybridExecutionAbort("schema_invalid", "semantic must be an object")
    _reject_forbidden(raw, label="semantic")
    if raw.get("schema_version") != SEMANTIC_DOCUMENT_SCHEMA_VERSION:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"unsupported semantic schema_version {raw.get('schema_version')!r}",
        )
    findings_raw = raw.get("findings", [])
    if findings_raw is None:
        raise HybridExecutionAbort("schema_invalid", "findings must be an array")
    if not isinstance(findings_raw, list):
        raise HybridExecutionAbort("schema_invalid", "findings must be an array")
    findings = []
    for item in findings_raw:
        if not isinstance(item, Mapping):
            raise HybridExecutionAbort("schema_invalid", "finding entries must be objects")
        extra = sorted(str(key) for key in item if key not in _FINDING_AUDIT_KEYS)
        if extra:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"finding audit rejected extra field(s) {extra}",
            )
        findings.append(
            FindingAudit(
                finding_id=str(item["finding_id"]),
                class_id=str(item["class_id"]),
                observation_code=str(item["observation_code"]),
            )
        )
    maps_raw = raw.get("score_maps")
    if not isinstance(maps_raw, Mapping):
        raise HybridExecutionAbort("schema_invalid", "score_maps must be an object")
    score_maps = {name: _score_map(maps_raw.get(name), label=f"score_maps.{name}") for name in _SCORE_MAP_NAMES}
    fingerprints = raw.get("claim_fingerprints", [])
    if fingerprints is None:
        fingerprints = []
    if not isinstance(fingerprints, list):
        raise HybridExecutionAbort("schema_invalid", "claim_fingerprints must be an array")
    provenance = _parse_provenance(raw.get("provenance") or [])
    return SemanticDocument(
        block_kind=str(raw.get("block_kind") or ""),
        schema_version=str(raw.get("schema_version") or ""),
        status=raw.get("status"),
        abort_class=raw.get("abort_class"),
        detail=raw.get("detail"),
        observation_prompt_sha256=str(raw.get("observation_prompt_sha256") or ""),
        registry_sha256=str(raw.get("registry_sha256") or ""),
        policy_map_sha256=str(raw.get("policy_map_sha256") or ""),
        score_maps=score_maps,
        findings=tuple(findings),
        claim_fingerprints=tuple(str(item) for item in fingerprints),
        provenance=provenance,
        examiner_id=raw.get("examiner_id"),
        examiner_version=raw.get("examiner_version"),
        provider_id=raw.get("provider_id"),
        model_id=raw.get("model_id"),
    )


def _parse_provenance(raw: object) -> ProvenanceEvidenceBundle:
    if not isinstance(raw, list):
        raise HybridExecutionAbort("schema_invalid", "provenance must be an array")
    claims: list[ProvenanceClaim] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise HybridExecutionAbort("schema_invalid", "provenance entries must be objects")
        name = str(item.get("claim") or "")
        if name not in PROVENANCE_CLAIMS:
            raise HybridExecutionAbort("schema_invalid", f"unknown provenance claim {name!r}")
        collector = _COLLECTORS[name]
        value = item.get("value")
        if value is None:
            raise HybridExecutionAbort("schema_invalid", f"provenance {name} value is required")
        claims.append(collector(str(value)))
    return bundle_claims(claims)


@dataclass(frozen=True)
class HybridReportDocument:
    schema_version: str
    off_report: DecisionReport
    semantic: SemanticDocument | None

    def __post_init__(self) -> None:
        if self.schema_version not in {REPORT_SCHEMA_VERSION_0_1_0, REPORT_SCHEMA_VERSION_0_2_0}:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unsupported report schema_version {self.schema_version!r}",
            )
        if not isinstance(self.off_report, DecisionReport):
            raise HybridExecutionAbort("schema_invalid", "off_report type mismatch")
        if self.schema_version == REPORT_SCHEMA_VERSION_0_1_0 and self.semantic is not None:
            raise HybridExecutionAbort(
                "schema_invalid",
                "0.1.0 OFF reports cannot carry a semantic document",
            )
        if self.semantic is not None and not isinstance(self.semantic, SemanticDocument):
            raise HybridExecutionAbort("schema_invalid", "semantic type mismatch")


def parse_decision_report_document(raw: object, **kwargs: Any) -> HybridReportDocument:
    reject_authority_kwargs(kwargs, label="parse_decision_report_document")
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HybridExecutionAbort("schema_invalid", f"malformed report JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise HybridExecutionAbort("schema_invalid", "report document must be an object")
    schema = str(raw.get("schema_version") or "")
    if schema == REPORT_SCHEMA_VERSION_0_1_0:
        if "semantic" in raw:
            if raw["semantic"] is None:
                raise HybridExecutionAbort("schema_invalid", "semantic cannot be null")
            raise HybridExecutionAbort(
                "schema_invalid",
                "0.1.0 report carries semantic identity; refusing silent drop",
            )
        try:
            report = DecisionReport.from_dict(raw)
        except ConstraintExecutionError as exc:
            raise HybridExecutionAbort("schema_invalid", str(exc)) from exc
        return HybridReportDocument(schema_version=schema, off_report=report, semantic=None)
    if schema != REPORT_SCHEMA_VERSION_0_2_0:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"unsupported report schema_version {schema!r}",
        )
    if "semantic" not in raw:
        raise HybridExecutionAbort("schema_invalid", "0.2.0 report requires a semantic object")
    if raw["semantic"] is None:
        raise HybridExecutionAbort("schema_invalid", "semantic cannot be null")
    off_payload = dict(raw)
    off_payload["schema_version"] = REPORT_SCHEMA_VERSION
    off_payload.pop("semantic", None)
    try:
        report = DecisionReport.from_dict(off_payload)
    except ConstraintExecutionError as exc:
        raise HybridExecutionAbort("schema_invalid", str(exc)) from exc
    return HybridReportDocument(
        schema_version=REPORT_SCHEMA_VERSION_0_2_0,
        off_report=report,
        semantic=parse_semantic_document(raw["semantic"]),
    )


def serialize_decision_report_document(document: HybridReportDocument, **kwargs: Any) -> dict[str, Any]:
    reject_authority_kwargs(kwargs, label="serialize_decision_report_document")
    if not isinstance(document, HybridReportDocument):
        raise HybridExecutionAbort("schema_invalid", "serialize needs HybridReportDocument")
    if document.schema_version == REPORT_SCHEMA_VERSION_0_1_0:
        return document.off_report.to_dict()
    payload = document.off_report.to_dict()
    payload["schema_version"] = REPORT_SCHEMA_VERSION_0_2_0
    if document.semantic is None:
        raise HybridExecutionAbort("schema_invalid", "semantic cannot be null")
    payload["semantic"] = document.semantic.to_dict()
    return payload


def serialize_decision_report_json(document: HybridReportDocument, **kwargs: Any) -> str:
    reject_authority_kwargs(kwargs, label="serialize_decision_report_json")
    if document.schema_version == REPORT_SCHEMA_VERSION_0_1_0:
        return document.off_report.to_json()
    return json.dumps(serialize_decision_report_document(document), indent=2, ensure_ascii=False)


__all__ = [
    "BLOCK_KIND_ABORT",
    "BLOCK_KIND_SUCCESS",
    "FindingAudit",
    "HybridReportDocument",
    "REPORT_SCHEMA_VERSION_0_1_0",
    "REPORT_SCHEMA_VERSION_0_2_0",
    "SEMANTIC_DOCUMENT_SCHEMA_VERSION",
    "SemanticDocument",
    "VISIBILITY_INTERNAL",
    "VISIBILITY_PUBLIC",
    "parse_decision_report_document",
    "parse_semantic_document",
    "redact_semantic_document",
    "serialize_decision_report_document",
    "serialize_decision_report_json",
]
