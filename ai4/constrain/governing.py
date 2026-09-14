"""Product-owned typed/versioned governing-integration config (V07-3C).

This is the only approved activation surface for ``api.run`` hybrid
governance. Default remains absent (OFF). Presence of a validated
``GoverningIntegration`` on ``RuntimeConfig.integration`` feeds
``HybridConfiguration``; it is not runtime-observed provenance, not a
Ready object, and not an install bit.

No environment switch, undocumented ``run()`` kwarg, or caller-created
Ready can activate governance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.semantic_examiner import LOCKED_OBSERVATION_PROMPT_SHA256
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION
from ai4.constrain.semantic_fuse import (
    LOCKED_POLICY_MAP_SHA256,
    LOCKED_REGISTRY_SHA256,
    PACKAGED_FUSE_ID,
)

GOVERNING_INTEGRATION_VERSION = "v07.3c.0"
SEMANTIC_CONFIG_VERSION_3C = "v07.3c.0"


@dataclass(frozen=True)
class GoverningIntegration:
    """Typed product config. Not observed evidence and not a Ready/install."""

    proposer_provider_id: str
    proposer_model_id: str
    examiner_provider_id: str
    examiner_model_id: str
    examiner_id: str
    examiner_version: str
    origin_allowlist: tuple[str, ...]
    proposer_requested_origin: str
    examiner_requested_origin: str
    max_usd: float
    max_proposal_completions: int
    max_examiner_calls: int
    session_id: str
    session_dir: str
    examiner_backend: object
    version: str = GOVERNING_INTEGRATION_VERSION
    observation_prompt_sha256: str = LOCKED_OBSERVATION_PROMPT_SHA256
    registry_sha256: str = LOCKED_REGISTRY_SHA256
    policy_map_sha256: str = LOCKED_POLICY_MAP_SHA256
    fuse_id: str = PACKAGED_FUSE_ID
    semantic_schema_version: str = FINDINGS_SCHEMA_VERSION
    semantic_config_version: str = SEMANTIC_CONFIG_VERSION_3C
    reserve_usd_proposal: float = 0.0
    reserve_usd_examiner: float = 0.0
    proposer_credential: str | None = None
    examiner_credential: str | None = None
    persist_store: object | None = None
    report_store: object | None = None
    clock: object | None = None

    def validate(self) -> GoverningIntegration:
        if self.version != GOVERNING_INTEGRATION_VERSION:
            raise ConstraintExecutionError(
                f"Unknown governing integration version {self.version!r}. "
                f"Expected {GOVERNING_INTEGRATION_VERSION}."
            )
        for field in (
            "proposer_provider_id",
            "proposer_model_id",
            "examiner_provider_id",
            "examiner_model_id",
            "examiner_id",
            "examiner_version",
            "proposer_requested_origin",
            "examiner_requested_origin",
            "session_id",
            "session_dir",
            "observation_prompt_sha256",
            "registry_sha256",
            "policy_map_sha256",
            "fuse_id",
            "semantic_schema_version",
            "semantic_config_version",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ConstraintExecutionError(f"GoverningIntegration.{field} must be a non-empty string")
        if not isinstance(self.origin_allowlist, tuple) or not self.origin_allowlist:
            raise ConstraintExecutionError("GoverningIntegration.origin_allowlist must be a non-empty tuple")
        for origin in self.origin_allowlist:
            if not isinstance(origin, str) or not origin:
                raise ConstraintExecutionError("origin_allowlist entries must be non-empty strings")
        if self.examiner_backend is None or not callable(
            getattr(self.examiner_backend, "observe", None)
        ):
            raise ConstraintExecutionError(
                "GoverningIntegration.examiner_backend must implement observe(request)"
            )
        for field in ("max_proposal_completions", "max_examiner_calls"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConstraintExecutionError(f"GoverningIntegration.{field} must be a nonnegative int")
        for field in ("max_usd", "reserve_usd_proposal", "reserve_usd_examiner"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ConstraintExecutionError(f"GoverningIntegration.{field} must be a nonnegative number")
        if self.observation_prompt_sha256 != LOCKED_OBSERVATION_PROMPT_SHA256:
            raise ConstraintExecutionError("GoverningIntegration observation prompt hash is not the locked artifact")
        if self.registry_sha256 != LOCKED_REGISTRY_SHA256:
            raise ConstraintExecutionError("GoverningIntegration registry hash is not the locked artifact")
        if self.policy_map_sha256 != LOCKED_POLICY_MAP_SHA256:
            raise ConstraintExecutionError("GoverningIntegration policy map hash is not the locked artifact")
        if self.fuse_id != PACKAGED_FUSE_ID:
            raise ConstraintExecutionError("GoverningIntegration fuse_id must remain packaged_fuse_v2")
        if self.semantic_schema_version != FINDINGS_SCHEMA_VERSION:
            raise ConstraintExecutionError("GoverningIntegration semantic schema version mismatch")
        if self.semantic_config_version != SEMANTIC_CONFIG_VERSION_3C:
            raise ConstraintExecutionError("GoverningIntegration semantic config version mismatch")
        return self


def require_governing_integration(raw: object) -> GoverningIntegration:
    if raw is None:
        raise ConstraintExecutionError("GoverningIntegration is required")
    if not isinstance(raw, GoverningIntegration):
        raise ConstraintExecutionError("RuntimeConfig.integration must be a GoverningIntegration")
    return raw.validate()


__all__ = [
    "GOVERNING_INTEGRATION_VERSION",
    "GoverningIntegration",
    "SEMANTIC_CONFIG_VERSION_3C",
    "require_governing_integration",
]
