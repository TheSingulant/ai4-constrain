"""V07-3A inert/internal hybrid primitives.

This package is not a product surface. It is not imported by
``ai4.constrain.api``, ``ai4.constrain.__init__``, ConstraintMiddleware,
or ConstrainedAgent. Nothing here installs a governing hybrid evaluator,
exposes an enable flag, or reaches ``observe_semantic_candidate`` /
``map_and_fuse_v2`` from ``run()`` / ``evaluate()``.

``hybrid_ready`` is a stub that returns ``NotReady("slice_incomplete")``.
There is no ``Ready`` object and no install path in this slice.
"""

from __future__ import annotations

from ai4.constrain._v07_3a.abort import (
    HYBRID_ABORT_CLASSES,
    HYBRID_ABORT_VOCABULARY_VERSION,
    HybridExecutionAbort,
)
from ai4.constrain._v07_3a.budget import (
    ReservationKind,
    RunBudgetAuthority,
    RunBudgetReservation,
)
from ai4.constrain._v07_3a.context import (
    ContinuitySnapshot,
    NotReady,
    ObservedProvenanceEvidence,
    ReadinessInput,
    RoleBinding,
    TrustedProductConfig,
    bind_roles,
    evidence_is_authenticated,
    hybrid_ready,
    observed_provenance,
    unobserved_provenance,
)
from ai4.constrain._v07_3a.continuity import (
    assert_continuity_not_reconciled_off,
    continuity_snapshot_from_persisted,
    durable_continuity_intent,
    hybrid_continuity_required,
    inspect_persisted_report_schema_0_2_0,
    inspect_persisted_semantic,
    reconcile_continuity_mirrors,
    tighten_continuity_state,
)
from ai4.constrain._v07_3a.rebuild import (
    APPROVED_DETERMINISTIC_SHARD_METADATA,
    rebuild_fused_evaluation,
)
from ai4.constrain._v07_3a.report import (
    FORBIDDEN_SEMANTIC_REPORT_FIELDS,
    SEMANTIC_BLOCK_SCHEMA_VERSION,
    SemanticAbortBlock,
    SemanticSuccessBlock,
    redact_semantic_block,
)

__all__ = [
    "APPROVED_DETERMINISTIC_SHARD_METADATA",
    "FORBIDDEN_SEMANTIC_REPORT_FIELDS",
    "HYBRID_ABORT_CLASSES",
    "HYBRID_ABORT_VOCABULARY_VERSION",
    "HybridExecutionAbort",
    "ContinuitySnapshot",
    "NotReady",
    "ObservedProvenanceEvidence",
    "ReadinessInput",
    "ReservationKind",
    "RoleBinding",
    "RunBudgetAuthority",
    "RunBudgetReservation",
    "SEMANTIC_BLOCK_SCHEMA_VERSION",
    "SemanticAbortBlock",
    "SemanticSuccessBlock",
    "TrustedProductConfig",
    "assert_continuity_not_reconciled_off",
    "bind_roles",
    "continuity_snapshot_from_persisted",
    "durable_continuity_intent",
    "evidence_is_authenticated",
    "hybrid_continuity_required",
    "hybrid_ready",
    "inspect_persisted_report_schema_0_2_0",
    "inspect_persisted_semantic",
    "observed_provenance",
    "rebuild_fused_evaluation",
    "reconcile_continuity_mirrors",
    "redact_semantic_block",
    "tighten_continuity_state",
    "unobserved_provenance",
]
