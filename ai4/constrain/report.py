"""Stable DecisionReport document and serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from src.agents.base_agent import TerminalState
from src.protocol_labels import FROZEN_TERMINAL_LABELS, frozen_terminal_label
from src.shards.arbitration import ArbitrationResult
from src.shards.models import Evaluation, ShardScore
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.privacy import redact_text
from ai4.constrain.runtime import REPORT_SCHEMA_VERSION, RUNTIME_VERSION

PRODUCT_DECISIONS = ("accept", "revise", "refuse")
OUTCOME_KINDS = ("constraint", "execution")
REPORT_MODES = ("constrained_loop", "evaluate_only")
FROZEN_TERMINALS = FROZEN_TERMINAL_LABELS

_REQUIRED_REPORT_KEYS = (
    "schema_version",
    "mode",
    "outcome_kind",
    "prompt",
    "initial_proposal",
    "shard_evaluations",
    "arbitration",
    "decision",
    "terminal",
    "decision_reason",
    "revision_trace",
    "final_output",
    "telemetry",
    "versions",
)


def product_decision(state: TerminalState) -> str | None:
    """Constraint decision only. Execution terminals are not refuse."""
    if state is TerminalState.ACCEPT:
        return "accept"
    if state is TerminalState.REVISE:
        return "revise"
    if state is TerminalState.REFUSE:
        return "refuse"
    if state is TerminalState.REPEATED:
        return "revise"
    if state is TerminalState.TIMEOUT:
        return None
    raise ConstraintExecutionError(f"Unknown frozen terminal {state!r}")


def outcome_kind_for(state: TerminalState) -> str:
    if state is TerminalState.TIMEOUT:
        return "execution"
    return "constraint"


def product_decision_from_action(action: str) -> str:
    action = str(action).strip().lower()
    if action in PRODUCT_DECISIONS:
        return action
    if action == "timeout":
        raise ConstraintExecutionError(
            "evaluate() timeout is an execution outcome, not a constraint decision"
        )
    raise ConstraintExecutionError(f"Unknown constraint action {action!r}")


@dataclass(frozen=True)
class CriterionRecord:
    criterion_id: str
    passed: bool
    score: float
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "passed": self.passed,
            "score": self.score,
            "evidence": self.evidence,
        }

    def redacted(self) -> CriterionRecord:
        return replace(self, evidence=redact_text(self.evidence))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CriterionRecord:
        return cls(
            criterion_id=str(raw["criterion_id"]),
            passed=bool(raw["passed"]),
            score=float(raw["score"]),
            evidence=str(raw.get("evidence") or ""),
        )


@dataclass(frozen=True)
class ShardEvaluationRecord:
    shard_id: str
    version: str
    kind: str
    priority: int
    score: float
    passed: bool
    verdict: str
    threshold: float
    reasons: tuple[str, ...] = ()
    criteria: tuple[CriterionRecord, ...] = ()
    applicable: bool = True
    enforced: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "version": self.version,
            "kind": self.kind,
            "priority": self.priority,
            "score": self.score,
            "passed": self.passed,
            "verdict": self.verdict,
            "threshold": self.threshold,
            "applicable": self.applicable,
            "enforced": self.enforced,
            "reasons": list(self.reasons),
            "criteria": [item.to_dict() for item in self.criteria],
        }

    def redacted(self) -> ShardEvaluationRecord:
        return replace(
            self,
            reasons=tuple(redact_text(item) for item in self.reasons),
            criteria=tuple(item.redacted() for item in self.criteria),
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ShardEvaluationRecord:
        criteria = tuple(CriterionRecord.from_dict(item) for item in raw.get("criteria") or ())
        return cls(
            shard_id=str(raw["shard_id"]),
            version=str(raw["version"]),
            kind=str(raw["kind"]),
            priority=int(raw["priority"]),
            score=float(raw["score"]),
            passed=bool(raw["passed"]),
            verdict=str(raw["verdict"]),
            threshold=float(raw["threshold"]),
            reasons=tuple(str(item) for item in raw.get("reasons") or ()),
            criteria=criteria,
            applicable=bool(raw["applicable"]) if "applicable" in raw else True,
            enforced=bool(raw["enforced"]) if "enforced" in raw else True,
        )


@dataclass(frozen=True)
class ArbitrationRecord:
    verdict: str
    veto: bool
    irreconcilable: bool
    revision_targets: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "veto": self.veto,
            "irreconcilable": self.irreconcilable,
            "revision_targets": list(self.revision_targets),
            "notes": list(self.notes),
        }

    def redacted(self) -> ArbitrationRecord:
        return replace(self, notes=tuple(redact_text(item) for item in self.notes))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ArbitrationRecord:
        return cls(
            verdict=str(raw["verdict"]),
            veto=bool(raw["veto"]),
            irreconcilable=bool(raw["irreconcilable"]),
            revision_targets=tuple(str(item) for item in raw.get("revision_targets") or ()),
            notes=tuple(str(item) for item in raw.get("notes") or ()),
        )


@dataclass(frozen=True)
class CallTelemetry:
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    estimated_usd: float
    kind: str = "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "estimated_usd": self.estimated_usd,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CallTelemetry:
        return cls(
            model=str(raw.get("model") or ""),
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
            latency_ms=float(raw.get("latency_ms") or 0.0),
            estimated_usd=float(raw.get("estimated_usd") or 0.0),
            kind=str(raw.get("kind") or "complete"),
        )


@dataclass(frozen=True)
class Telemetry:
    provider: str
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    estimated_usd: float
    per_call: tuple[CallTelemetry, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "estimated_usd": self.estimated_usd,
            "per_call": [item.to_dict() for item in self.per_call],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Telemetry:
        return cls(
            provider=str(raw.get("provider") or ""),
            model=str(raw.get("model") or ""),
            calls=int(raw.get("calls") or 0),
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
            latency_ms=float(raw.get("latency_ms") or 0.0),
            estimated_usd=float(raw.get("estimated_usd") or 0.0),
            per_call=tuple(CallTelemetry.from_dict(item) for item in raw.get("per_call") or ()),
        )


PROPOSAL_IDENTITY_KEYS = ("provider_id", "model", "resolved_as")
PROPOSAL_RESOLVED_AS = (
    "config",
    "explicit_argument",
    "custom_object",
    "evaluate_only",
    "legacy_telemetry",
)


@dataclass(frozen=True)
class ProposalIdentity:
    """Auditable proposal-backend identity. Not governing policy.

    Changing provider or model may change candidate text and the resulting
    decision. It must not change evaluator identity, rubric set, thresholds,
    arbitration, enforced shards, refusal semantics, RuntimeConfig security
    settings, or SessionPolicyIdentity.
    """

    provider_id: str
    model: str = ""
    resolved_as: str = "config"

    def to_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "resolved_as": self.resolved_as,
        }

    @classmethod
    def from_telemetry(cls, telemetry: Telemetry) -> ProposalIdentity:
        """Reconstruct audit identity from schema 0.1.0 telemetry-only reports."""
        return cls(
            provider_id=str(telemetry.provider or "none"),
            model=str(telemetry.model or ""),
            resolved_as="legacy_telemetry",
        )

    @classmethod
    def from_dict(cls, raw: object) -> ProposalIdentity:
        if not isinstance(raw, dict):
            raise ConstraintExecutionError("proposal identity must be a JSON object")
        extra = sorted(str(key) for key in raw if key not in PROPOSAL_IDENTITY_KEYS)
        if extra:
            raise ConstraintExecutionError(
                f"Unknown proposal identity field(s) {extra}; refusing policy smuggling"
            )
        missing = [key for key in PROPOSAL_IDENTITY_KEYS if key not in raw]
        if missing:
            raise ConstraintExecutionError(f"proposal identity missing keys: {missing}")
        provider_id = str(raw["provider_id"] or "").strip()
        if not provider_id:
            raise ConstraintExecutionError("proposal.provider_id must be non-empty")
        resolved_as = str(raw["resolved_as"] or "").strip()
        if resolved_as not in PROPOSAL_RESOLVED_AS:
            raise ConstraintExecutionError(
                f"Unknown proposal.resolved_as {resolved_as!r}. "
                f"Allowed: {PROPOSAL_RESOLVED_AS}"
            )
        return cls(
            provider_id=provider_id,
            model=str(raw.get("model") or ""),
            resolved_as=resolved_as,
        )


EVALUATOR_IDENTITY_KEYS = ("evaluator_id", "evaluator_version", "resolved_as")
EVALUATOR_RESOLVED_AS = (
    "config",
    "explicit_argument",
    "custom_object",
    "legacy_versions",
)


@dataclass(frozen=True)
class EvaluatorIdentity:
    """Auditable evaluator-implementation provenance. Not governing policy.

    Changing the evaluator implementation may change scores and the resulting
    decision. It must not change packaged rubric set, kinds, priorities,
    thresholds, conflicts, pass/fail derivation, arbitration, enforced shards,
    refusal semantics, RuntimeConfig security settings, or evidence class.

    Evaluator implementation interchange does not demonstrate alignment
    persistence or correctness across judges.
    """

    evaluator_id: str
    evaluator_version: str = ""
    resolved_as: str = "config"

    def to_dict(self) -> dict[str, str]:
        return {
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "resolved_as": self.resolved_as,
        }

    @classmethod
    def from_versions(cls, versions: VersionInfo) -> EvaluatorIdentity:
        """Reconstruct provenance from schema 0.1.0 versions-only reports."""
        return cls(
            evaluator_id=str(versions.evaluator_id or ""),
            evaluator_version=str(versions.evaluator_version or ""),
            resolved_as="legacy_versions",
        )

    @classmethod
    def from_dict(cls, raw: object) -> EvaluatorIdentity:
        if not isinstance(raw, dict):
            raise ConstraintExecutionError("evaluator identity must be a JSON object")
        extra = sorted(str(key) for key in raw if key not in EVALUATOR_IDENTITY_KEYS)
        if extra:
            raise ConstraintExecutionError(
                f"Unknown evaluator identity field(s) {extra}; refusing policy smuggling"
            )
        missing = [key for key in EVALUATOR_IDENTITY_KEYS if key not in raw]
        if missing:
            raise ConstraintExecutionError(f"evaluator identity missing keys: {missing}")
        evaluator_id = str(raw["evaluator_id"] or "").strip()
        if not evaluator_id:
            raise ConstraintExecutionError("evaluator.evaluator_id must be non-empty")
        resolved_as = str(raw["resolved_as"] or "").strip()
        if resolved_as not in EVALUATOR_RESOLVED_AS:
            raise ConstraintExecutionError(
                f"Unknown evaluator.resolved_as {resolved_as!r}. "
                f"Allowed: {EVALUATOR_RESOLVED_AS}"
            )
        return cls(
            evaluator_id=evaluator_id,
            evaluator_version=str(raw.get("evaluator_version") or ""),
            resolved_as=resolved_as,
        )


@dataclass(frozen=True)
class VersionInfo:
    runtime_version: str
    report_schema_version: str
    protocol: str
    rubric_set: str
    evaluator_id: str
    evaluator_version: str
    arbitration: str
    condition: str = "D"
    evidence_class: str = "null_retained_D_adds_cost"
    rubric_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_version": self.runtime_version,
            "report_schema_version": self.report_schema_version,
            "protocol": self.protocol,
            "condition": self.condition,
            "evidence_class": self.evidence_class,
            "rubric_set": self.rubric_set,
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
            "arbitration": self.arbitration,
            "rubric_versions": dict(self.rubric_versions),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VersionInfo:
        versions = raw.get("rubric_versions") or {}
        if not isinstance(versions, dict):
            raise ConstraintExecutionError("versions.rubric_versions must be an object")
        smuggled = [
            key
            for key in ("provider", "provider_id", "model", "resolved_as", "evaluator")
            if key in raw
        ]
        if smuggled:
            raise ConstraintExecutionError(
                f"versions must not include proposal identity field(s) {smuggled}; "
                "provider/model are not governing policy, and evaluator provenance "
                "belongs on the evaluator block"
            )
        return cls(
            runtime_version=str(raw.get("runtime_version") or RUNTIME_VERSION),
            report_schema_version=str(raw.get("report_schema_version") or REPORT_SCHEMA_VERSION),
            protocol=str(raw.get("protocol") or ""),
            condition=str(raw.get("condition") or "D"),
            evidence_class=str(raw.get("evidence_class") or "null_retained_D_adds_cost"),
            rubric_set=str(raw.get("rubric_set") or ""),
            evaluator_id=str(raw.get("evaluator_id") or ""),
            evaluator_version=str(raw.get("evaluator_version") or ""),
            arbitration=str(raw.get("arbitration") or ""),
            rubric_versions={str(key): str(value) for key, value in versions.items()},
        )


@dataclass(frozen=True)
class RevisionStep:
    round: int
    input_text: str
    output_text: str
    shard_evaluations: tuple[ShardEvaluationRecord, ...]
    arbitration: ArbitrationRecord
    action: str
    reason: str
    feedback: str
    telemetry: CallTelemetry
    captured: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "shard_evaluations": [item.to_dict() for item in self.shard_evaluations],
            "arbitration": self.arbitration.to_dict(),
            "action": self.action,
            "reason": self.reason,
            "feedback": self.feedback,
            "telemetry": self.telemetry.to_dict(),
            "captured": self.captured,
        }

    def redacted(self) -> RevisionStep:
        return replace(
            self,
            input_text=redact_text(self.input_text),
            output_text=redact_text(self.output_text),
            shard_evaluations=tuple(item.redacted() for item in self.shard_evaluations),
            arbitration=self.arbitration.redacted(),
            reason=redact_text(self.reason),
            feedback=redact_text(self.feedback),
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RevisionStep:
        return cls(
            round=int(raw["round"]),
            input_text=str(raw.get("input_text") or ""),
            output_text=str(raw.get("output_text") or ""),
            shard_evaluations=tuple(
                ShardEvaluationRecord.from_dict(item) for item in raw.get("shard_evaluations") or ()
            ),
            arbitration=ArbitrationRecord.from_dict(raw["arbitration"]),
            action=str(raw.get("action") or ""),
            reason=str(raw.get("reason") or ""),
            feedback=str(raw.get("feedback") or ""),
            telemetry=CallTelemetry.from_dict(raw.get("telemetry") or {}),
            captured=bool(raw["captured"]) if "captured" in raw else True,
        )


@dataclass(frozen=True)
class DecisionReport:
    """Stable structured result of ``ai4.constrain.run`` / ``evaluate``."""

    schema_version: str
    mode: str
    outcome_kind: str
    prompt: str
    initial_proposal: str
    shard_evaluations: tuple[ShardEvaluationRecord, ...] | None
    arbitration: ArbitrationRecord | None
    decision: str | None
    terminal: str | None
    decision_reason: str
    revision_trace: tuple[RevisionStep, ...]
    final_output: str
    telemetry: Telemetry
    versions: VersionInfo
    prompt_id: str = ""
    prompt_specified_shards: tuple[str, ...] = ()
    enforced_shards: tuple[str, ...] = REQUIRED_IDS
    shard_control_scope: str = "all_required_v0.1"
    candidate_evaluated: bool = True
    redacted: bool = True
    proposal: ProposalIdentity | None = None
    evaluator: EvaluatorIdentity | None = None

    def proposal_identity(self) -> ProposalIdentity:
        """Auditable proposal identity; reconstructed from telemetry on old reports."""
        if self.proposal is not None:
            return self.proposal
        return ProposalIdentity.from_telemetry(self.telemetry)

    def evaluator_identity(self) -> EvaluatorIdentity:
        """Auditable evaluator provenance; reconstructed from versions on old reports."""
        if self.evaluator is not None:
            return self.evaluator
        return EvaluatorIdentity.from_versions(self.versions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "outcome_kind": self.outcome_kind,
            "prompt": self.prompt,
            "prompt_id": self.prompt_id,
            "prompt_specified_shards": list(self.prompt_specified_shards),
            "enforced_shards": list(self.enforced_shards),
            "shard_control_scope": self.shard_control_scope,
            "candidate_evaluated": self.candidate_evaluated,
            "initial_proposal": self.initial_proposal,
            "shard_evaluations": (
                None if self.shard_evaluations is None else [item.to_dict() for item in self.shard_evaluations]
            ),
            "arbitration": None if self.arbitration is None else self.arbitration.to_dict(),
            "decision": self.decision,
            "terminal": self.terminal,
            "decision_reason": self.decision_reason,
            "revision_trace": [item.to_dict() for item in self.revision_trace],
            "final_output": self.final_output,
            "telemetry": self.telemetry.to_dict(),
            "proposal": self.proposal_identity().to_dict(),
            "evaluator": self.evaluator_identity().to_dict(),
            "versions": self.versions.to_dict(),
            "redacted": self.redacted,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def with_redaction(self) -> DecisionReport:
        if self.redacted:
            return self
        return replace(
            self,
            prompt=redact_text(self.prompt),
            initial_proposal=redact_text(self.initial_proposal),
            shard_evaluations=(
                None
                if self.shard_evaluations is None
                else tuple(item.redacted() for item in self.shard_evaluations)
            ),
            arbitration=None if self.arbitration is None else self.arbitration.redacted(),
            decision_reason=redact_text(self.decision_reason),
            revision_trace=tuple(item.redacted() for item in self.revision_trace),
            final_output=redact_text(self.final_output),
            proposal=self.proposal,
            evaluator=self.evaluator,
            redacted=True,
        )

    @classmethod
    def from_dict(cls, raw: object) -> DecisionReport:
        if not isinstance(raw, dict):
            raise ConstraintExecutionError("DecisionReport must be a JSON object")
        missing = [key for key in _REQUIRED_REPORT_KEYS if key not in raw]
        if missing:
            raise ConstraintExecutionError(f"DecisionReport missing keys: {missing}")
        if raw.get("schema_version") != REPORT_SCHEMA_VERSION:
            raise ConstraintExecutionError(
                f"Unsupported DecisionReport schema_version {raw.get('schema_version')!r}"
            )
        mode = str(raw["mode"])
        if mode not in REPORT_MODES:
            raise ConstraintExecutionError(f"Unknown DecisionReport mode {mode!r}")
        outcome_kind = str(raw["outcome_kind"])
        if outcome_kind not in OUTCOME_KINDS:
            raise ConstraintExecutionError(f"Unknown DecisionReport outcome_kind {outcome_kind!r}")
        decision = raw.get("decision")
        if decision is not None:
            decision = str(decision)
            if decision not in PRODUCT_DECISIONS:
                raise ConstraintExecutionError(f"Unknown DecisionReport decision {decision!r}")
        terminal = raw.get("terminal")
        if terminal is not None:
            terminal = str(terminal)
            if terminal not in FROZEN_TERMINALS:
                raise ConstraintExecutionError(f"Unknown frozen terminal {terminal!r}")
        shards_raw = raw["shard_evaluations"]
        arbitration_raw = raw["arbitration"]
        if shards_raw is None:
            shard_evaluations = None
        elif isinstance(shards_raw, list):
            shard_evaluations = tuple(ShardEvaluationRecord.from_dict(item) for item in shards_raw)
        else:
            raise ConstraintExecutionError("shard_evaluations must be an array or null")
        if arbitration_raw is None:
            arbitration = None
        elif isinstance(arbitration_raw, dict):
            arbitration = ArbitrationRecord.from_dict(arbitration_raw)
        else:
            raise ConstraintExecutionError("arbitration must be an object or null")
        specified = raw.get("prompt_specified_shards", raw.get("specified_shards") or ())
        telemetry = Telemetry.from_dict(raw["telemetry"])
        proposal_raw = raw.get("proposal")
        if proposal_raw is None:
            proposal = ProposalIdentity.from_telemetry(telemetry)
        else:
            proposal = ProposalIdentity.from_dict(proposal_raw)
        versions = VersionInfo.from_dict(raw["versions"])
        evaluator_raw = raw.get("evaluator")
        if evaluator_raw is None:
            evaluator = EvaluatorIdentity.from_versions(versions)
        else:
            evaluator = EvaluatorIdentity.from_dict(evaluator_raw)
            if evaluator.evaluator_id != versions.evaluator_id:
                raise ConstraintExecutionError(
                    f"evaluator.evaluator_id {evaluator.evaluator_id!r} disagrees with "
                    f"versions.evaluator_id {versions.evaluator_id!r}; refusing inconsistent "
                    "evaluator provenance"
                )
            if evaluator.evaluator_version != versions.evaluator_version:
                raise ConstraintExecutionError(
                    f"evaluator.evaluator_version {evaluator.evaluator_version!r} disagrees "
                    f"with versions.evaluator_version {versions.evaluator_version!r}; "
                    "refusing inconsistent evaluator provenance"
                )
        try:
            return cls(
                schema_version=str(raw["schema_version"]),
                mode=mode,
                outcome_kind=outcome_kind,
                prompt=str(raw.get("prompt") or ""),
                prompt_id=str(raw.get("prompt_id") or ""),
                prompt_specified_shards=tuple(str(item) for item in specified or ()),
                enforced_shards=tuple(str(item) for item in raw.get("enforced_shards") or REQUIRED_IDS),
                shard_control_scope=str(raw.get("shard_control_scope") or "all_required_v0.1"),
                candidate_evaluated=(
                    bool(raw["candidate_evaluated"])
                    if "candidate_evaluated" in raw
                    else shards_raw is not None
                ),
                initial_proposal=str(raw.get("initial_proposal") or ""),
                shard_evaluations=shard_evaluations,
                arbitration=arbitration,
                decision=decision,
                terminal=terminal,
                decision_reason=str(raw.get("decision_reason") or ""),
                revision_trace=tuple(RevisionStep.from_dict(item) for item in raw["revision_trace"]),
                final_output=str(raw.get("final_output") or ""),
                telemetry=telemetry,
                proposal=proposal,
                evaluator=evaluator,
                versions=versions,
                redacted=bool(raw["redacted"]) if "redacted" in raw else True,
            )
        except ConstraintExecutionError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ConstraintExecutionError(f"Malformed DecisionReport: {exc}") from exc

    @classmethod
    def from_json(cls, raw: str | bytes) -> DecisionReport:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConstraintExecutionError(f"Malformed DecisionReport JSON: {exc}") from exc
        return cls.from_dict(payload)


def shard_record(
    score: ShardScore,
    *,
    prompt_specified_shards: tuple[str, ...] = (),
) -> ShardEvaluationRecord:
    apply_filter = bool(prompt_specified_shards)
    applicable = (not apply_filter) or (score.shard_id in prompt_specified_shards)
    if applicable:
        verdict = "pass" if score.passed else "fail"
    else:
        verdict = "not_applicable"
    return ShardEvaluationRecord(
        shard_id=score.shard_id,
        version=score.version,
        kind=score.kind,
        priority=score.priority,
        score=float(score.score),
        passed=bool(score.passed),
        verdict=verdict,
        threshold=float(score.threshold),
        reasons=tuple(score.notes),
        criteria=tuple(
            CriterionRecord(
                criterion_id=item.criterion_id,
                passed=item.passed,
                score=float(item.score),
                evidence=item.evidence,
            )
            for item in score.results
        ),
        applicable=applicable,
        enforced=True,
    )


def shard_records(
    evaluation: Evaluation,
    *,
    prompt_specified_shards: tuple[str, ...] = (),
) -> tuple[ShardEvaluationRecord, ...]:
    by_id = evaluation.by_id()
    ordered = []
    seen: set[str] = set()
    for shard_id in REQUIRED_IDS:
        score = by_id.get(shard_id)
        if score is None:
            continue
        ordered.append(shard_record(score, prompt_specified_shards=prompt_specified_shards))
        seen.add(shard_id)
    for score in evaluation.shard_scores:
        if score.shard_id not in seen:
            ordered.append(shard_record(score, prompt_specified_shards=prompt_specified_shards))
    return tuple(ordered)


def arbitration_record(result: ArbitrationResult) -> ArbitrationRecord:
    return ArbitrationRecord(
        verdict=result.verdict,
        veto=bool(result.veto),
        irreconcilable=bool(result.irreconcilable),
        revision_targets=tuple(result.revision_targets),
        notes=tuple(result.notes),
    )


def loop_terminal(state: TerminalState, reason: str) -> str:
    label = frozen_terminal_label(state, reason)
    if label not in FROZEN_TERMINALS:
        raise ConstraintExecutionError(f"Unknown frozen terminal {label!r}")
    return label
