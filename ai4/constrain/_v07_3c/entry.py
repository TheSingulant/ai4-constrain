"""run()-only entry for V07-3C governing integration.

``execute_configured`` returns None when no product integration is
configured so the frozen OFF path remains unchanged. It never installs
from evaluate() and never treats env vars, hidden kwargs, or caller
Ready objects as activation.
"""

from __future__ import annotations

import time
from typing import Any

from src.agents.base_agent import TerminalState
from src.constraints.constraint_middleware import ConstraintMiddleware
from src.providers.base import Completion
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.budget import RunBudgetAuthority
from ai4.constrain._v07_3a.context import ContinuitySnapshot, NotReady, TrustedProductConfig
from ai4.constrain._v07_3a.continuity import hybrid_continuity_required
from ai4.constrain._v07_3b.context import HybridConfiguration, HybridContextBuilder
from ai4.constrain._v07_3b.snapshot import detect_identity_drift
from ai4.constrain._v07_3c.install import HybridOrchestrator
from ai4.constrain._v07_3c.loop import run_governing_loop
from ai4.constrain._v07_3c.observe import bind_role_scoped_identities, mint_runtime_provenance
from ai4.constrain._v07_3c.persist import (
    FileContinuityStore,
    load_session_document,
    persist_report_document,
    persist_success_session,
    repair_continuity,
)
from ai4.constrain._v07_3c.ready import Ready, hybrid_ready
from ai4.constrain._v07_3c.report import (
    abort_semantic_block,
    build_abort_report,
    build_success_report,
    success_semantic_block,
)
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.evaluator_wall import packaged_policy_rubrics
from ai4.constrain.ext import (
    PROPOSAL_RESOLVED_AS_ARGUMENT,
    PROPOSAL_RESOLVED_AS_CONFIG,
    PROPOSAL_RESOLVED_AS_CUSTOM,
    ProviderBackend,
    bind_evaluator,
    evaluator_identity,
    evaluator_impl_fingerprint,
    evaluator_resolved_as,
    resolve_proposal,
)
from ai4.constrain.governing import require_governing_integration
from ai4.constrain.report import (
    CallTelemetry,
    EvaluatorIdentity,
    ProposalIdentity,
    Telemetry,
    loop_terminal,
    product_decision,
)
from ai4.constrain.runtime import RuntimeConfig
from ai4.constrain.semantic_examiner import LOCKED_OBSERVATION_PROMPT_SHA256
from ai4.constrain.semantic_fuse import LOCKED_POLICY_MAP_SHA256, LOCKED_REGISTRY_SHA256


def _rubric_versions() -> dict[str, str]:
    return {str(item.id): str(item.version) for item in packaged_policy_rubrics()}


def _proposal_identity(resolution) -> ProposalIdentity:
    return ProposalIdentity(
        provider_id=resolution.provider_id,
        model=resolution.model,
        resolved_as=resolution.resolved_as,
    )


def _evaluator_identity(evaluator) -> EvaluatorIdentity:
    return EvaluatorIdentity(
        evaluator_id=evaluator_identity(evaluator),
        evaluator_version=str(getattr(evaluator, "version", "") or ""),
        resolved_as=str(getattr(evaluator, "resolved_as", "") or evaluator_resolved_as(evaluator)),
    )


def _call_telemetry(completion: Completion, *, kind: str) -> CallTelemetry:
    return CallTelemetry(
        model=str(completion.model or ""),
        prompt_tokens=int(completion.prompt_tokens),
        completion_tokens=int(completion.completion_tokens),
        latency_ms=float(completion.latency_ms),
        estimated_usd=float(completion.estimated_usd),
        kind=kind,
    )


def _telemetry(proposal: ProposalIdentity, completions: tuple[Completion, ...], *, supplied_first: bool) -> Telemetry:
    per_call: list[CallTelemetry] = []
    for index, completion in enumerate(completions):
        if supplied_first and index == 0:
            kind = "supplied"
        elif index:
            kind = "revise"
        else:
            kind = "complete"
        per_call.append(_call_telemetry(completion, kind=kind))
    model = per_call[-1].model if per_call else proposal.model
    return Telemetry(
        provider=proposal.provider_id,
        model=model,
        calls=len(per_call),
        prompt_tokens=sum(item.prompt_tokens for item in per_call),
        completion_tokens=sum(item.completion_tokens for item in per_call),
        latency_ms=sum(item.latency_ms for item in per_call),
        estimated_usd=round(sum(item.estimated_usd for item in per_call), 8),
        per_call=tuple(per_call),
    )


def _continuity_payloads(document: HybridSessionDocument | None, report_payload: dict[str, Any] | None) -> tuple[object, ...]:
    payloads: list[object] = []
    if document is not None:
        payloads.append({"schema_version": document.schema_version})
        payloads.extend(turn.report.to_dict() for turn in document.off_state.turns)
    if report_payload is not None:
        payloads.append(report_payload)
    return tuple(payloads)


def _empty_telemetry(proposal: ProposalIdentity) -> Telemetry:
    return Telemetry(
        provider=proposal.provider_id,
        model=proposal.model,
        calls=0,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0.0,
        estimated_usd=0.0,
    )


