"""Singular install seam (Candidate 2.1 / 2.2).

Sequence:
  validate context → readiness passes → write continuity marker →
  persistence commit returns successfully → ONLY THEN may proposal /
  examiner / fuse / decide begin.

Failed marker persist = failed install = never entered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai4.constrain._v07_3a._common import reject_authority_kwargs
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import NotReady
from ai4.constrain._v07_3b.context import HybridContext, HybridContextValidator
from ai4.constrain._v07_3b.snapshot import ArtifactContinuitySnapshot, detect_identity_drift
from ai4.constrain._v07_3c.observe import observation_from_bundle
from ai4.constrain._v07_3c.persist import ContinuityStore, persist_continuity_marker
from ai4.constrain._v07_3c.ready import Ready, hybrid_ready


@dataclass(frozen=True)
class InstalledHybrid:
    """Successful install snapshot. Continuity is already persisted."""

    context: HybridContext
    ready: Ready
    identity_snapshot: ArtifactContinuitySnapshot
    session_id: str
    proposer_observation: dict[str, str]
    examiner_observation: dict[str, str]
    ever_on: bool = True


class HybridOrchestrator:
    """Internal install authority. No public constructor installs."""

    def __init__(self, store: ContinuityStore, *, session_id: str) -> None:
        if store is None:
            raise HybridExecutionAbort("schema_invalid", "HybridOrchestrator requires a persist store")
        if not isinstance(session_id, str) or not session_id:
            raise HybridExecutionAbort("schema_invalid", "session_id is required")
        self._store = store
        self._session_id = session_id
        self._installed: InstalledHybrid | None = None
        self._proposal_started = False

    @property
    def installed(self) -> InstalledHybrid | None:
        return self._installed

    @property
    def store(self) -> ContinuityStore:
        return self._store

    @property
    def session_id(self) -> str:
        return self._session_id

    def mark_hybrid_operation_started(self) -> None:
        self._proposal_started = True

    def install(self, validated_ctx: HybridContext, **kwargs: Any) -> InstalledHybrid:
        """Last install step is durable ever_on=true. Then hybrid ops may start."""
        reject_authority_kwargs(kwargs, label="HybridOrchestrator.install")
        if self._installed is not None:
            raise HybridExecutionAbort("identity_drift", "hybrid already installed for this session")
        if self._proposal_started:
            raise HybridExecutionAbort(
                "schema_invalid",
                "cannot install after an abort-capable hybrid operation has started",
            )
        if not isinstance(validated_ctx, HybridContext):
            raise HybridExecutionAbort("schema_invalid", "install needs HybridContext")
        HybridContextValidator().validate(validated_ctx)
        conclusion = hybrid_ready(validated_ctx)
        if isinstance(conclusion, NotReady):
            raise HybridExecutionAbort(
                "continuity_required_not_ready",
                f"install refused; hybrid_ready is NotReady({conclusion.reason!r})",
            )
        if not isinstance(conclusion, Ready):
            raise HybridExecutionAbort("schema_invalid", "install requires Ready")
        if validated_ctx.budget_authority is None:
            raise HybridExecutionAbort("schema_invalid", "install requires shared budget authority")
        if validated_ctx.examiner_provenance is None:
            raise HybridExecutionAbort(
                "provenance_mismatch",
                "install requires role-scoped examiner runtime provenance",
            )
        proposer_observation = observation_from_bundle(validated_ctx.provenance)
        examiner_observation = observation_from_bundle(validated_ctx.examiner_provenance)
        if not all(proposer_observation.values()) or not all(examiner_observation.values()):
            raise HybridExecutionAbort(
                "provenance_mismatch",
                "install snapshot missing observed-at-install origin/account/session/model",
            )
        persist_continuity_marker(
            self._store,
            session_id=self._session_id,
            snapshot=validated_ctx.identity_snapshot,
        )
        installed = InstalledHybrid(
            context=validated_ctx,
            ready=conclusion,
            identity_snapshot=validated_ctx.identity_snapshot,
            session_id=self._session_id,
            proposer_observation=proposer_observation,
            examiner_observation=examiner_observation,
            ever_on=True,
        )
        self._installed = installed
        return installed

    def assert_identity_stable(self, observed: ArtifactContinuitySnapshot, **kwargs: Any) -> None:
        reject_authority_kwargs(kwargs, label="assert_identity_stable")
        if self._installed is None:
            raise HybridExecutionAbort("schema_invalid", "identity check requires install")
        detect_identity_drift(self._installed.identity_snapshot, observed)


__all__ = [
    "HybridOrchestrator",
    "InstalledHybrid",
]
