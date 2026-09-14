"""Immutable artifact continuity snapshot and drift detection (V07-3B §9).

Records locked identity hashes and role/config fingerprints. Drift
detection fails closed. 3B takes no governing action on drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain.semantic_examiner import LOCKED_OBSERVATION_PROMPT_SHA256
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION
from ai4.constrain.semantic_fuse import LOCKED_POLICY_MAP_SHA256, LOCKED_REGISTRY_SHA256, PACKAGED_FUSE_ID

SNAPSHOT_FIELDS = (
    "observation_prompt_sha256",
    "registry_sha256",
    "policy_map_sha256",
    "fuse_id",
    "examiner_config_identity",
    "examiner_provenance_identity",
    "proposer_identity",
    "evaluator_identity",
    "evaluator_fingerprint",
    "semantic_schema_version",
    "examiner_call_cap",
    "semantic_config_version",
)

LOCKED_SNAPSHOT_DEFAULTS = {
    "observation_prompt_sha256": LOCKED_OBSERVATION_PROMPT_SHA256,
    "registry_sha256": LOCKED_REGISTRY_SHA256,
    "policy_map_sha256": LOCKED_POLICY_MAP_SHA256,
    "fuse_id": PACKAGED_FUSE_ID,
    "semantic_schema_version": FINDINGS_SCHEMA_VERSION,
}


@dataclass(frozen=True)
class ArtifactContinuitySnapshot:
    """Immutable identity snapshot. Not a decision and not installable."""

    observation_prompt_sha256: str
    registry_sha256: str
    policy_map_sha256: str
    fuse_id: str
    examiner_config_identity: str
    examiner_provenance_identity: str
    proposer_identity: str
    evaluator_identity: str
    evaluator_fingerprint: str
    semantic_schema_version: str
    examiner_call_cap: int
    semantic_config_version: str

    def __post_init__(self) -> None:
        for field in SNAPSHOT_FIELDS:
            if field == "examiner_call_cap":
                value = self.examiner_call_cap
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise HybridExecutionAbort(
                        "schema_invalid",
                        "examiner_call_cap must be a nonnegative int",
                    )
                continue
            require_str(getattr(self, field), field=field)

    def to_dict(self) -> dict[str, str | int]:
        return {field: getattr(self, field) for field in SNAPSHOT_FIELDS}

    @classmethod
    def from_dict(cls, raw: object) -> ArtifactContinuitySnapshot:
        if not isinstance(raw, dict):
            raise HybridExecutionAbort("schema_invalid", "artifact snapshot must be an object")
        extra = sorted(str(key) for key in raw if key not in SNAPSHOT_FIELDS)
        if extra:
            raise HybridExecutionAbort("schema_invalid", f"unknown snapshot field(s) {extra}")
        missing = [key for key in SNAPSHOT_FIELDS if key not in raw]
        if missing:
            raise HybridExecutionAbort("schema_invalid", f"snapshot missing field(s) {missing}")
        return cls(
            observation_prompt_sha256=str(raw["observation_prompt_sha256"]),
            registry_sha256=str(raw["registry_sha256"]),
            policy_map_sha256=str(raw["policy_map_sha256"]),
            fuse_id=str(raw["fuse_id"]),
            examiner_config_identity=str(raw["examiner_config_identity"]),
            examiner_provenance_identity=str(raw["examiner_provenance_identity"]),
            proposer_identity=str(raw["proposer_identity"]),
            evaluator_identity=str(raw["evaluator_identity"]),
            evaluator_fingerprint=str(raw["evaluator_fingerprint"]),
            semantic_schema_version=str(raw["semantic_schema_version"]),
            examiner_call_cap=int(raw["examiner_call_cap"]),
            semantic_config_version=str(raw["semantic_config_version"]),
        )


def detect_identity_drift(
    expected: ArtifactContinuitySnapshot,
    observed: ArtifactContinuitySnapshot,
    **kwargs: Any,
) -> None:
    """Fail closed on any identity mismatch. No governing action."""
    reject_authority_kwargs(kwargs, label="detect_identity_drift")
    if not isinstance(expected, ArtifactContinuitySnapshot):
        raise HybridExecutionAbort("schema_invalid", "expected snapshot type mismatch")
    if not isinstance(observed, ArtifactContinuitySnapshot):
        raise HybridExecutionAbort("schema_invalid", "observed snapshot type mismatch")
    drifted = [
        field
        for field in SNAPSHOT_FIELDS
        if getattr(expected, field) != getattr(observed, field)
    ]
    if drifted:
        raise HybridExecutionAbort(
            "identity_drift",
            f"artifact continuity drift in {drifted}",
        )


def snapshot_from_context(context: object, **kwargs: Any) -> ArtifactContinuitySnapshot:
    reject_authority_kwargs(kwargs, label="snapshot_from_context")
    snapshot = getattr(context, "identity_snapshot", None)
    if not isinstance(snapshot, ArtifactContinuitySnapshot):
        raise HybridExecutionAbort("schema_invalid", "context is missing identity_snapshot")
    return snapshot


def assert_locked_artifact_hashes(snapshot: ArtifactContinuitySnapshot, **kwargs: Any) -> None:
    reject_authority_kwargs(kwargs, label="assert_locked_artifact_hashes")
    if snapshot.observation_prompt_sha256 != LOCKED_OBSERVATION_PROMPT_SHA256:
        raise HybridExecutionAbort("observation_prompt_hash_mismatch", "observation prompt hash drift")
    if snapshot.registry_sha256 != LOCKED_REGISTRY_SHA256:
        raise HybridExecutionAbort("registry_hash_mismatch", "registry hash drift")
    if snapshot.policy_map_sha256 != LOCKED_POLICY_MAP_SHA256:
        raise HybridExecutionAbort("policy_map_hash_mismatch", "policy map hash drift")
    if snapshot.fuse_id != PACKAGED_FUSE_ID:
        raise HybridExecutionAbort("identity_drift", "fuse id drift")


__all__ = [
    "ArtifactContinuitySnapshot",
    "LOCKED_SNAPSHOT_DEFAULTS",
    "SNAPSHOT_FIELDS",
    "assert_locked_artifact_hashes",
    "detect_identity_drift",
    "snapshot_from_context",
]