def execute_configured(
    *,
    prompt: str,
    proposal: str | None,
    provider: str | ProviderBackend | None,
    evaluator: object,
    cfg: RuntimeConfig,
    specified: tuple[str, ...],
    prompt_id: str,
) -> object | None:
    """Return a governing report, or None to keep the frozen OFF path."""
    if getattr(cfg, "integration", None) is None:
        return None
    integration = require_governing_integration(cfg.integration)
    session_store = integration.persist_store or FileContinuityStore(integration.session_dir)
    report_store = integration.report_store or FileContinuityStore(
        integration.session_dir, suffix=".report.json"
    )
    eval_spec = evaluator if evaluator is not None else cfg.evaluator_id
    backend = bind_evaluator(
        eval_spec,
        rubric_set=cfg.rubric_set,
        resolved_as=evaluator_resolved_as(evaluator),
    )
    if provider is None:
        resolution = resolve_proposal(cfg.provider_id, resolved_as=PROPOSAL_RESOLVED_AS_CONFIG)
        observable_proposer = resolution.backend
    elif isinstance(provider, str):
        resolution = resolve_proposal(provider, resolved_as=PROPOSAL_RESOLVED_AS_ARGUMENT)
        observable_proposer = resolution.backend
    else:
        resolution = resolve_proposal(provider, resolved_as=PROPOSAL_RESOLVED_AS_CUSTOM)
        observable_proposer = provider
    identity = _proposal_identity(resolution)
    eval_ident = _evaluator_identity(backend)

    prior = load_session_document(session_store, integration.session_id)
    prior_report = report_store.load(integration.session_id)
    ever_on = bool(prior.identity.ever_on) if prior is not None else False
    ever_required = bool(prior.ever_required) if prior is not None else False
    payloads = _continuity_payloads(prior, prior_report)
    repaired_on, repaired_required, continuity = repair_continuity(
        ever_on=ever_on,
        ever_required=ever_required,
        payloads=payloads,
    )
    required = hybrid_continuity_required(continuity)

    clock = integration.clock if callable(integration.clock) else time.monotonic
    deadline = float(clock()) + float(cfg.timeout_s)
    authority = RunBudgetAuthority(
        deadline_monotonic=deadline,
        max_proposal_completions=integration.max_proposal_completions,
        max_examiner_calls=integration.max_examiner_calls,
        max_usd=float(integration.max_usd),
        clock=clock if callable(integration.clock) else None,
    )
    trusted = TrustedProductConfig(
        proposer_provider_id=integration.proposer_provider_id,
        proposer_model_id=integration.proposer_model_id,
        examiner_provider_id=integration.examiner_provider_id,
        examiner_model_id=integration.examiner_model_id,
        examiner_id=integration.examiner_id,
        examiner_version=integration.examiner_version,
        observation_prompt_sha256=integration.observation_prompt_sha256,
    )
    configuration = HybridConfiguration(
        trusted=trusted,
        origin_allowlist=integration.origin_allowlist,
        proposer_requested_origin=integration.proposer_requested_origin,
        examiner_requested_origin=integration.examiner_requested_origin,
        max_usd=float(integration.max_usd),
        deadline_monotonic=deadline,
        max_proposal_completions=integration.max_proposal_completions,
        max_examiner_calls=integration.max_examiner_calls,
        observation_prompt_sha256=integration.observation_prompt_sha256,
        registry_sha256=integration.registry_sha256,
        policy_map_sha256=integration.policy_map_sha256,
        fuse_id=integration.fuse_id,
        semantic_schema_version=integration.semantic_schema_version,
        semantic_config_version=integration.semantic_config_version,
        evaluator_identity=evaluator_identity(backend),
        evaluator_fingerprint=evaluator_impl_fingerprint(eval_spec),
    )

    def _abort(abort: HybridExecutionAbort, *, provenance=None) -> object:
        from ai4.constrain._v07_3b.provenance import bundle_claims, collect_configured

        if provenance is None:
            provenance = bundle_claims(
                [collect_configured(f"{trusted.proposer_provider_id}/{trusted.proposer_model_id}")]
            )
        semantic = abort_semantic_block(
            abort_class=abort.abort_class,
            provenance=provenance,
            observation_prompt_sha256=LOCKED_OBSERVATION_PROMPT_SHA256,
            registry_sha256=LOCKED_REGISTRY_SHA256,
            policy_map_sha256=LOCKED_POLICY_MAP_SHA256,
            detail=abort.message or abort.abort_class,
            examiner_id=trusted.examiner_id,
            examiner_version=trusted.examiner_version,
            provider_id=trusted.examiner_provider_id,
            model_id=trusted.examiner_model_id,
        )
        return build_abort_report(
            prompt=prompt,
            prompt_id=prompt_id,
            specified=specified,
            initial_proposal=proposal or "",
            telemetry=_empty_telemetry(identity),
            proposal=identity,
            evaluator=eval_ident,
            rubric_versions=_rubric_versions(),
            semantic=semantic,
            reason=f"{abort.abort_class}: {abort.message}" if abort.message else abort.abort_class,
            redact=cfg.redact,
        )

    try:
        proposer_bundle, examiner_bundle, proposer_transport, examiner_transport, _p_obs, _e_obs = (
            mint_runtime_provenance(
                configured_label=f"{trusted.proposer_provider_id}/{trusted.proposer_model_id}",
                examiner_configured_label=(
                    f"{trusted.examiner_provider_id}/{trusted.examiner_model_id}"
                ),
                proposer=observable_proposer,
                examiner=integration.examiner_backend,
                proposer_requested_origin=integration.proposer_requested_origin,
                examiner_requested_origin=integration.examiner_requested_origin,
                origin_allowlist=integration.origin_allowlist,
            )
        )
        context = bind_role_scoped_identities(
            HybridContextBuilder(configuration)
            .with_runtime_provenance(proposer_bundle)
            .with_examiner_runtime_provenance(examiner_bundle)
            .with_continuity(
                ContinuitySnapshot(
                    ever_on=repaired_on,
                    ever_required=repaired_required,
                    persisted_report_schema_0_2_0=continuity.persisted_report_schema_0_2_0,
                    persisted_semantic=continuity.persisted_semantic,
                )
            )
            .with_budget_authority(authority)
            .with_transport(proposer=proposer_transport, examiner=examiner_transport)
            .with_accounts(
                proposer=_p_obs["account_id"],
                examiner=_e_obs["account_id"],
            )
            .with_credentials(
                proposer=integration.proposer_credential,
                examiner=integration.examiner_credential,
            )
            .with_session_objects(
                proposer=observable_proposer,
                examiner=integration.examiner_backend,
            )
            .build()
        )
    except HybridExecutionAbort as exc:
        if required:
            return _abort(
                HybridExecutionAbort("continuity_required_not_ready", exc.abort_class),
            )
        if exc.abort_class in {"origin_allowlist_failure", "schema_invalid", "caller_config_pin_forbidden"}:
            raise ConstraintExecutionError(str(exc)) from exc
        return None

    conclusion = hybrid_ready(context)
    if isinstance(conclusion, NotReady):
        if required:
            return _abort(
                HybridExecutionAbort("continuity_required_not_ready", conclusion.reason),
                provenance=context.provenance,
            )
        return None
    if not isinstance(conclusion, Ready):
        raise ConstraintExecutionError("hybrid_ready returned an unknown conclusion")

    if required and prior is not None and prior.identity.artifact_snapshot is not None:
        try:
            detect_identity_drift(prior.identity.artifact_snapshot, context.identity_snapshot)
        except HybridExecutionAbort as exc:
            return _abort(exc, provenance=context.provenance)

    orchestrator = HybridOrchestrator(session_store, session_id=integration.session_id)
    try:
        orchestrator.install(context)
    except HybridExecutionAbort as exc:
        return _abort(exc, provenance=context.provenance)

    middleware = ConstraintMiddleware(
        rubrics=packaged_policy_rubrics(),
        max_revision_rounds=cfg.max_revision_rounds,
    )
    try:
        last, completions, steps, used, state, reason = run_governing_loop(
            orchestrator=orchestrator,
            context=context,
            provider=observable_proposer,
            examiner_backend=integration.examiner_backend,
            evaluator=backend,
            middleware=middleware,
            prompt=prompt,
            proposal=proposal,
            specified=specified,
            max_revision_rounds=cfg.max_revision_rounds,
            reserve_usd_proposal=float(integration.reserve_usd_proposal),
            reserve_usd_examiner=float(integration.reserve_usd_examiner),
        )
        semantic = success_semantic_block(
            bound=last.bound,
            det_eval=last.det_eval,
            fuse_result=last.fuse_result,
            provenance=context.provenance,
            observation_prompt_sha256=context.configuration.observation_prompt_sha256,
            registry_sha256=context.configuration.registry_sha256,
            policy_map_sha256=context.configuration.policy_map_sha256,
        )
        report = build_success_report(
            prompt=prompt,
            prompt_id=prompt_id,
            specified=specified,
            initial_proposal=completions[0].text if completions else (proposal or ""),
            final_output=last.text if state is not TerminalState.REFUSE else last.text,
            fused_eval=last.walled,
            decision=last.decision,
            product_decision=product_decision(state) or last.decision.action,
            terminal=loop_terminal(state, reason),
            revision_trace=steps,
            telemetry=_telemetry(identity, completions, supplied_first=proposal is not None),
            proposal=identity,
            evaluator=eval_ident,
            rubric_versions=_rubric_versions(),
            semantic=semantic,
            redact=cfg.redact,
        )
        current = load_session_document(session_store, integration.session_id)
        if current is None:
            raise HybridExecutionAbort("backend_error", "continuity marker missing after install")
        persist_success_session(
            session_store,
            session_id=integration.session_id,
            document=current,
        )
        persist_report_document(
            report_store,
            session_id=integration.session_id,
            payload=report.to_dict(),
        )
        return report
    except HybridExecutionAbort as exc:
        return _abort(exc, provenance=context.provenance)


__all__ = ["execute_configured"]
