"""Product-owned HybridContext builder (V07-3B §4).

Pipeline (non-governing):

    HybridConfiguration → HybridContextBuilder → HybridContextValidator
    → readiness inputs / facts

Inputs are trusted product config, runtime-observed provenance (collector
minted), role bindings, optional shared budget authority, continuity
state, and locked artifact identities.

There is no public Ready / install path. Validation facts are for tests
and later 3C review only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai4.constrain._v07_3a._common import (
    reject_authority_kwargs,
    require_finite_number,
    require_nonnegative,
    require_str,
)
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.budget import RunBudgetAuthority
from ai4.constrain._v07_3a.context import (
    ContinuitySnapshot,
    RoleBinding,
    TrustedProductConfig,
    bind_roles,
)
from ai4.constrain._v07_3a.continuity import hybrid_continuity_required
from ai4.constrain.ext import FROZEN_EVALUATOR_ID, FROZEN_EVALUATOR_IMPL
from ai4.constrain.semantic_examiner import LOCKED_OBSERVATION_PROMPT_SHA256
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION
from ai4.constrain.semantic_fuse import (
    LOCKED_POLICY_MAP_SHA256,
    LOCKED_REGISTRY_SHA256,
    PACKAGED_FUSE_ID,
)
from ai4.constrain._v07_3b.origin import (
    TransportBinding,
    allowlist_origin,
    normalize_allowlist,
)
from ai4.constrain._v07_3b.provenance import (
    CLAIM_ACCOUNT_OBSERVED,
    CLAIM_CONFIGURED,
    CLAIM_ORIGIN_ALLOWLISTED,
    CLAIM_PROVIDER_SESSION_BOUND,
    CLAIM_SERVED_MODEL_OBSERVED,
    CLAIM_TRANSPORT_BOUND,
    ProvenanceEvidenceBundle,
    bundle_claims,
    collect_configured,
)
from ai4.constrain._v07_3b.separation import (
    GRADE_HARD_DISQUALIFIER,
    SeparationAssessment,
    assess_operational_separation,
)
from ai4.constrain._v07_3b.snapshot import (
    ArtifactContinuitySnapshot,
    assert_locked_artifact_hashes,
)

SEMANTIC_CONFIG_VERSION = "v07.3b.0"


@dataclass(frozen=True)
class HybridConfiguration:
    """Trusted product configuration. Not runtime-observed evidence."""

    trusted: TrustedProductConfig
    origin_allowlist: tuple[str, ...]
    proposer_requested_origin: str
    examiner_requested_origin: str
    max_usd: float
    deadline_monotonic: float
    max_proposal_completions: int
    max_examiner_calls: int
    observation_prompt_sha256: str = LOCKED_OBSERVATION_PROMPT_SHA256
    registry_sha256: str = LOCKED_REGISTRY_SHA256
    policy_map_sha256: str = LOCKED_POLICY_MAP_SHA256
    fuse_id: str = PACKAGED_FUSE_ID
    semantic_schema_version: str = FINDINGS_SCHEMA_VERSION
    semantic_config_version: str = SEMANTIC_CONFIG_VERSION
    evaluator_identity: str = FROZEN_EVALUATOR_ID
    evaluator_fingerprint: str = FROZEN_EVALUATOR_IMPL

    def __post_init__(self) -> None:
        if not isinstance(self.trusted, TrustedProductConfig):
            raise HybridExecutionAbort("schema_invalid", "trusted must be TrustedProductConfig")
        if not isinstance(self.origin_allowlist, tuple):
            raise HybridExecutionAbort("schema_invalid", "origin_allowlist must be a tuple")
        require_str(self.proposer_requested_origin, field="proposer_requested_origin")
        require_str(self.examiner_requested_origin, field="examiner_requested_origin")
        require_nonnegative(require_finite_number(self.max_usd, field="max_usd"), field="max_usd")
        require_finite_number(self.deadline_monotonic, field="deadline_monotonic")
        for field in ("max_proposal_completions", "max_examiner_calls"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise HybridExecutionAbort("schema_invalid", f"{field} must be a nonnegative int")
        require_str(self.observation_prompt_sha256, field="observation_prompt_sha256")
        require_str(self.registry_sha256, field="registry_sha256")
        require_str(self.policy_map_sha256, field="policy_map_sha256")
        require_str(self.fuse_id, field="fuse_id")
        require_str(self.semantic_schema_version, field="semantic_schema_version")
        require_str(self.semantic_config_version, field="semantic_config_version")
        require_str(self.evaluator_identity, field="evaluator_identity")
        require_str(self.evaluator_fingerprint, field="evaluator_fingerprint")
        object.__setattr__(self, "origin_allowlist", normalize_allowlist(self.origin_allowlist))
        allowlist_origin(self.proposer_requested_origin, self.origin_allowlist)
        allowlist_origin(self.examiner_requested_origin, self.origin_allowlist)
        if self.trusted.observation_prompt_sha256 != self.observation_prompt_sha256:
            raise HybridExecutionAbort(
                "observation_prompt_hash_mismatch",
                "trusted config observation prompt hash disagrees with locked snapshot",
            )


@dataclass(frozen=True)
class HybridContext:
    """Assembled hybrid facts. Not installable and not a Ready object."""

    configuration: HybridConfiguration
    role_bindings: tuple[RoleBinding, RoleBinding]
    provenance: ProvenanceEvidenceBundle
    continuity: ContinuitySnapshot
    identity_snapshot: ArtifactContinuitySnapshot
    separation: SeparationAssessment
    proposer_transport: TransportBinding | None = None
    examiner_transport: TransportBinding | None = None
    budget_authority: RunBudgetAuthority | None = None
    examiner_provenance: ProvenanceEvidenceBundle | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, HybridConfiguration):
            raise HybridExecutionAbort("schema_invalid", "configuration type mismatch")
        if not isinstance(self.provenance, ProvenanceEvidenceBundle):
            raise HybridExecutionAbort("schema_invalid", "provenance type mismatch")
        if not isinstance(self.continuity, ContinuitySnapshot):
            raise HybridExecutionAbort("schema_invalid", "continuity type mismatch")
        if not isinstance(self.identity_snapshot, ArtifactContinuitySnapshot):
            raise HybridExecutionAbort("schema_invalid", "identity_snapshot type mismatch")
        if not isinstance(self.separation, SeparationAssessment):
            raise HybridExecutionAbort("schema_invalid", "separation type mismatch")
        if self.budget_authority is not None and not isinstance(
            self.budget_authority, RunBudgetAuthority
        ):
            raise HybridExecutionAbort("schema_invalid", "budget_authority type mismatch")
        if self.examiner_provenance is not None and not isinstance(
            self.examiner_provenance, ProvenanceEvidenceBundle
        ):
            raise HybridExecutionAbort("schema_invalid", "examiner_provenance type mismatch")

    def install(self, *args: Any, **kwargs: Any) -> None:
        raise HybridExecutionAbort(
            "continuity_required_not_ready",
            "HybridContext cannot install a hybrid evaluator",
        )


@dataclass(frozen=True)
class ContextValidationFacts:
    """Non-installing validation facts. Not a readiness conclusion.

    ``configured_origin_allowlist_pass`` is a configuration/validation
    fact. It is not runtime-observed provenance. ``origin_allowlisted``
    here means the collector-minted ``origin_allowlisted`` claim is
    present on the bundle (runtime-observed), not that config matched
    the allowlist.
    """

    origin_allowlisted: bool
    locked_artifacts_ok: bool
    continuity_required: bool
    hard_disqualified: bool
    minimum_operational_separation: bool
    observed_claim_names: tuple[str, ...]
    notes: tuple[str, ...]
    configured_origin_allowlist_pass: bool = False
    has_runtime_observed_provenance: bool = False


class HybridContextBuilder:
    """Assemble a HybridContext from trusted config plus optional observations."""

    def __init__(self, configuration: HybridConfiguration, **kwargs: Any) -> None:
        reject_authority_kwargs(kwargs, label="HybridContextBuilder")
        if not isinstance(configuration, HybridConfiguration):
            raise HybridExecutionAbort("schema_invalid", "HybridContextBuilder needs HybridConfiguration")
        self._configuration = configuration
        self._provenance: ProvenanceEvidenceBundle | None = None
        self._continuity: ContinuitySnapshot | None = None
        self._budget: RunBudgetAuthority | None = None
        self._proposer_transport: TransportBinding | None = None
        self._examiner_transport: TransportBinding | None = None
        self._proposer_account: str | None = None
        self._examiner_account: str | None = None
        self._proposer_credential: str | bytes | None = None
        self._examiner_credential: str | bytes | None = None
        self._proposer_session: object | None = None
        self._examiner_session: object | None = None
        self._examiner_provenance: ProvenanceEvidenceBundle | None = None

    def with_runtime_provenance(self, bundle: ProvenanceEvidenceBundle) -> HybridContextBuilder:
        if not isinstance(bundle, ProvenanceEvidenceBundle):
            raise HybridExecutionAbort("schema_invalid", "with_runtime_provenance needs a bundle")
        configured = bundle.claim(CLAIM_CONFIGURED)
        if configured is not None and configured.is_runtime_observed():
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "configured labels cannot be marked runtime-observed",
            )
        self._provenance = bundle
        return self

    def with_examiner_runtime_provenance(self, bundle: ProvenanceEvidenceBundle) -> HybridContextBuilder:
        if not isinstance(bundle, ProvenanceEvidenceBundle):
            raise HybridExecutionAbort(
                "schema_invalid",
                "with_examiner_runtime_provenance needs a bundle",
            )
        configured = bundle.claim(CLAIM_CONFIGURED)
        if configured is not None and configured.is_runtime_observed():
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "configured labels cannot be marked runtime-observed",
            )
        self._examiner_provenance = bundle
        return self

    def with_continuity(self, snapshot: ContinuitySnapshot) -> HybridContextBuilder:
        if not isinstance(snapshot, ContinuitySnapshot):
            raise HybridExecutionAbort("schema_invalid", "with_continuity needs ContinuitySnapshot")
        self._continuity = snapshot
        return self

    def with_budget_authority(self, authority: RunBudgetAuthority) -> HybridContextBuilder:
        if not isinstance(authority, RunBudgetAuthority):
            raise HybridExecutionAbort("schema_invalid", "with_budget_authority needs RunBudgetAuthority")
        self._budget = authority
        return self

    def with_transport(
        self,
        *,
        proposer: TransportBinding | None = None,
        examiner: TransportBinding | None = None,
    ) -> HybridContextBuilder:
        self._proposer_transport = proposer
        self._examiner_transport = examiner
        return self

    def with_accounts(self, *, proposer: str | None = None, examiner: str | None = None) -> HybridContextBuilder:
        self._proposer_account = proposer
        self._examiner_account = examiner
        return self

    def with_credentials(
        self,
        *,
        proposer: str | bytes | None = None,
        examiner: str | bytes | None = None,
    ) -> HybridContextBuilder:
        self._proposer_credential = proposer
        self._examiner_credential = examiner
        return self

    def with_session_objects(
        self,
        *,
        proposer: object | None = None,
        examiner: object | None = None,
    ) -> HybridContextBuilder:
        self._proposer_session = proposer
        self._examiner_session = examiner
        return self

    def build(self, **kwargs: Any) -> HybridContext:
        reject_authority_kwargs(kwargs, label="HybridContextBuilder.build")
        config = self._configuration
        bindings = bind_roles(config.trusted)
        continuity = self._continuity or ContinuitySnapshot(
            ever_on=False,
            ever_required=False,
            persisted_report_schema_0_2_0=False,
            persisted_semantic=False,
        )
        # Configuration allowlist is a validation fact, not observation.
        # Fail closed if the configured requested origins are not listed.
        # Do not mint origin_allowlisted / runtime_observed from config.
        allowlist_origin(config.proposer_requested_origin, config.origin_allowlist)
        allowlist_origin(config.examiner_requested_origin, config.origin_allowlist)
        claims = []
        if self._provenance is not None:
            claims.extend(self._provenance.claims)
        else:
            claims.append(
                collect_configured(
                    f"{config.trusted.examiner_provider_id}/{config.trusted.examiner_model_id}"
                )
            )
        provenance = bundle_claims(claims)
        snapshot = ArtifactContinuitySnapshot(
            observation_prompt_sha256=config.observation_prompt_sha256,
            registry_sha256=config.registry_sha256,
            policy_map_sha256=config.policy_map_sha256,
            fuse_id=config.fuse_id,
            examiner_config_identity=(
                f"{config.trusted.examiner_id}:{config.trusted.examiner_version}:"
                f"{config.trusted.examiner_provider_id}/{config.trusted.examiner_model_id}"
            ),
            examiner_provenance_identity=_provenance_identity(provenance),
            proposer_identity=(
                f"{config.trusted.proposer_provider_id}/{config.trusted.proposer_model_id}"
            ),
            evaluator_identity=config.evaluator_identity,
            evaluator_fingerprint=config.evaluator_fingerprint,
            semantic_schema_version=config.semantic_schema_version,
            examiner_call_cap=config.max_examiner_calls,
            semantic_config_version=config.semantic_config_version,
        )
        assert_locked_artifact_hashes(snapshot)
        separation = assess_operational_separation(
            proposer=bindings[0],
            examiner=bindings[1],
            proposer_account=self._proposer_account,
            examiner_account=self._examiner_account,
            proposer_origin=config.proposer_requested_origin,
            examiner_origin=config.examiner_requested_origin,
            proposer_transport=self._proposer_transport,
            examiner_transport=self._examiner_transport,
            proposer_credential=self._proposer_credential,
            examiner_credential=self._examiner_credential,
            proposer_session=self._proposer_session,
            examiner_session=self._examiner_session,
        )
        return HybridContext(
            configuration=config,
            role_bindings=bindings,
            provenance=provenance,
            continuity=continuity,
            identity_snapshot=snapshot,
            separation=separation,
            proposer_transport=self._proposer_transport,
            examiner_transport=self._examiner_transport,
            budget_authority=self._budget,
            examiner_provenance=self._examiner_provenance,
        )


class HybridContextValidator:
    """Produce non-installing validation facts from a HybridContext."""

    def validate(self, context: HybridContext, **kwargs: Any) -> ContextValidationFacts:
        reject_authority_kwargs(kwargs, label="HybridContextValidator.validate")
        if not isinstance(context, HybridContext):
            raise HybridExecutionAbort("schema_invalid", "validate needs HybridContext")
        assert_locked_artifact_hashes(context.identity_snapshot)
        allowlist = context.configuration.origin_allowlist
        allowlist_origin(context.configuration.proposer_requested_origin, allowlist)
        allowlist_origin(context.configuration.examiner_requested_origin, allowlist)
        observed = tuple(
            item.claim for item in context.provenance.claims if item.is_runtime_observed()
        )
        notes: list[str] = []
        if context.separation.grade == GRADE_HARD_DISQUALIFIER:
            notes.append("hard_disqualifier")
        if hybrid_continuity_required(context.continuity):
            notes.append("continuity_required")
        return ContextValidationFacts(
            origin_allowlisted=CLAIM_ORIGIN_ALLOWLISTED in observed,
            locked_artifacts_ok=True,
            continuity_required=hybrid_continuity_required(context.continuity),
            hard_disqualified=context.separation.grade == GRADE_HARD_DISQUALIFIER,
            minimum_operational_separation=context.separation.minimum_satisfied,
            observed_claim_names=observed,
            notes=tuple(notes),
            configured_origin_allowlist_pass=True,
            has_runtime_observed_provenance=bool(observed),
        )


def _provenance_identity(bundle: ProvenanceEvidenceBundle) -> str:
    parts = []
    for name in (
        CLAIM_TRANSPORT_BOUND,
        CLAIM_ORIGIN_ALLOWLISTED,
        CLAIM_PROVIDER_SESSION_BOUND,
        CLAIM_SERVED_MODEL_OBSERVED,
        CLAIM_ACCOUNT_OBSERVED,
        CLAIM_CONFIGURED,
    ):
        item = bundle.claim(name)
        if item is None:
            continue
        mark = "observed" if item.is_runtime_observed() else "configured"
        parts.append(f"{name}={mark}")
    return ";".join(parts) if parts else "none"


__all__ = [
    "ContextValidationFacts",
    "HybridConfiguration",
    "HybridContext",
    "HybridContextBuilder",
    "HybridContextValidator",
    "SEMANTIC_CONFIG_VERSION",
]
