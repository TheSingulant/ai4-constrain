"""Governing success and abort reports (V07-3C).

Abort report: outcome_kind=execution; decision/terminal/arbitration/
shard_evaluations are None for the current governing transaction;
semantic.kind=abort with a closed abort_class.

Success semantic blocks are non-authoritative over decision / terminal /
arbitration. Public redaction strips sensitive infra/provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from src.shards.models import Evaluation
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain._v07_3a.abort import HYBRID_ABORT_CLASSES, HybridExecutionAbort
from ai4.constrain._v07_3b.provenance import ProvenanceEvidenceBundle
from ai4.constrain._v07_3b.report import (
    BLOCK_KIND_ABORT,
    BLOCK_KIND_SUCCESS,
    REPORT_SCHEMA_VERSION_0_2_0,
    VISIBILITY_INTERNAL,
    VISIBILITY_PUBLIC,
    FindingAudit,
    HybridReportDocument,
    SemanticDocument,
    redact_semantic_document,
    serialize_decision_report_document,
)
from ai4.constrain.report import (
    ArbitrationRecord,
    DecisionReport,
    EvaluatorIdentity,
    ProposalIdentity,
    RevisionStep,
    Telemetry,
    VersionInfo,
    arbitration_record,
    shard_records,
)
from ai4.constrain.runtime import (
    ARBITRATION_VERSION,
    CONDITION,
    EVIDENCE_CLASS,
    PROTOCOL_VERSION,
    REPORT_SCHEMA_VERSION,
    RUNTIME_VERSION,
)
from ai4.constrain.semantic_fuse import PackagedFuseResult
from ai4.constrain.semantic_findings import BoundSemanticFindings
from src.constraints.constraint_middleware import ConstraintDecision


@dataclass(frozen=True)
class GoverningDecisionReport(DecisionReport):
    """DecisionReport plus a 0.2.0 semantic document."""

    semantic_block: SemanticDocument | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.semantic_block is None:
            return super().to_dict()
        visibility = VISIBILITY_PUBLIC if self.redacted else VISIBILITY_INTERNAL
        document = HybridReportDocument(
            schema_version=REPORT_SCHEMA_VERSION_0_2_0,
            off_report=replace(self, schema_version=REPORT_SCHEMA_VERSION, semantic_block=None),
            semantic=self.semantic_block,
        )
        payload = serialize_decision_report_document(document)
        payload["semantic"] = self.semantic_block.to_dict(visibility=visibility)
        return payload

    def with_redaction(self) -> GoverningDecisionReport:
        if self.redacted:
            return self
        redacted = super().with_redaction()
        return replace(redacted, semantic_block=self.semantic_block, redacted=True)


def _score_maps(
    det_eval: Evaluation | None,
    fuse_result: PackagedFuseResult | None,
) -> dict[str, dict[str, float]]:
    zeros = {shard_id: 0.0 for shard_id in REQUIRED_IDS}
    if det_eval is None or fuse_result is None:
        return {"deterministic": dict(zeros), "overlay": dict(zeros), "fused": dict(zeros)}
    det = {item.shard_id: float(item.score) for item in det_eval.shard_scores}
    overlay = {shard_id: float(value) for shard_id, value in fuse_result.overlay}
    fused = {shard_id: float(value) for shard_id, value in fuse_result.fused_scores}
    return {
        "deterministic": {shard_id: det[shard_id] for shard_id in REQUIRED_IDS},
        "overlay": {shard_id: overlay[shard_id] for shard_id in REQUIRED_IDS},
        "fused": {shard_id: fused[shard_id] for shard_id in REQUIRED_IDS},
    }


def success_semantic_block(
    *,
    bound: BoundSemanticFindings,
    det_eval: Evaluation,
    fuse_result: PackagedFuseResult,
    provenance: ProvenanceEvidenceBundle,
    observation_prompt_sha256: str,
    registry_sha256: str,
    policy_map_sha256: str,
) -> SemanticDocument:
    findings = tuple(
        FindingAudit(
            finding_id=item.finding.finding_id,
            class_id=item.finding.class_id,
            observation_code=item.finding.observation_code,
        )
        for item in bound.findings
    )
    fingerprints = tuple(item.claim_fingerprint for item in bound.findings)
    return SemanticDocument(
        block_kind=BLOCK_KIND_SUCCESS,
        status="ok",
        observation_prompt_sha256=observation_prompt_sha256,
        registry_sha256=registry_sha256,
        policy_map_sha256=policy_map_sha256,
        score_maps=_score_maps(det_eval, fuse_result),
        findings=findings,
        claim_fingerprints=fingerprints,
        provenance=provenance,
        examiner_id=bound.payload.examiner_id,
        examiner_version=bound.payload.examiner_version,
        provider_id=bound.payload.provider_id,
        model_id=bound.payload.model_id,
    )


def abort_semantic_block(
    *,
    abort_class: str,
    provenance: ProvenanceEvidenceBundle,
    observation_prompt_sha256: str,
    registry_sha256: str,
    policy_map_sha256: str,
    detail: str = "",
    det_eval: Evaluation | None = None,
    fuse_result: PackagedFuseResult | None = None,
    examiner_id: str | None = None,
    examiner_version: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> SemanticDocument:
    if abort_class not in HYBRID_ABORT_CLASSES:
        raise HybridExecutionAbort("schema_invalid", f"unknown abort_class {abort_class!r}")
    return SemanticDocument(
        block_kind=BLOCK_KIND_ABORT,
        abort_class=abort_class,
        detail=detail or abort_class,
        observation_prompt_sha256=observation_prompt_sha256,
        registry_sha256=registry_sha256,
        policy_map_sha256=policy_map_sha256,
        score_maps=_score_maps(det_eval, fuse_result),
        findings=(),
        claim_fingerprints=(),
        provenance=provenance,
        examiner_id=examiner_id,
        examiner_version=examiner_version,
        provider_id=provider_id,
        model_id=model_id,
    )


def _versions(evaluator_id: str, evaluator_version: str, rubric_versions: dict[str, str]) -> VersionInfo:
    return VersionInfo(
        runtime_version=RUNTIME_VERSION,
        report_schema_version=REPORT_SCHEMA_VERSION_0_2_0,
        protocol=PROTOCOL_VERSION,
        condition=CONDITION,
        evidence_class=EVIDENCE_CLASS,
        rubric_set="v0.1",
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
        arbitration=ARBITRATION_VERSION,
        rubric_versions=rubric_versions,
    )


def build_success_report(
    *,
    prompt: str,
    prompt_id: str,
    specified: tuple[str, ...],
    initial_proposal: str,
    final_output: str,
    fused_eval: Evaluation,
    decision: ConstraintDecision,
    product_decision: str,
    terminal: str,
    revision_trace: tuple[RevisionStep, ...],
    telemetry: Telemetry,
    proposal: ProposalIdentity,
    evaluator: EvaluatorIdentity,
    rubric_versions: dict[str, str],
    semantic: SemanticDocument,
    redact: bool,
) -> GoverningDecisionReport:
    report = GoverningDecisionReport(
        schema_version=REPORT_SCHEMA_VERSION_0_2_0,
        mode="constrained_loop",
        outcome_kind="constraint",
        prompt=prompt,
        prompt_id=prompt_id,
        prompt_specified_shards=specified,
        enforced_shards=REQUIRED_IDS,
        shard_control_scope="all_required_v0.1",
        candidate_evaluated=True,
        initial_proposal=initial_proposal,
        shard_evaluations=shard_records(fused_eval, prompt_specified_shards=specified),
        arbitration=arbitration_record(decision.arbitration),
        decision=product_decision,
        terminal=terminal,
        decision_reason=decision.reason,
        revision_trace=revision_trace,
        final_output=final_output,
        telemetry=telemetry,
        proposal=proposal,
        evaluator=evaluator,
        versions=_versions(evaluator.evaluator_id, evaluator.evaluator_version, rubric_versions),
        redacted=False,
        semantic_block=semantic,
    )
    if redact:
        return report.with_redaction()
    return report


def build_abort_report(
    *,
    prompt: str,
    prompt_id: str,
    specified: tuple[str, ...],
    initial_proposal: str,
    telemetry: Telemetry,
    proposal: ProposalIdentity,
    evaluator: EvaluatorIdentity,
    rubric_versions: dict[str, str],
    semantic: SemanticDocument,
    reason: str,
    redact: bool,
    revision_trace: tuple[RevisionStep, ...] = (),
) -> GoverningDecisionReport:
    report = GoverningDecisionReport(
        schema_version=REPORT_SCHEMA_VERSION_0_2_0,
        mode="constrained_loop",
        outcome_kind="execution",
        prompt=prompt,
        prompt_id=prompt_id,
        prompt_specified_shards=specified,
        enforced_shards=REQUIRED_IDS,
        shard_control_scope="all_required_v0.1",
        candidate_evaluated=False,
        initial_proposal=initial_proposal,
        shard_evaluations=None,
        arbitration=None,
        decision=None,
        terminal=None,
        decision_reason=reason,
        revision_trace=revision_trace,
        final_output="",
        telemetry=telemetry,
        proposal=proposal,
        evaluator=evaluator,
        versions=_versions(evaluator.evaluator_id, evaluator.evaluator_version, rubric_versions),
        redacted=False,
        semantic_block=semantic,
    )
    if redact:
        return report.with_redaction()
    return report


def public_semantic_projection(document: SemanticDocument) -> dict[str, Any]:
    return redact_semantic_document(document)


__all__ = [
    "GoverningDecisionReport",
    "abort_semantic_block",
    "build_abort_report",
    "build_success_report",
    "public_semantic_projection",
    "success_semantic_block",
]
