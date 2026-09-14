"""Inert semantic report blocks (V07-3A §7).

Success and abort blocks with a closed field set. They must not carry
governing decision, passed, threshold, arbitration, or terminal control.
They are not wired into live DecisionReport serialization (product
reports stay schema 0.1.0 / OFF behavior).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HYBRID_ABORT_CLASSES, HybridExecutionAbort

SEMANTIC_BLOCK_SCHEMA_VERSION = "ai4.semantic_report.v0.7-3a"
BLOCK_KIND_SUCCESS = "success"
BLOCK_KIND_ABORT = "abort"
VISIBILITY_PUBLIC = "public"
VISIBILITY_INTERNAL = "internal"
SUCCESS_STATUS_OK = "ok"

FORBIDDEN_SEMANTIC_REPORT_FIELDS = frozenset(
    {
        "accept",
        "action",
        "arbitration",
        "decision",
        "passed",
        "refuse",
        "revise",
        "revision_targets",
        "terminal",
        "threshold",
        "thresholds",
        "verdict",
    }
)

SUCCESS_PUBLIC_FIELDS = (
    "block_kind",
    "schema_version",
    "status",
    "findings_count",
    "observation_prompt_sha256",
    "registry_sha256",
    "policy_map_sha256",
    "visibility",
)
SUCCESS_INTERNAL_FIELDS = (
    "examiner_id",
    "examiner_version",
    "provider_id",
    "model_id",
)
ABORT_PUBLIC_FIELDS = (
    "block_kind",
    "schema_version",
    "abort_class",
    "visibility",
)
ABORT_INTERNAL_FIELDS = (
    "detail",
    "examiner_id",
    "examiner_version",
    "provider_id",
    "model_id",
)


def _reject_forbidden(raw: Mapping[str, Any], *, label: str) -> None:
    blocked = sorted(str(key) for key in raw if key in FORBIDDEN_SEMANTIC_REPORT_FIELDS)
    if blocked:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"{label} cannot carry governing field(s) {blocked}",
        )


def _optional_str(raw: object, *, field: str) -> str | None:
    if raw is None:
        return None
    return require_str(raw, field=field)


def _require_count(raw: object, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise HybridExecutionAbort("schema_invalid", f"{field} must be a nonnegative int")
    return raw


@dataclass(frozen=True)
class SemanticSuccessBlock:
    """Closed success semantic audit block. Not a decision."""

    findings_count: int
    observation_prompt_sha256: str
    registry_sha256: str
    policy_map_sha256: str
    examiner_id: str | None = None
    examiner_version: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    status: str = SUCCESS_STATUS_OK
    schema_version: str = SEMANTIC_BLOCK_SCHEMA_VERSION
    block_kind: str = BLOCK_KIND_SUCCESS

    def __post_init__(self) -> None:
        if self.block_kind != BLOCK_KIND_SUCCESS:
            raise HybridExecutionAbort("schema_invalid", "success block_kind mismatch")
        if self.schema_version != SEMANTIC_BLOCK_SCHEMA_VERSION:
            raise HybridExecutionAbort("schema_invalid", "semantic block schema mismatch")
        if self.status != SUCCESS_STATUS_OK:
            raise HybridExecutionAbort("schema_invalid", "success status must be ok")
        _require_count(self.findings_count, field="findings_count")
        require_str(self.observation_prompt_sha256, field="observation_prompt_sha256")
        require_str(self.registry_sha256, field="registry_sha256")
        require_str(self.policy_map_sha256, field="policy_map_sha256")
        _optional_str(self.examiner_id, field="examiner_id")
        _optional_str(self.examiner_version, field="examiner_version")
        _optional_str(self.provider_id, field="provider_id")
        _optional_str(self.model_id, field="model_id")

    def to_dict(self, *, visibility: str = VISIBILITY_INTERNAL) -> dict[str, Any]:
        if visibility not in {VISIBILITY_PUBLIC, VISIBILITY_INTERNAL}:
            raise HybridExecutionAbort("schema_invalid", "unknown visibility")
        payload: dict[str, Any] = {
            "block_kind": self.block_kind,
            "schema_version": self.schema_version,
            "status": self.status,
            "findings_count": self.findings_count,
            "observation_prompt_sha256": self.observation_prompt_sha256,
            "registry_sha256": self.registry_sha256,
            "policy_map_sha256": self.policy_map_sha256,
            "visibility": visibility,
        }
        if visibility == VISIBILITY_INTERNAL:
            payload["examiner_id"] = self.examiner_id
            payload["examiner_version"] = self.examiner_version
            payload["provider_id"] = self.provider_id
            payload["model_id"] = self.model_id
        _reject_forbidden(payload, label="SemanticSuccessBlock")
        return payload


@dataclass(frozen=True)
class SemanticAbortBlock:
    """Closed abort semantic audit block. Not a terminal decision."""

    abort_class: str
    detail: str | None = None
    examiner_id: str | None = None
    examiner_version: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    schema_version: str = SEMANTIC_BLOCK_SCHEMA_VERSION
    block_kind: str = BLOCK_KIND_ABORT

    def __post_init__(self) -> None:
        if self.block_kind != BLOCK_KIND_ABORT:
            raise HybridExecutionAbort("schema_invalid", "abort block_kind mismatch")
        if self.schema_version != SEMANTIC_BLOCK_SCHEMA_VERSION:
            raise HybridExecutionAbort("schema_invalid", "semantic block schema mismatch")
        if self.abort_class not in HYBRID_ABORT_CLASSES:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"abort_class {self.abort_class!r} is not in the closed vocabulary",
            )
        _optional_str(self.detail, field="detail")
        _optional_str(self.examiner_id, field="examiner_id")
        _optional_str(self.examiner_version, field="examiner_version")
        _optional_str(self.provider_id, field="provider_id")
        _optional_str(self.model_id, field="model_id")

    def to_dict(self, *, visibility: str = VISIBILITY_INTERNAL) -> dict[str, Any]:
        if visibility not in {VISIBILITY_PUBLIC, VISIBILITY_INTERNAL}:
            raise HybridExecutionAbort("schema_invalid", "unknown visibility")
        payload: dict[str, Any] = {
            "block_kind": self.block_kind,
            "schema_version": self.schema_version,
            "abort_class": self.abort_class,
            "visibility": visibility,
        }
        if visibility == VISIBILITY_INTERNAL:
            payload["detail"] = self.detail
            payload["examiner_id"] = self.examiner_id
            payload["examiner_version"] = self.examiner_version
            payload["provider_id"] = self.provider_id
            payload["model_id"] = self.model_id
        _reject_forbidden(payload, label="SemanticAbortBlock")
        return payload


def redact_semantic_block(
    block: SemanticSuccessBlock | SemanticAbortBlock | Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Public projection. Internal examiner labels are omitted."""
    reject_authority_kwargs(kwargs, label="redact_semantic_block")
    if isinstance(block, (SemanticSuccessBlock, SemanticAbortBlock)):
        return block.to_dict(visibility=VISIBILITY_PUBLIC)
    if not isinstance(block, Mapping):
        raise HybridExecutionAbort("schema_invalid", "redact_semantic_block needs a semantic block")
    _reject_forbidden(block, label="redact_semantic_block")
    kind = block.get("block_kind")
    if kind == BLOCK_KIND_SUCCESS:
        return {key: block[key] for key in SUCCESS_PUBLIC_FIELDS if key in block} | {
            "visibility": VISIBILITY_PUBLIC
        }
    if kind == BLOCK_KIND_ABORT:
        return {key: block[key] for key in ABORT_PUBLIC_FIELDS if key in block} | {
            "visibility": VISIBILITY_PUBLIC
        }
    raise HybridExecutionAbort("schema_invalid", "unknown semantic block_kind")


__all__ = [
    "ABORT_INTERNAL_FIELDS",
    "ABORT_PUBLIC_FIELDS",
    "BLOCK_KIND_ABORT",
    "BLOCK_KIND_SUCCESS",
    "FORBIDDEN_SEMANTIC_REPORT_FIELDS",
    "SEMANTIC_BLOCK_SCHEMA_VERSION",
    "SUCCESS_INTERNAL_FIELDS",
    "SUCCESS_PUBLIC_FIELDS",
    "SemanticAbortBlock",
    "SemanticSuccessBlock",
    "VISIBILITY_INTERNAL",
    "VISIBILITY_PUBLIC",
    "redact_semantic_block",
]
