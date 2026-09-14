"""Governing hybrid loop after successful install (V07-3C).

Legal flow only:
  proposal → det eval → semantic observe → map → fuse → rebuild →
  packaged wall → ConstraintMiddleware.decide → arbitration →
  accept / revise / refuse. Bounded revision re-runs semantic each round.

Once installed, incomplete transactions abort. decide() is legal only
for a complete fused post-wall evaluation. decide(timed_out=True) /
decide(budget_exhausted=True) are never used to manufacture terminals.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.agents.base_agent import TerminalState
from src.control_contract import next_loop_action, parse_d_decision
from src.constraints.constraint_middleware import ConstraintDecision, ConstraintMiddleware
from src.providers.base import Completion
from src.shards.models import Evaluation
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.rebuild import rebuild_fused_evaluation
from ai4.constrain._v07_3b.budget import (
    BudgetAwareProviderAdapter,
    require_known_actual_usd,
    reserve_examiner_lane,
)
from ai4.constrain._v07_3b.context import HybridContext
from ai4.constrain._v07_3b.feedback import format_hybrid_revision_feedback
from ai4.constrain._v07_3b.snapshot import snapshot_from_context
from ai4.constrain._v07_3c.install import HybridOrchestrator
from ai4.constrain._v07_3c.observe import (
    assert_account_session_match,
    assert_origin_matches,
    assert_served_model_matches,
    read_connection_observation,
)
from ai4.constrain.errors import SemanticExaminerError, SemanticFindingsError, SemanticFuseError
from ai4.constrain.evaluator_wall import overlay_packaged_policy
from ai4.constrain.ext import EvaluatorBackend
from ai4.constrain.report import CallTelemetry, RevisionStep, shard_records, arbitration_record
from ai4.constrain.semantic_examiner import observation_prompt_sha256, observe_semantic_candidate
from ai4.constrain.semantic_findings import BoundSemanticFindings
from ai4.constrain.semantic_fuse import PackagedFuseResult, map_and_fuse_v2

_STATUS_TO_ABORT = {
    "timeout": "wall_deadline_exhausted",
    "backend_error": "backend_error",
    "schema_invalid": "schema_invalid",
    "injection_suspected": "injection_suspected",
    "empty_parse": "empty_parse",
}


@dataclass
class RoundResult:
    text: str
    completion: Completion
    det_eval: Evaluation
    bound: BoundSemanticFindings
    fuse_result: PackagedFuseResult
    fused_eval: Evaluation
    walled: Evaluation
    decision: ConstraintDecision
    feedback: str


def _quote_sha256(text: str, start: int, end: int) -> str:
    span = text[start:end].encode("utf-8")
    return hashlib.sha256(span).hexdigest()


def _det_score_map(evaluation: Evaluation) -> dict[str, float]:
    return {item.shard_id: float(item.score) for item in evaluation.shard_scores}


def _translate_examiner_failure(exc: Exception) -> HybridExecutionAbort:
    if isinstance(exc, HybridExecutionAbort):
        return exc
    text = str(exc).lower()
    for status, abort_class in _STATUS_TO_ABORT.items():
        if status in text:
            return HybridExecutionAbort(abort_class, str(exc))
    if "schema" in text:
        return HybridExecutionAbort("schema_invalid", str(exc))
    if "injection" in text:
        return HybridExecutionAbort("injection_suspected", str(exc))
    if "empty" in text or "parse" in text:
        return HybridExecutionAbort("empty_parse", str(exc))
    return HybridExecutionAbort("backend_error", str(exc))


def _assert_installed_identity(orchestrator: HybridOrchestrator, context: HybridContext) -> None:
    orchestrator.assert_identity_stable(snapshot_from_context(context))


def _assert_role_continuity(_role: str, expected: dict[str, str], observed: dict[str, str]) -> None:
    assert_origin_matches(expected=expected["peer_origin"], observed=observed["peer_origin"])
    assert_account_session_match(
        expected_account=expected["account_id"],
        observed_account=observed["account_id"],
        expected_session=expected["session_token"],
        observed_session=observed["session_token"],
    )
    assert_served_model_matches(expected=expected["served_model"], observed=observed["served_model"])


def _recheck_runtime_provenance(
    *,
    orchestrator: HybridOrchestrator,
    provider: object,
    examiner: object,
) -> None:
    installed = orchestrator.installed
    if installed is None:
        raise HybridExecutionAbort("schema_invalid", "runtime provenance recheck requires install")
    proposer_obs = read_connection_observation(provider, role="proposer")
    examiner_obs = read_connection_observation(examiner, role="examiner")
    _assert_role_continuity("proposer", installed.proposer_observation, proposer_obs)
    _assert_role_continuity("examiner", installed.examiner_observation, examiner_obs)


def _observe_semantic(
    *,
    candidate: str,
    context: HybridContext,
    examiner_backend: object,
    authority,
    reserve_usd: float,
) -> BoundSemanticFindings:
    if authority is None:
        raise HybridExecutionAbort("schema_invalid", "shared budget authority is required")
    reservation = reserve_examiner_lane(authority, usd=reserve_usd)
    executing = authority.begin_execute(reservation)
    try:
        bound = observe_semantic_candidate(
            candidate,
            examiner_backend,
            examiner_id=context.configuration.trusted.examiner_id,
            examiner_version=context.configuration.trusted.examiner_version,
            provider_id=context.configuration.trusted.examiner_provider_id,
            model_id=context.configuration.trusted.examiner_model_id,
            proposer_provider_id=context.configuration.trusted.proposer_provider_id,
            proposer_model_id=context.configuration.trusted.proposer_model_id,
        )
        prompt_digest = observation_prompt_sha256()
        if prompt_digest != context.configuration.observation_prompt_sha256:
            raise HybridExecutionAbort(
                "observation_prompt_hash_mismatch",
                "locked observation prompt hash drifted at observe time",
            )
        if bound.payload.status != "ok":
            abort_class = _STATUS_TO_ABORT.get(bound.payload.status, "backend_error")
            raise HybridExecutionAbort(abort_class, f"semantic status {bound.payload.status}")
        actual = require_known_actual_usd(examiner_backend, field="last_estimated_usd")
        authority.commit(executing, actual_usd=actual)
        return bound
    except HybridExecutionAbort:
        _release_unless_committed(authority, executing)
        raise
    except (SemanticExaminerError, SemanticFindingsError) as exc:
        _release_unless_committed(authority, executing)
        raise _translate_examiner_failure(exc) from exc
    except Exception as exc:
        _release_unless_committed(authority, executing)
        raise HybridExecutionAbort("backend_error", str(exc)) from exc


def _release_unless_committed(authority, handle) -> None:
    """Release only when spend was not honestly committed.

    Consult the authority's stored handle, not the caller's frozen copy.
    A valid known cost that then exceeds max USD is already committed;
    do not unwind that actual or invent a zero.
    """
    try:
        current = authority._reservations.get(handle.reservation_id)
        if current is not None and current.state == "committed":
            return
        if handle.state != "committed":
            authority.release(handle)
    except HybridExecutionAbort:
        pass


def _hybrid_feedback(bound: BoundSemanticFindings) -> str:
    pairs = [(item.finding.class_id, item.finding.observation_code) for item in bound.findings]
    if not pairs:
        raise HybridExecutionAbort(
            "schema_invalid",
            "missing feedback template; empty-ok cannot emit raw fallback feedback",
        )
    return format_hybrid_revision_feedback(pairs)


def _call_telemetry(completion: Completion, *, kind: str) -> CallTelemetry:
    return CallTelemetry(
        model=str(completion.model or ""),
        prompt_tokens=int(completion.prompt_tokens),
        completion_tokens=int(completion.completion_tokens),
        latency_ms=float(completion.latency_ms),
        estimated_usd=float(completion.estimated_usd),
        kind=kind,
    )


def run_governing_loop(
    *,
    orchestrator: HybridOrchestrator,
    context: HybridContext,
    provider: object,
    examiner_backend: object,
    evaluator: EvaluatorBackend,
    middleware: ConstraintMiddleware,
    prompt: str,
    proposal: str | None,
    specified: tuple[str, ...],
    max_revision_rounds: int,
    reserve_usd_proposal: float,
    reserve_usd_examiner: float,
) -> tuple[RoundResult, tuple[Completion, ...], tuple[RevisionStep, ...], int, TerminalState, str]:
    """Run the singular governing loop. Caller must have already installed."""
    if orchestrator.installed is None:
        raise HybridExecutionAbort("schema_invalid", "governing loop requires successful install")
    _assert_installed_identity(orchestrator, context)
    _recheck_runtime_provenance(
        orchestrator=orchestrator,
        provider=provider,
        examiner=examiner_backend,
    )
    authority = context.budget_authority
    budgeted = BudgetAwareProviderAdapter(
        provider,
        budget_authority=authority,
        reserve_usd=reserve_usd_proposal,
    )
    completions: list[Completion] = []
    steps: list[RevisionStep] = []
    used = 0
    current = ""
    last: RoundResult | None = None

    def _propose_first() -> Completion:
        orchestrator.mark_hybrid_operation_started()
        if proposal is not None:
            model = getattr(provider, "observed_served_model", None) or getattr(provider, "name", "supplied")
            completion = Completion(text=proposal, model=str(model), estimated_usd=0.0)
            # Supplied drafts still consume the proposal-completion lane.
            reservation = authority.reserve_proposal_completion(usd=0.0)
            executing = authority.begin_execute(reservation)
            authority.commit(executing, actual_usd=0.0)
            return completion
        return budgeted.complete(system="Answer the user. Be concise.", user=prompt)

    try:
        first = _propose_first()
    except HybridExecutionAbort:
        raise
    except Exception as exc:
        raise HybridExecutionAbort("backend_error", f"proposal failed: {exc}") from exc
    completions.append(first)
    current = first.text
    if first.model:
        assert_served_model_matches(
            expected=context.provenance.observed_value("served_model_observed") or "",
            observed=str(first.model),
        )
    _recheck_runtime_provenance(
        orchestrator=orchestrator,
        provider=provider,
        examiner=examiner_backend,
    )

    while True:
        _assert_installed_identity(orchestrator, context)
        _recheck_runtime_provenance(
            orchestrator=orchestrator,
            provider=provider,
            examiner=examiner_backend,
        )
        det_eval = evaluator.evaluate(current)
        bound = _observe_semantic(
            candidate=current,
            context=context,
            examiner_backend=examiner_backend,
            authority=authority,
            reserve_usd=reserve_usd_examiner,
        )
        for item in bound.findings:
            expected = _quote_sha256(current, item.finding.span.start, item.finding.span.end)
            if item.finding.quote_sha256 != expected:
                raise HybridExecutionAbort(
                    "identity_drift",
                    "claim fingerprint/quote is not bound to the current candidate",
                )
        try:
            fuse_result = map_and_fuse_v2(_det_score_map(det_eval), bound)
        except SemanticFuseError as exc:
            raise HybridExecutionAbort("fuse_failure", str(exc)) from exc
        fused = rebuild_fused_evaluation(det_eval, fuse_result)
        walled = overlay_packaged_policy(fused)
        decision = middleware.decide(walled, revision_round=used)
        feedback = ""
        if decision.action == "revise":
            feedback = _hybrid_feedback(bound)
        last = RoundResult(
            text=current,
            completion=completions[-1],
            det_eval=det_eval,
            bound=bound,
            fuse_result=fuse_result,
            fused_eval=fused,
            walled=walled,
            decision=decision,
            feedback=feedback,
        )
        loop_decision = parse_d_decision(
            action=decision.action,
            reason=decision.reason,
            feedback=feedback,
        )
        step = next_loop_action(
            loop_decision,
            revision_rounds_used=used,
            max_revision_rounds=max_revision_rounds,
            budget_left=True,
            timed_out=False,
        )
        if step == "accept":
            return last, tuple(completions), tuple(steps), used, TerminalState.ACCEPT, decision.reason
        if step == "refuse":
            return last, tuple(completions), tuple(steps), used, TerminalState.REFUSE, decision.reason
        if step in {"timeout", "emit_exhausted"} and decision.action != "revise":
            raise HybridExecutionAbort(
                "proposal_completion_exhausted",
                "incomplete hybrid transaction cannot manufacture a timeout terminal",
            )
        if step == "emit_exhausted":
            return last, tuple(completions), tuple(steps), used, TerminalState.REVISE, decision.reason
        if step != "revise_call":
            raise HybridExecutionAbort("schema_invalid", f"unknown loop step {step!r}")
        previous = current
        try:
            revised = budgeted.revise(
                system="Answer the user. Be concise.",
                user=prompt,
                draft=current,
                feedback=feedback,
            )
        except HybridExecutionAbort:
            raise
        except Exception as exc:
            raise HybridExecutionAbort("backend_error", f"proposal revision failed: {exc}") from exc
        completions.append(revised)
        used += 1
        steps.append(
            RevisionStep(
                round=used,
                input_text=previous,
                output_text=revised.text,
                shard_evaluations=shard_records(walled, prompt_specified_shards=specified),
                arbitration=arbitration_record(decision.arbitration),
                action=decision.action,
                reason=decision.reason,
                feedback=feedback,
                telemetry=_call_telemetry(revised, kind="revise"),
                captured=True,
            )
        )
        if revised.text == current:
            return last, tuple(completions), tuple(steps), used, TerminalState.REPEATED, "repeated candidate"
        current = revised.text
        if used > max_revision_rounds:
            raise HybridExecutionAbort(
                "identity_drift",
                "revision bound exceeded; semantic module cannot enlarge the budget",
            )


__all__ = [
    "RoundResult",
    "run_governing_loop",
]
