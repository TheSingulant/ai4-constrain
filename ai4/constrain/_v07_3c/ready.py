"""Ready conclusion and hybrid_ready predicate (V07-3C).

Ready is introduced only in this slice. It is a readiness conclusion,
not independence, attestation, authentication, or cryptographic model
proof. ``hybrid_ready`` remains the sole readiness predicate. There is
no second activation bit and no public constructor that installs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import NotReady, ReadinessInput, TrustedProductConfig
from ai4.constrain._v07_3a.continuity import hybrid_continuity_required
from ai4.constrain._v07_3b.context import HybridConfiguration, HybridContext
from ai4.constrain._v07_3b.provenance import (
    CLAIM_ACCOUNT_OBSERVED,
    CLAIM_ORIGIN_ALLOWLISTED,
    CLAIM_PROVIDER_SESSION_BOUND,
    CLAIM_SERVED_MODEL_OBSERVED,
    CLAIM_TRANSPORT_BOUND,
)
from ai4.constrain._v07_3b.snapshot import assert_locked_artifact_hashes
from ai4.constrain.semantic_examiner import LOCKED_OBSERVATION_PROMPT_SHA256
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION
from ai4.constrain.semantic_fuse import LOCKED_POLICY_MAP_SHA256, LOCKED_REGISTRY_SHA256, PACKAGED_FUSE_ID
from ai4.constrain.governing import SEMANTIC_CONFIG_VERSION_3C

REQUIRED_RUNTIME_CLAIMS = (
    CLAIM_TRANSPORT_BOUND,
    CLAIM_ORIGIN_ALLOWLISTED,
    CLAIM_PROVIDER_SESSION_BOUND,
    CLAIM_SERVED_MODEL_OBSERVED,
    CLAIM_ACCOUNT_OBSERVED,
)

GATE_LOCKED_OBSERVATION_PROMPT_HASH = "locked_observation_prompt_hash"
GATE_LOCKED_REGISTRY_HASH = "locked_registry_hash"
GATE_LOCKED_POLICY_MAP_HASH = "locked_policy_map_hash"
GATE_FUSE_ID_MATCH = "fuse_id_match"
GATE_SEMANTIC_SCHEMA_VERSION = "semantic_schema_version_match"
GATE_SEMANTIC_CONFIG_VERSION = "semantic_config_version_match"
GATE_ROLE_BINDINGS = "proposer_examiner_role_bindings"
GATE_OPERATIONAL_SEPARATION = "operational_separation_minimum"
GATE_HARD_DISQUALIFIER = "no_hard_disqualifier"
GATE_RUNTIME_PROVENANCE = "runtime_observed_provenance"
GATE_CONTINUITY_COMPATIBLE = "continuity_compatible"
GATE_SHARED_BUDGET = "shared_budget_authority"
GATE_DEADLINE_VALID = "wall_clock_deadline_valid"
GATE_EXAMINER_BUDGET = "examiner_call_budget_available"
GATE_PROPOSAL_BUDGET = "proposal_completion_budget_available"


@dataclass(frozen=True)
class ReadyFacts:
    """Honest gate facts. None of these claim independence or attestation."""

    locked_observation_prompt_hash: bool
    locked_registry_hash: bool
    locked_policy_map_hash: bool
    fuse_id_match: bool
    semantic_schema_version_match: bool
    semantic_config_version_match: bool
    role_bindings_present: bool
    operational_separation_minimum: bool
    no_hard_disqualifier: bool
    runtime_observed_provenance: bool
    continuity_compatible: bool
    shared_budget_authority: bool
    wall_clock_deadline_valid: bool
    examiner_call_budget_available: bool
    proposal_completion_budget_available: bool
    observed_claim_names: tuple[str, ...]
    failed_gates: tuple[str, ...]
    independence: bool = False
    attested: bool = False
    authenticated: bool = False
    cryptographic_model_proof: bool = False

    def __post_init__(self) -> None:
        if self.independence or self.attested or self.authenticated or self.cryptographic_model_proof:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "ReadyFacts cannot claim independence, attestation, authentication, "
                "or cryptographic model proof",
            )

    @property
    def all_gates_passed(self) -> bool:
        return not self.failed_gates


@dataclass(frozen=True)
class Ready:
    """Readiness conclusion. Not an installer and not an attestation.

    Ready means the approved gates passed. It does not mean independence,
    attestation, authentication, or cryptographic model proof.
    """

    facts: ReadyFacts
    reason: str = "ready"

    def __post_init__(self) -> None:
        require_str(self.reason, field="reason")
        if not isinstance(self.facts, ReadyFacts):
            raise HybridExecutionAbort("schema_invalid", "Ready requires ReadyFacts")
        if not self.facts.all_gates_passed:
            raise HybridExecutionAbort("schema_invalid", "Ready cannot carry failed gates")
        if self.reason != "ready":
            raise HybridExecutionAbort("schema_invalid", "Ready.reason must be 'ready'")

    def install(self, *args: Any, **kwargs: Any) -> None:
        raise HybridExecutionAbort(
            "caller_config_pin_forbidden",
            "Ready is a conclusion only; HybridOrchestrator.install is the sole install seam",
        )


def _clock_now(context: HybridContext) -> float:
    authority = context.budget_authority
    if authority is None:
        return 0.0
    return float(authority._clock())


def compute_ready_facts(context: HybridContext, **kwargs: Any) -> ReadyFacts:
    reject_authority_kwargs(kwargs, label="compute_ready_facts")
    if not isinstance(context, HybridContext):
        raise HybridExecutionAbort("schema_invalid", "compute_ready_facts needs HybridContext")
    snapshot = context.identity_snapshot
    config = context.configuration
    proposer_observed = tuple(
        item.claim for item in context.provenance.claims if item.is_runtime_observed()
    )
    examiner_bundle = context.examiner_provenance
    examiner_observed = (
        tuple(item.claim for item in examiner_bundle.claims if item.is_runtime_observed())
        if examiner_bundle is not None
        else ()
    )
    observed = tuple(f"proposer.{name}" for name in proposer_observed) + tuple(
        f"examiner.{name}" for name in examiner_observed
    )
    failed: list[str] = []

    locked_prompt = snapshot.observation_prompt_sha256 == LOCKED_OBSERVATION_PROMPT_SHA256
    locked_registry = snapshot.registry_sha256 == LOCKED_REGISTRY_SHA256
    locked_map = snapshot.policy_map_sha256 == LOCKED_POLICY_MAP_SHA256
    fuse_ok = snapshot.fuse_id == PACKAGED_FUSE_ID == config.fuse_id
    schema_ok = snapshot.semantic_schema_version == FINDINGS_SCHEMA_VERSION == config.semantic_schema_version
    config_ok = snapshot.semantic_config_version == SEMANTIC_CONFIG_VERSION_3C == config.semantic_config_version
    roles_ok = (
        len(context.role_bindings) == 2
        and {item.role for item in context.role_bindings} == {"proposer", "examiner"}
    )
    hard_ok = not context.separation.hard_disqualifiers and not context.separation.grade == "hard_disqualifier"
    sep_ok = bool(context.separation.minimum_satisfied) and hard_ok
    proposer_required = all(name in proposer_observed for name in REQUIRED_RUNTIME_CLAIMS)
    # Config labels never satisfy observed provenance. Each role's bundle
    # must carry its own runtime-observed dimensions; the other role cannot
    # satisfy Ready for this one.
    if context.provenance.kind != "runtime_observed":
        proposer_required = False
    examiner_required = False
    if examiner_bundle is not None and examiner_bundle.kind == "runtime_observed":
        examiner_required = all(name in examiner_observed for name in REQUIRED_RUNTIME_CLAIMS)
    required_observed = proposer_required and examiner_required
    budget = context.budget_authority
    budget_ok = budget is not None
    now = _clock_now(context) if budget_ok else 0.0
    deadline_ok = bool(budget_ok and now < float(budget.deadline_monotonic))
    snap = budget.snapshot() if budget_ok else {}
    examiner_ok = bool(
        budget_ok
        and int(snap["examiner_committed"]) + int(snap["examiner_reserved"]) < int(snap["max_examiner_calls"])
    )
    proposal_ok = bool(
        budget_ok
        and int(snap["proposal_committed"]) + int(snap["proposal_reserved"]) < int(snap["max_proposal_completions"])
    )
    # Continuity is compatible when the snapshot is well-formed. Identity
    # match is a restore check, not a Ready claim of independence.
    continuity_ok = True
    if hybrid_continuity_required(context.continuity) and not context.continuity.ever_on:
        # Repair is the caller's job; unrepaired disagreement is incompatible.
        continuity_ok = False

    if not locked_prompt:
        failed.append(GATE_LOCKED_OBSERVATION_PROMPT_HASH)
    if not locked_registry:
        failed.append(GATE_LOCKED_REGISTRY_HASH)
    if not locked_map:
        failed.append(GATE_LOCKED_POLICY_MAP_HASH)
    if not fuse_ok:
        failed.append(GATE_FUSE_ID_MATCH)
    if not schema_ok:
        failed.append(GATE_SEMANTIC_SCHEMA_VERSION)
    if not config_ok:
        failed.append(GATE_SEMANTIC_CONFIG_VERSION)
    if not roles_ok:
        failed.append(GATE_ROLE_BINDINGS)
    if not sep_ok:
        failed.append(GATE_OPERATIONAL_SEPARATION)
    if not hard_ok:
        failed.append(GATE_HARD_DISQUALIFIER)
    if not required_observed:
        failed.append(GATE_RUNTIME_PROVENANCE)
    if not continuity_ok:
        failed.append(GATE_CONTINUITY_COMPATIBLE)
    if not budget_ok:
        failed.append(GATE_SHARED_BUDGET)
    if not deadline_ok:
        failed.append(GATE_DEADLINE_VALID)
    if not examiner_ok:
        failed.append(GATE_EXAMINER_BUDGET)
    if not proposal_ok:
        failed.append(GATE_PROPOSAL_BUDGET)

    try:
        assert_locked_artifact_hashes(snapshot)
    except HybridExecutionAbort:
        if GATE_LOCKED_OBSERVATION_PROMPT_HASH not in failed and not locked_prompt:
            failed.append(GATE_LOCKED_OBSERVATION_PROMPT_HASH)

    return ReadyFacts(
        locked_observation_prompt_hash=locked_prompt,
        locked_registry_hash=locked_registry,
        locked_policy_map_hash=locked_map,
        fuse_id_match=fuse_ok,
        semantic_schema_version_match=schema_ok,
        semantic_config_version_match=config_ok,
        role_bindings_present=roles_ok,
        operational_separation_minimum=sep_ok,
        no_hard_disqualifier=hard_ok,
        runtime_observed_provenance=required_observed,
        continuity_compatible=continuity_ok,
        shared_budget_authority=budget_ok,
        wall_clock_deadline_valid=deadline_ok,
        examiner_call_budget_available=examiner_ok,
        proposal_completion_budget_available=proposal_ok,
        observed_claim_names=observed,
        failed_gates=tuple(failed),
    )


def hybrid_ready(
    context: HybridContext | HybridConfiguration | ReadinessInput | TrustedProductConfig | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Ready | NotReady:
    """Sole readiness predicate. Returns Ready only when every approved gate passes."""
    reject_authority_kwargs(kwargs, label="hybrid_ready")
    if context is None:
        return NotReady(reason="slice_incomplete")
    if isinstance(context, (HybridConfiguration, ReadinessInput, TrustedProductConfig, Mapping)):
        return NotReady(reason="runtime_observed_provenance")
    if not isinstance(context, HybridContext):
        raise HybridExecutionAbort("schema_invalid", "unsupported hybrid_ready context")
    facts = compute_ready_facts(context)
    if facts.all_gates_passed:
        return Ready(facts=facts)
    return NotReady(reason=facts.failed_gates[0] if facts.failed_gates else "not_ready")


__all__ = [
    "GATE_CONTINUITY_COMPATIBLE",
    "GATE_DEADLINE_VALID",
    "GATE_EXAMINER_BUDGET",
    "GATE_FUSE_ID_MATCH",
    "GATE_HARD_DISQUALIFIER",
    "GATE_LOCKED_OBSERVATION_PROMPT_HASH",
    "GATE_LOCKED_POLICY_MAP_HASH",
    "GATE_LOCKED_REGISTRY_HASH",
    "GATE_OPERATIONAL_SEPARATION",
    "GATE_PROPOSAL_BUDGET",
    "GATE_ROLE_BINDINGS",
    "GATE_RUNTIME_PROVENANCE",
    "GATE_SEMANTIC_CONFIG_VERSION",
    "GATE_SEMANTIC_SCHEMA_VERSION",
    "GATE_SHARED_BUDGET",
    "REQUIRED_RUNTIME_CLAIMS",
    "Ready",
    "ReadyFacts",
    "compute_ready_facts",
    "hybrid_ready",
]
