"""V07-3B non-governing hybrid infrastructure.

This package is not a product surface. It is not imported by
``ai4.constrain.api``, ``ai4.constrain.__init__``, ConstraintMiddleware,
or ConstrainedAgent. Nothing here installs a governing hybrid evaluator,
exposes an enable flag, or reaches ``observe_semantic_candidate`` /
``map_and_fuse_v2`` from ``run()`` / ``evaluate()``.

3B adds provenance, origin, operational-separation, context-builder,
budget-adapter, session 0.2.0, DecisionReport 0.2.0, feedback-template,
artifact-snapshot, and non-installing readiness *facts*. Hybrid governing
behavior remains structurally unreachable. V07-3C is the first and only
governing integration slice.

``hybrid_ready`` still returns ``NotReady``. There is no ``Ready`` object
and no install path in this slice.
"""

from __future__ import annotations

from ai4.constrain._v07_3a import (
    HYBRID_ABORT_CLASSES,
    HybridExecutionAbort,
    NotReady,
    ObservedProvenanceEvidence,
    ReadinessInput,
    RoleBinding,
    RunBudgetAuthority,
    RunBudgetReservation,
    TrustedProductConfig,
    bind_roles,
    evidence_is_authenticated as evidence_is_authenticated_3a,
    hybrid_ready as hybrid_ready_3a,
    unobserved_provenance,
)
from ai4.constrain._v07_3b.budget import BudgetAwareProviderAdapter
from ai4.constrain._v07_3b.context import (
    HybridConfiguration,
    HybridContext,
    HybridContextBuilder,
    HybridContextValidator,
)
from ai4.constrain._v07_3b.feedback import (
    FEEDBACK_TEMPLATE_REGISTRY_VERSION,
    format_hybrid_revision_feedback,
    lookup_feedback_template,
)
from ai4.constrain._v07_3b.origin import (
    REDIRECT_POLICY_EXPLICIT_ALLOWLIST,
    REDIRECT_POLICY_NONE,
    TransportBinding,
    allowlist_origin,
    canonicalize_origin,
)
from ai4.constrain._v07_3b.provenance import (
    PROVENANCE_CLAIMS,
    ProvenanceClaim,
    ProvenanceEvidenceBundle,
    collect_account_observed,
    collect_configured,
    collect_origin_allowlisted,
    collect_provider_session_bound,
    collect_served_model_observed,
    collect_transport_bound,
    evidence_is_attested,
    evidence_is_authenticated,
)
from ai4.constrain._v07_3b.readiness import (
    ReadinessFacts,
    compute_readiness_facts,
    hybrid_ready,
)
from ai4.constrain._v07_3b.report import (
    REPORT_SCHEMA_VERSION_0_2_0,
    SemanticDocument,
    parse_decision_report_document,
    redact_semantic_document,
    serialize_decision_report_document,
)
from ai4.constrain._v07_3b.separation import (
    GRADE_BEST_EFFORT,
    GRADE_HARD_DISQUALIFIER,
    GRADE_MINIMUM_OPERATIONAL,
    GRADE_NOT_PROVEN,
    SeparationAssessment,
    assess_operational_separation,
    credential_compare_token,
    credentials_equal,
)
from ai4.constrain._v07_3b.session import (
    SESSION_SCHEMA_VERSION_0_1_0,
    SESSION_SCHEMA_VERSION_0_1_1,
    SESSION_SCHEMA_VERSION_0_2_0,
    HybridSessionIdentity,
    parse_session_document,
    serialize_session_document,
)
from ai4.constrain._v07_3b.snapshot import (
    ArtifactContinuitySnapshot,
    detect_identity_drift,
    snapshot_from_context,
)

__all__ = [
    "BUDGET_ADAPTER_INERT_WITHOUT_AUTHORITY",
    "FEEDBACK_TEMPLATE_REGISTRY_VERSION",
    "GRADE_BEST_EFFORT",
    "GRADE_HARD_DISQUALIFIER",
    "GRADE_MINIMUM_OPERATIONAL",
    "GRADE_NOT_PROVEN",
    "HYBRID_ABORT_CLASSES",
    "HybridConfiguration",
    "HybridContext",
    "HybridContextBuilder",
    "HybridContextValidator",
    "HybridExecutionAbort",
    "HybridSessionIdentity",
    "NotReady",
    "ObservedProvenanceEvidence",
    "PROVENANCE_CLAIMS",
    "ProvenanceClaim",
    "ProvenanceEvidenceBundle",
    "REDIRECT_POLICY_EXPLICIT_ALLOWLIST",
    "REDIRECT_POLICY_NONE",
    "REPORT_SCHEMA_VERSION_0_2_0",
    "ReadinessFacts",
    "ReadinessInput",
    "RoleBinding",
    "RunBudgetAuthority",
    "RunBudgetReservation",
    "SESSION_SCHEMA_VERSION_0_1_0",
    "SESSION_SCHEMA_VERSION_0_1_1",
    "SESSION_SCHEMA_VERSION_0_2_0",
    "SemanticDocument",
    "SeparationAssessment",
    "TransportBinding",
    "TrustedProductConfig",
    "allowlist_origin",
    "assess_operational_separation",
    "bind_roles",
    "canonicalize_origin",
    "collect_account_observed",
    "collect_configured",
    "collect_origin_allowlisted",
    "collect_provider_session_bound",
    "collect_served_model_observed",
    "collect_transport_bound",
    "compute_readiness_facts",
    "credential_compare_token",
    "credentials_equal",
    "detect_identity_drift",
    "evidence_is_attested",
    "evidence_is_authenticated",
    "evidence_is_authenticated_3a",
    "format_hybrid_revision_feedback",
    "hybrid_ready",
    "hybrid_ready_3a",
    "lookup_feedback_template",
    "parse_decision_report_document",
    "parse_session_document",
    "redact_semantic_document",
    "serialize_decision_report_document",
    "serialize_session_document",
    "snapshot_from_context",
    "unobserved_provenance",
    "BudgetAwareProviderAdapter",
    "ArtifactContinuitySnapshot",
]

# Documented adapter contract: without an injected authority the wrapper
# is a pass-through and cannot change OFF provider behavior.
BUDGET_ADAPTER_INERT_WITHOUT_AUTHORITY = True
