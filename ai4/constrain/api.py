"""Public ``run`` / ``evaluate`` wrapping frozen v0.1 D-path semantics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from src.agents.base_agent import AgentConfig, RunResult
from src.agents.recursive_agent import ConstrainedAgent
from src.constraints.constraint_middleware import ConstraintDecision, ConstraintMiddleware
from src.providers.base import Completion
from src.providers.live import LiveSpendError
from src.shards.models import Evaluation
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.ext import (
    EVALUATE_ONLY_PROVIDER_ID,
    EvaluatorBackend,
    PROPOSAL_RESOLVED_AS_ARGUMENT,
    PROPOSAL_RESOLVED_AS_CONFIG,
    PROPOSAL_RESOLVED_AS_CUSTOM,
    PROPOSAL_RESOLVED_AS_EVALUATE,
    ProviderBackend,
    REQUIRED_SHARD_IDS,
    SECRET_METADATA_KEYS,
    assert_complete_evaluation,
    bind_evaluator,
    checked_completion,
    evaluator_identity,
    evaluator_resolved_as,
    resolve_proposal,
)
from ai4.constrain.evaluator_wall import packaged_policy_rubrics
from ai4.constrain.report import (
    CallTelemetry,
    DecisionReport,
    EvaluatorIdentity,
    ProposalIdentity,
    RevisionStep,
    Telemetry,
    VersionInfo,
    arbitration_record,
    loop_terminal,
    outcome_kind_for,
    product_decision,
    product_decision_from_action,
    shard_records,
)
from ai4.constrain.runtime import (
    ARBITRATION_VERSION,
    CONDITION,
    EVIDENCE_CLASS,
    PROTOCOL_VERSION,
    REPORT_SCHEMA_VERSION,
    RUNTIME_VERSION,
    RuntimeConfig,
)


class _ProposalFirstProvider:
    """Issue a caller-supplied draft as the first completion, then delegate."""

    def __init__(self, inner: ProviderBackend, proposal: str) -> None:
        self._inner = inner
        self._proposal = proposal
        self._issued = False
        self.name = getattr(inner, "name", "proposal-first")

    def complete(self, *, system: str, user: str) -> Completion:
        if not self._issued:
            self._issued = True
            model = getattr(self._inner, "model", None) or getattr(self._inner, "name", "supplied")
            return checked_completion(Completion(text=self._proposal, model=str(model)))
        return self._inner.complete(system=system, user=user)

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        return self._inner.revise(system=system, user=user, draft=draft, feedback=feedback)


class RecordingMiddleware:
    """Capture live decide() results. Never used to replay an evaluator."""

    def __init__(self, inner: ConstraintMiddleware) -> None:
        self._inner = inner
        self.rubrics = inner.rubrics
        self.max_revision_rounds = inner.max_revision_rounds
        self.captures: list[tuple[Evaluation, ConstraintDecision, str]] = []

    def decide(
        self,
        evaluation: Evaluation,
        *,
        revision_round: int,
        timed_out: bool = False,
        budget_exhausted: bool = False,
    ) -> ConstraintDecision:
        decision = self._inner.decide(
            evaluation,
            revision_round=revision_round,
            timed_out=timed_out,
            budget_exhausted=budget_exhausted,
        )
        feedback = ""
        if decision.action == "revise":
            feedback = self._inner.format_feedback(decision, evaluation)
        self.captures.append((evaluation, decision, feedback))
        return decision

    def format_feedback(self, decision: ConstraintDecision, evaluation: Evaluation) -> str:
        return self._inner.format_feedback(decision, evaluation)


def _validate_specified(specified: Sequence[str] | None) -> tuple[str, ...]:
    specified_shards = tuple(specified or ())
    unknown = [item for item in specified_shards if item not in REQUIRED_IDS]
    if unknown:
        raise ConstraintExecutionError(
            f"Unknown prompt_specified_shards {unknown}. "
            f"This is a prompt annotation only; frozen D still evaluates "
            f"{REQUIRED_SHARD_IDS}."
        )
    return specified_shards


def _rubric_versions() -> dict[str, str]:
    return {str(item.id): str(item.version) for item in packaged_policy_rubrics()}


def _versions(evaluator: EvaluatorBackend) -> VersionInfo:
    return VersionInfo(
        runtime_version=RUNTIME_VERSION,
        report_schema_version=REPORT_SCHEMA_VERSION,
        protocol=PROTOCOL_VERSION,
        condition=CONDITION,
        evidence_class=EVIDENCE_CLASS,
        rubric_set="v0.1",
        evaluator_id=evaluator_identity(evaluator),
        evaluator_version=str(getattr(evaluator, "version", "") or ""),
        arbitration=ARBITRATION_VERSION,
        rubric_versions=_rubric_versions(),
    )


def _evaluator_provenance(evaluator: EvaluatorBackend) -> EvaluatorIdentity:
    resolved_as = str(getattr(evaluator, "resolved_as", "") or evaluator_resolved_as(evaluator))
    return EvaluatorIdentity(
        evaluator_id=evaluator_identity(evaluator),
        evaluator_version=str(getattr(evaluator, "version", "") or ""),
        resolved_as=resolved_as,
    )


def _proposal_identity(resolution) -> ProposalIdentity:
    return ProposalIdentity(
        provider_id=resolution.provider_id,
        model=resolution.model,
        resolved_as=resolution.resolved_as,
    )


def _evaluate_only_proposal() -> ProposalIdentity:
    return ProposalIdentity(
        provider_id=EVALUATE_ONLY_PROVIDER_ID,
        model="",
        resolved_as=PROPOSAL_RESOLVED_AS_EVALUATE,
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


def _telemetry(
    proposal: ProposalIdentity,
    completions: Sequence[Completion],
    *,
    supplied_first: bool,
) -> Telemetry:
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


def _middleware(max_revision_rounds: int) -> ConstraintMiddleware:
    return ConstraintMiddleware(
        rubrics=packaged_policy_rubrics(),
        max_revision_rounds=max_revision_rounds,
    )


def _maybe_redact(report: DecisionReport, redact: bool) -> DecisionReport:
    if redact:
        return report.with_redaction()
    return replace(report, redacted=False)


def _captured_trace(
    *,
    completions: Sequence[Completion],
    captures: Sequence[tuple[Evaluation, ConstraintDecision, str]],
    prompt_specified_shards: tuple[str, ...],
) -> tuple[RevisionStep, ...]:
    if len(completions) < 2:
        return ()
    unused = list(captures)
    steps: list[RevisionStep] = []
    for index, completion in enumerate(completions[1:], start=1):
        previous = completions[index - 1].text
        match_i = next((i for i, (ev, _dec, _fb) in enumerate(unused) if ev.text == previous), None)
        if match_i is None:
            raise ConstraintExecutionError(
                "Missing captured loop state for a revision step; "
                "refusing to reconstruct the trace by re-evaluating"
            )
        evaluation, decision, feedback = unused.pop(match_i)
        steps.append(
            RevisionStep(
                round=index,
                input_text=previous,
                output_text=completion.text,
                shard_evaluations=shard_records(
                    evaluation, prompt_specified_shards=prompt_specified_shards
                ),
                arbitration=arbitration_record(decision.arbitration),
                action=decision.action,
                reason=decision.reason,
                feedback=feedback,
                telemetry=_call_telemetry(completion, kind="revise"),
                captured=True,
            )
        )
    return tuple(steps)


def _driving_from_capture(
    result: RunResult,
    captures: Sequence[tuple[Evaluation, ConstraintDecision, str]],
) -> Evaluation | None:
    if not result.completions:
        return None
    if result.failed_evaluation is not None:
        return assert_complete_evaluation(result.failed_evaluation)
    last_text = result.completions[-1].text
    for evaluation, _decision, _feedback in reversed(captures):
        if evaluation.text == last_text:
            return evaluation
    if result.evaluation is not None and result.evaluation.text == last_text:
        return assert_complete_evaluation(result.evaluation)
    return None


def _report_from_run(
    *,
    result: RunResult,
    prompt: str,
    evaluator: EvaluatorBackend,
    proposal: ProposalIdentity,
    captures: Sequence[tuple[Evaluation, ConstraintDecision, str]],
    supplied_first: bool,
    prompt_specified_shards: tuple[str, ...],
    prompt_id: str,
) -> DecisionReport:
    driving = _driving_from_capture(result, captures)
    if driving is None:
        shards = None
        arbitration = None
    else:
        shards = shard_records(driving, prompt_specified_shards=prompt_specified_shards)
        last = next((item for item in reversed(captures) if item[0] is driving or item[0].text == driving.text), None)
        if last is None:
            raise ConstraintExecutionError(
                "Driving evaluation was not captured during the loop; "
                "refusing to re-arbitrate from a reconstructed score"
            )
        arbitration = arbitration_record(last[1].arbitration)
    initial = result.completions[0].text if result.completions else ""
    model = proposal.model
    if result.completions:
        last_model = str(result.completions[-1].model or "")
        if last_model:
            model = last_model
    identity = ProposalIdentity(
        provider_id=proposal.provider_id,
        model=model,
        resolved_as=proposal.resolved_as,
    )
    return DecisionReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="constrained_loop",
        outcome_kind=outcome_kind_for(result.state),
        prompt=prompt,
        prompt_id=prompt_id or result.prompt_id,
        prompt_specified_shards=prompt_specified_shards,
        enforced_shards=REQUIRED_IDS,
        shard_control_scope="all_required_v0.1",
        candidate_evaluated=driving is not None,
        initial_proposal=initial,
        shard_evaluations=shards,
        arbitration=arbitration,
        decision=product_decision(result.state),
        terminal=loop_terminal(result.state, result.reason),
        decision_reason=result.reason,
        revision_trace=_captured_trace(
            completions=result.completions,
            captures=captures,
            prompt_specified_shards=prompt_specified_shards,
        ),
        final_output=result.text,
        telemetry=_telemetry(identity, result.completions, supplied_first=supplied_first),
        proposal=identity,
        evaluator=_evaluator_provenance(evaluator),
        versions=_versions(evaluator),
        redacted=False,
    )


def evaluate(
    text: str,
    *,
    prompt: str = "",
    evaluator: str | EvaluatorBackend | None = None,
    rubric_set: str = "v0.1",
    prompt_specified_shards: Sequence[str] | None = None,
    prompt_id: str = "",
    max_revision_rounds: int = 2,
    redact: bool = True,
) -> DecisionReport:
    """Score existing text with frozen v0.1 shards. No model calls.

    Frozen D still scores all five shards. ``prompt_specified_shards`` is a
    prompt annotation used only for applicability projection, not to skip
    enforcement.

    The reported ``decision`` is the first-round middleware action.
    ``terminal`` is null because the revision loop did not run; it is not
    a frozen loop label.
    """
    if not isinstance(text, str):
        raise ConstraintExecutionError("evaluate() requires a text string")
    specified = _validate_specified(prompt_specified_shards)
    backend = bind_evaluator(
        evaluator,
        rubric_set=rubric_set,
        resolved_as=evaluator_resolved_as(evaluator),
    )
    evaluation = backend.evaluate(text)
    middleware = _middleware(max_revision_rounds)
    decision = middleware.decide(evaluation, revision_round=0)
    action = product_decision_from_action(decision.action)
    report = DecisionReport(
        schema_version=REPORT_SCHEMA_VERSION,
        mode="evaluate_only",
        outcome_kind="constraint",
        prompt=prompt,
        prompt_id=prompt_id,
        prompt_specified_shards=specified,
        enforced_shards=REQUIRED_IDS,
        shard_control_scope="all_required_v0.1",
        candidate_evaluated=True,
        initial_proposal=text,
        shard_evaluations=shard_records(evaluation, prompt_specified_shards=specified),
        arbitration=arbitration_record(decision.arbitration),
        decision=action,
        terminal=None,
        decision_reason=decision.reason,
        revision_trace=(),
        final_output=text,
        telemetry=Telemetry(
            provider=EVALUATE_ONLY_PROVIDER_ID,
            model="",
            calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0.0,
            estimated_usd=0.0,
        ),
        proposal=_evaluate_only_proposal(),
        evaluator=_evaluator_provenance(backend),
        versions=_versions(backend),
        redacted=False,
    )
    return _maybe_redact(report, redact)


def run(
    prompt: str,
    *,
    proposal: str | None = None,
    provider: str | ProviderBackend | None = None,
    evaluator: str | EvaluatorBackend | None = None,
    rubric_set: str | None = None,
    max_revision_rounds: int | None = None,
    timeout_s: float | None = None,
    max_completions: int | None = None,
    prompt_specified_shards: Sequence[str] | None = None,
    prompt_id: str = "",
    config: RuntimeConfig | None = None,
    redact: bool | None = None,
) -> DecisionReport:
    """Generate (or take a proposal) and apply frozen condition-D control.

    This productizes the frozen D architecture. Stage 2D did not establish
    that D is superior to C; the frozen evidence class remains
    ``null_retained_D_adds_cost``.
    """
    if not isinstance(prompt, str):
        raise ConstraintExecutionError("run() requires a prompt string")
    if proposal is not None and not isinstance(proposal, str):
        raise ConstraintExecutionError("proposal must be a string when provided")
    cfg = (config or RuntimeConfig()).validate()
    if rubric_set is not None:
        cfg = replace(cfg, rubric_set=rubric_set).validate()
    if max_revision_rounds is not None:
        cfg = replace(cfg, max_revision_rounds=max_revision_rounds).validate()
    if timeout_s is not None:
        cfg = replace(cfg, timeout_s=timeout_s).validate()
    if max_completions is not None:
        cfg = replace(cfg, max_completions=max_completions).validate()
    if redact is not None:
        cfg = replace(cfg, redact=redact)
    specified = _validate_specified(prompt_specified_shards)
    if (
        provider is not None
        and evaluator is not None
        and not isinstance(provider, str)
        and not isinstance(evaluator, str)
        and provider is evaluator
    ):
        raise ConstraintExecutionError(
            "Proposal provider and evaluator must be distinct call-site objects; "
            "a dual-role object cannot cross the provider/evaluator boundary"
        )
    eval_spec = evaluator if evaluator is not None else cfg.evaluator_id
    backend = bind_evaluator(
        eval_spec,
        rubric_set=cfg.rubric_set,
        resolved_as=evaluator_resolved_as(evaluator),
    )
    if provider is None:
        resolution = resolve_proposal(cfg.provider_id, resolved_as=PROPOSAL_RESOLVED_AS_CONFIG)
    elif isinstance(provider, str):
        resolution = resolve_proposal(provider, resolved_as=PROPOSAL_RESOLVED_AS_ARGUMENT)
    else:
        resolution = resolve_proposal(provider, resolved_as=PROPOSAL_RESOLVED_AS_CUSTOM)
    resolved = resolution.backend
    identity = _proposal_identity(resolution)
    supplied_first = proposal is not None
    loop_provider: ProviderBackend = (
        _ProposalFirstProvider(resolved, proposal) if supplied_first else resolved
    )
    recorder = RecordingMiddleware(_middleware(cfg.max_revision_rounds))
    agent = ConstrainedAgent(
        loop_provider,
        evaluator=backend,
        middleware=recorder,
        config=AgentConfig(
            condition="D",
            max_revision_rounds=cfg.max_revision_rounds,
            timeout_s=cfg.timeout_s,
            max_completions=cfg.max_completions,
        ),
    )
    try:
        result = agent.run(prompt, prompt_id=prompt_id, specified_shards=specified)
    except ConstraintExecutionError:
        raise
    except LiveSpendError as exc:
        raise ConstraintExecutionError(f"Live provider refused (fail closed): {exc}") from exc
    except Exception as exc:
        raise ConstraintExecutionError(f"Constrained run failed closed: {exc}") from exc
    report = _report_from_run(
        result=result,
        prompt=prompt,
        evaluator=backend,
        proposal=identity,
        captures=recorder.captures,
        supplied_first=supplied_first,
        prompt_specified_shards=specified,
        prompt_id=prompt_id,
    )
    return _maybe_redact(report, cfg.redact)


SECRET_METADATA_KEYS = SECRET_METADATA_KEYS
