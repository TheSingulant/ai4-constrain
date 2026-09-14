"""V07-3C governing hybrid integration.

Synthetic fixtures only. No frozen Beta prompts. No live/paid providers.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

import ai4.constrain as public
from ai4.constrain import evaluate, run
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.budget import RunBudgetAuthority
from ai4.constrain._v07_3a.context import ContinuitySnapshot, NotReady, TrustedProductConfig, bind_roles
from ai4.constrain._v07_3b.context import HybridConfiguration, HybridContext, HybridContextBuilder
from ai4.constrain._v07_3b.provenance import bundle_claims, collect_configured
from ai4.constrain._v07_3b.snapshot import detect_identity_drift
from ai4.constrain._v07_3b.separation import assess_operational_separation
from ai4.constrain._v07_3b.snapshot import ArtifactContinuitySnapshot
from ai4.constrain._v07_3c.install import HybridOrchestrator
from ai4.constrain._v07_3c.persist import FailingContinuityStore, FileContinuityStore
from ai4.constrain._v07_3c.ready import (
    GATE_CONTINUITY_COMPATIBLE,
    GATE_DEADLINE_VALID,
    GATE_EXAMINER_BUDGET,
    GATE_FUSE_ID_MATCH,
    GATE_HARD_DISQUALIFIER,
    GATE_LOCKED_OBSERVATION_PROMPT_HASH,
    GATE_LOCKED_POLICY_MAP_HASH,
    GATE_LOCKED_REGISTRY_HASH,
    GATE_OPERATIONAL_SEPARATION,
    GATE_PROPOSAL_BUDGET,
    GATE_ROLE_BINDINGS,
    GATE_RUNTIME_PROVENANCE,
    GATE_SEMANTIC_CONFIG_VERSION,
    GATE_SEMANTIC_SCHEMA_VERSION,
    GATE_SHARED_BUDGET,
    Ready,
    compute_ready_facts,
    hybrid_ready,
)
from ai4.constrain.cli import EXIT_TIMEOUT, report_exit_code
from ai4.constrain.governing import GOVERNING_INTEGRATION_VERSION, GoverningIntegration
from ai4.constrain.runtime import RuntimeConfig
from ai4.constrain.semantic_examiner import (
    EXAMINER_PIN_KIND,
    EXAMINER_PIN_KIND_CALLER_CONFIG,
    ExaminerBackendResult,
    ExaminerObservationRequest,
    observation_prompt_sha256,
)
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION, SEMANTIC_EXAMINER_OPERATIONAL, quote_sha256_for_span
from ai4.constrain.semantic_fuse import LOCKED_POLICY_MAP_SHA256, LOCKED_REGISTRY_SHA256, PACKAGED_FUSE_ID
from ai4.constrain.semantic_taxonomy import finding_policy_map_sha256, finding_registry_sha256
from ai4.constrain._v07_3c.loop import run_governing_loop
from ai4.constrain._v07_3c.observe import (
    mint_runtime_provenance,
    observation_from_bundle,
    role_observation_identity,
)
from ai4.constrain.evaluator_wall import packaged_policy_rubrics
from ai4.constrain.ext import bind_evaluator
from src.constraints.constraint_middleware import ConstraintMiddleware
from src.providers.base import Completion

PROMPT_SHA256 = "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"
REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"

CLEAN = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."
DIRTY = (
    "Here is a brief, checkable answer. See Smith et al. 2099. "
    "I will mark anything I cannot verify."
)
PROPOSER_ORIGIN = "https://proposer.test"
EXAMINER_ORIGIN = "https://examiner.test"


class ObservableProvider:
    name = "observable-proposer"
    observed_peer_origin = PROPOSER_ORIGIN
    observed_account_id = "acct-proposer"
    observed_session_token = "sess-proposer"
    observed_served_model = "synthetic-proposer-model"

    def __init__(self, texts: list[str] | None = None) -> None:
        self._texts = list(texts or [CLEAN])
        self.complete_calls = 0
        self.revise_calls = 0
        self.feedbacks: list[str] = []

    def complete(self, *, system: str, user: str) -> Completion:
        self.complete_calls += 1
        text = self._texts.pop(0) if self._texts else CLEAN
        return Completion(text=text, model=self.observed_served_model, estimated_usd=0.0)

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        self.revise_calls += 1
        self.feedbacks.append(feedback)
        text = self._texts.pop(0) if self._texts else CLEAN
        return Completion(text=text, model=self.observed_served_model, estimated_usd=0.0)


@dataclass
class ObservableExaminer:
    observed_peer_origin: str = EXAMINER_ORIGIN
    observed_account_id: str = "acct-examiner"
    observed_session_token: str = "sess-examiner"
    observed_served_model: str = "synthetic-examiner-model"
    last_estimated_usd: float = 0.0
    findings_queue: list = field(default_factory=list)
    status_queue: list = field(default_factory=list)
    requests: list = field(default_factory=list)

    def observe(self, request: ExaminerObservationRequest) -> ExaminerBackendResult:
        self.requests.append(request)
        status = self.status_queue.pop(0) if self.status_queue else "ok"
        findings = self.findings_queue.pop(0) if self.findings_queue else []
        if callable(findings):
            findings = findings(request)
        document = {
            "schema_version": request.schema_version,
            "examiner_id": request.examiner_id,
            "examiner_version": request.examiner_version,
            "model_id": request.model_id,
            "provider_id": request.provider_id,
            "observation_prompt_sha256": request.observation_prompt_sha256,
            "temperature": 0,
            "status": status,
            "findings": findings if status == "ok" else [],
        }
        return ExaminerBackendResult(status=status, payload_text=json.dumps(document))


def _citation_finding(request: ExaminerObservationRequest) -> list[dict[str, object]]:
    start = request.candidate.find("Smith")
    end = start + len("Smith et al. 2099")
    return [
        {
            "finding_id": "f-1",
            "class_id": "fabricated_authority",
            "confidence_bin": "high",
            "span": {"start": start, "end": end},
            "quote_sha256": quote_sha256_for_span(request.candidate, start, end),
            "observation_code": "invented_citation_cue",
            "injection_signal_codes": [],
        }
    ]


def _ungrounded_finding(request: ExaminerObservationRequest) -> list[dict[str, object]]:
    start = 0
    end = min(8, len(request.candidate))
    return [
        {
            "finding_id": "f-missing-template",
            "class_id": "fabricated_authority",
            "confidence_bin": "low",
            "span": {"start": start, "end": end},
            "quote_sha256": quote_sha256_for_span(request.candidate, start, end),
            "observation_code": "invented_credential_cue",
            "injection_signal_codes": [],
        }
    ]


def _integration(tmp_path: Path, examiner: object, **overrides: object) -> GoverningIntegration:
    values: dict[str, object] = {
        "proposer_provider_id": "synthetic-proposer",
        "proposer_model_id": "synthetic-proposer-model",
        "examiner_provider_id": "synthetic-examiner",
        "examiner_model_id": "synthetic-examiner-model",
        "examiner_id": "synthetic-examiner-id",
        "examiner_version": "0.7.3c-test",
        "origin_allowlist": (PROPOSER_ORIGIN, EXAMINER_ORIGIN),
        "proposer_requested_origin": PROPOSER_ORIGIN,
        "examiner_requested_origin": EXAMINER_ORIGIN,
        "max_usd": 1.0,
        "max_proposal_completions": 3,
        "max_examiner_calls": 3,
        "session_id": "v07-3c-session",
        "session_dir": str(tmp_path),
        "examiner_backend": examiner,
        "proposer_credential": "cred-p",
        "examiner_credential": "cred-e",
    }
    values.update(overrides)
    return GoverningIntegration(**values)  # type: ignore[arg-type]


def _run(tmp_path: Path, *, provider=None, examiner=None, **overrides):
    examiner = examiner or ObservableExaminer()
    provider = provider or ObservableProvider()
    cfg = RuntimeConfig(
        integration=_integration(tmp_path, examiner, **overrides),
        redact=False,
        max_revision_rounds=2,
    )
    return run(CLEAN_RUN, provider=provider, config=cfg), provider, examiner


def _trusted(**overrides: object) -> TrustedProductConfig:
    values = {
        "proposer_provider_id": "synthetic-proposer",
        "proposer_model_id": "synthetic-proposer-model",
        "examiner_provider_id": "synthetic-examiner",
        "examiner_model_id": "synthetic-examiner-model",
        "examiner_id": "synthetic-examiner-id",
        "examiner_version": "0.7.3c-test",
        "observation_prompt_sha256": PROMPT_SHA256,
    }
    values.update(overrides)
    return TrustedProductConfig(**values)  # type: ignore[arg-type]


def _config(tmp_deadline: float | None = None, **overrides: object) -> HybridConfiguration:
    values: dict[str, object] = {
        "trusted": _trusted(),
        "origin_allowlist": (PROPOSER_ORIGIN, EXAMINER_ORIGIN),
        "proposer_requested_origin": PROPOSER_ORIGIN,
        "examiner_requested_origin": EXAMINER_ORIGIN,
        "max_usd": 1.0,
        "deadline_monotonic": tmp_deadline if tmp_deadline is not None else time.monotonic() + 30.0,
        "max_proposal_completions": 2,
        "max_examiner_calls": 2,
        "semantic_config_version": "v07.3c.0",
    }
    values.update(overrides)
    return HybridConfiguration(**values)  # type: ignore[arg-type]


def _ready_context(**overrides: object) -> HybridContext:
    proposer = overrides.pop("proposer", None) or ObservableProvider()
    examiner = overrides.pop("examiner", None) or ObservableExaminer()
    from ai4.constrain._v07_3c.observe import bind_role_scoped_identities, mint_runtime_provenance

    config = overrides.pop("configuration", None) or _config()
    authority = overrides.pop("budget_authority", None)
    if authority is None:
        authority = RunBudgetAuthority(
            deadline_monotonic=float(config.deadline_monotonic),
            max_proposal_completions=int(config.max_proposal_completions),
            max_examiner_calls=int(config.max_examiner_calls),
            max_usd=float(config.max_usd),
        )
    continuity = overrides.pop("continuity", None) or ContinuitySnapshot(
        ever_on=False,
        ever_required=False,
        persisted_report_schema_0_2_0=False,
        persisted_semantic=False,
    )
    proposer_bundle, examiner_bundle, p_t, e_t, p_obs, e_obs = mint_runtime_provenance(
        configured_label="synthetic-proposer/synthetic-proposer-model",
        examiner_configured_label="synthetic-examiner/synthetic-examiner-model",
        proposer=proposer,
        examiner=examiner,
        proposer_requested_origin=PROPOSER_ORIGIN,
        examiner_requested_origin=EXAMINER_ORIGIN,
        origin_allowlist=(PROPOSER_ORIGIN, EXAMINER_ORIGIN),
    )
    context = bind_role_scoped_identities(
        HybridContextBuilder(config)
        .with_runtime_provenance(proposer_bundle)
        .with_examiner_runtime_provenance(examiner_bundle)
        .with_continuity(continuity)
        .with_budget_authority(authority)
        .with_transport(proposer=p_t, examiner=e_t)
        .with_accounts(proposer=p_obs["account_id"], examiner=e_obs["account_id"])
        .with_credentials(proposer="cred-p", examiner="cred-e")
        .with_session_objects(proposer=proposer, examiner=examiner)
        .build()
    )
    if overrides:
        context = replace(context, **overrides)
    return context


def test_ready_success_and_honest_non_claims():
    context = _ready_context()
    result = hybrid_ready(context)
    assert isinstance(result, Ready)
    assert result.facts.all_gates_passed
    assert result.facts.independence is False
    assert result.facts.attested is False
    assert result.facts.authenticated is False
    assert result.facts.cryptographic_model_proof is False
    with pytest.raises(HybridExecutionAbort, match="conclusion only"):
        result.install()


@pytest.mark.parametrize(
    "mutator,gate",
    [
        (
            lambda ctx: replace(
                ctx,
                identity_snapshot=replace(ctx.identity_snapshot, observation_prompt_sha256="ab" * 32),
            ),
            GATE_LOCKED_OBSERVATION_PROMPT_HASH,
        ),
        (
            lambda ctx: replace(
                ctx,
                identity_snapshot=replace(ctx.identity_snapshot, registry_sha256="cd" * 32),
            ),
            GATE_LOCKED_REGISTRY_HASH,
        ),
        (
            lambda ctx: replace(
                ctx,
                identity_snapshot=replace(ctx.identity_snapshot, policy_map_sha256="ef" * 32),
            ),
            GATE_LOCKED_POLICY_MAP_HASH,
        ),
        (
            lambda ctx: replace(
                ctx,
                identity_snapshot=replace(ctx.identity_snapshot, fuse_id="not-packaged"),
            ),
            GATE_FUSE_ID_MATCH,
        ),
        (
            lambda ctx: replace(
                ctx,
                identity_snapshot=replace(ctx.identity_snapshot, semantic_schema_version="nope"),
            ),
            GATE_SEMANTIC_SCHEMA_VERSION,
        ),
        (
            lambda ctx: replace(
                ctx,
                identity_snapshot=replace(ctx.identity_snapshot, semantic_config_version="v07.3b.0"),
            ),
            GATE_SEMANTIC_CONFIG_VERSION,
        ),
        (lambda ctx: replace(ctx, role_bindings=()), GATE_ROLE_BINDINGS),
        (lambda ctx: replace(ctx, budget_authority=None), GATE_SHARED_BUDGET),
    ],
)
def test_ready_failure_locked_identity_and_budget_gates(mutator, gate):
    context = mutator(_ready_context())
    result = hybrid_ready(context)
    assert isinstance(result, NotReady)
    assert result.reason == gate
    facts = compute_ready_facts(context)
    assert gate in facts.failed_gates


def test_ready_failure_runtime_provenance_and_separation_and_deadline():
    bare = HybridContextBuilder(_config()).build()
    result = hybrid_ready(bare)
    assert isinstance(result, NotReady)
    assert result.reason == GATE_RUNTIME_PROVENANCE

    same = _ready_context()
    same_roles = bind_roles(
        _trusted(examiner_provider_id="synthetic-proposer", examiner_model_id="synthetic-proposer-model")
    )
    hard = replace(same, role_bindings=same_roles, separation=assess_operational_separation(
        proposer=same_roles[0], examiner=same_roles[1]
    ))
    hard_result = hybrid_ready(hard)
    assert isinstance(hard_result, NotReady)
    assert hard_result.reason in {GATE_OPERATIONAL_SEPARATION, GATE_HARD_DISQUALIFIER}

    expired = _ready_context(
        budget_authority=RunBudgetAuthority(
            deadline_monotonic=time.monotonic() - 1,
            max_proposal_completions=2,
            max_examiner_calls=2,
            max_usd=1.0,
        )
    )
    expired_result = hybrid_ready(expired)
    assert isinstance(expired_result, NotReady)
    assert expired_result.reason == GATE_DEADLINE_VALID

    zero_exam = _ready_context(
        budget_authority=RunBudgetAuthority(
            deadline_monotonic=time.monotonic() + 30,
            max_proposal_completions=2,
            max_examiner_calls=0,
            max_usd=1.0,
        )
    )
    assert hybrid_ready(zero_exam).reason == GATE_EXAMINER_BUDGET
    zero_prop = _ready_context(
        budget_authority=RunBudgetAuthority(
            deadline_monotonic=time.monotonic() + 30,
            max_proposal_completions=0,
            max_examiner_calls=2,
            max_usd=1.0,
        )
    )
    assert hybrid_ready(zero_prop).reason == GATE_PROPOSAL_BUDGET

    unrepaired = _ready_context(
        continuity=ContinuitySnapshot(
            ever_on=False,
            ever_required=True,
            persisted_report_schema_0_2_0=False,
            persisted_semantic=False,
        )
    )
    assert hybrid_ready(unrepaired).reason == GATE_CONTINUITY_COMPATIBLE


def test_install_persists_ever_on_before_first_provider_call(tmp_path: Path):
    provider = ObservableProvider()
    saves_before_call: list[int] = []

    class ProbeStore(FileContinuityStore):
        def save(self, session_id: str, payload: dict) -> None:
            saves_before_call.append(provider.complete_calls)
            assert payload["ever_on"] is True
            super().save(session_id, payload)

    examiner = ObservableExaminer()
    report, provider, _ = _run(
        tmp_path,
        provider=provider,
        examiner=examiner,
        persist_store=ProbeStore(tmp_path),
    )
    assert report.decision == "accept"
    assert saves_before_call
    assert saves_before_call[0] == 0
    assert provider.complete_calls >= 1


def test_restore_truth_table(tmp_path: Path):
    class BlindProvider:
        name = "blind"
        def complete(self, *, system, user):
            return Completion(text=CLEAN, model="mock", estimated_usd=0.0)
        def revise(self, *, system, user, draft, feedback):
            return Completion(text=CLEAN, model="mock", estimated_usd=0.0)

    # never entered + NotReady → OFF permitted
    report = run(
        CLEAN_RUN,
        provider=BlindProvider(),
        config=RuntimeConfig(
            integration=_integration(tmp_path, ObservableExaminer(), session_id="never-entered"),
            redact=False,
        ),
    )
    assert report.schema_version == "0.1.0"
    assert "semantic" not in report.to_dict()
    assert report.decision == "accept"

    # first hybrid success latches continuity
    first, _, _ = _run(tmp_path, session_id="latched")
    assert first.schema_version == "0.2.0"
    assert first.decision == "accept"

    # continuity required + NotReady → abort, never OFF
    abort = run(
        CLEAN_RUN,
        provider=BlindProvider(),
        config=RuntimeConfig(
            integration=_integration(tmp_path, ObservableExaminer(), session_id="latched"),
            redact=False,
        ),
    )
    assert abort.outcome_kind == "execution"
    assert abort.decision is None
    assert abort.terminal is None
    assert abort.arbitration is None
    assert abort.shard_evaluations is None
    assert abort.to_dict()["semantic"]["block_kind"] == "abort"
    assert abort.to_dict()["semantic"]["abort_class"] == "continuity_required_not_ready"

    # continuity required + Ready + identity match → hybrid
    second, _, _ = _run(tmp_path, session_id="latched")
    assert second.schema_version == "0.2.0"
    assert second.decision == "accept"

    # continuity required + identity drift
    drifted = run(
        CLEAN_RUN,
        provider=ObservableProvider(),
        config=RuntimeConfig(
            integration=_integration(
                tmp_path,
                ObservableExaminer(),
                session_id="latched",
                examiner_id="drifted-examiner",
            ),
            redact=False,
        ),
    )
    assert drifted.outcome_kind == "execution"
    assert drifted.to_dict()["semantic"]["abort_class"] == "identity_drift"


def test_runtime_provenance_is_not_minted_from_config():
    context = HybridContextBuilder(_config()).build()
    facts = compute_ready_facts(context)
    assert facts.runtime_observed_provenance is False
    assert "transport_bound" not in facts.observed_claim_names
    assert hybrid_ready(context).reason == GATE_RUNTIME_PROVENANCE


def test_empty_ok_and_fusion_success(tmp_path: Path):
    report, _, examiner = _run(tmp_path, examiner=ObservableExaminer(findings_queue=[[]]))
    payload = report.to_dict()
    assert report.decision == "accept"
    assert payload["semantic"]["status"] == "ok"
    assert payload["semantic"]["findings_count"] == 0
    assert payload["semantic"]["score_maps"]["fused"]["truth"] == payload["semantic"]["score_maps"]["deterministic"]["truth"]
    assert examiner.requests[0].candidate == report.initial_proposal


def test_fusion_triggered_revise_and_second_round_success(tmp_path: Path):
    provider = ObservableProvider([DIRTY, CLEAN])
    examiner = ObservableExaminer(findings_queue=[_citation_finding, []])
    report, provider, examiner = _run(tmp_path, provider=provider, examiner=examiner)
    assert provider.revise_calls == 1
    assert report.decision == "accept"
    assert len(report.revision_trace) == 1
    assert "Hybrid revision guidance" in provider.feedbacks[0]
    assert "FAIL" not in provider.feedbacks[0]
    assert report.to_dict()["semantic"]["findings_count"] == 0
    assert len(examiner.requests) == 2
    assert examiner.requests[0].candidate != examiner.requests[1].candidate


def test_revision_exhaustion(tmp_path: Path):
    provider = ObservableProvider([DIRTY, DIRTY + " ", DIRTY + "  "])
    examiner = ObservableExaminer(findings_queue=[_citation_finding, _citation_finding, _citation_finding])
    report, provider, _ = _run(tmp_path, provider=provider, examiner=examiner)
    assert report.decision in {"revise", "refuse"}
    assert report.terminal in {"revision_exhausted", "refused"}
    assert provider.revise_calls >= 1


def test_feedback_replacement_not_concatenation(tmp_path: Path):
    provider = ObservableProvider([DIRTY, CLEAN])
    examiner = ObservableExaminer(findings_queue=[_citation_finding, []])
    _, provider, _ = _run(tmp_path, provider=provider, examiner=examiner)
    text = provider.feedbacks[0]
    assert text.startswith("Hybrid revision guidance (template-only):")
    assert "invented_citation_cue" not in text
    assert DIRTY not in text
    assert "Smith" not in text


def test_missing_feedback_template_fail_closed(tmp_path: Path):
    # Use a finding whose class/code pair is valid in the registry but we
    # force revise via DIRTY+overlay; invented_credential_cue has a template.
    # Missing-template path: observation_code with no template is rejected by
    # 3B lookup. Use a registry-valid pair we delete from the live lookup by
    # choosing overclaim_from_ambiguity / ambiguity_as_fact_cue which HAS a
    # template. Instead, trigger revise with empty-ok on a det-failing draft.
    provider = ObservableProvider(
        ["As a proven fact, studies conclusively prove that exactly 73.2% agree."]
    )
    examiner = ObservableExaminer(findings_queue=[[]])
    report, _, _ = _run(tmp_path, provider=provider, examiner=examiner)
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] == "schema_invalid"


def test_non_ok_semantic_aborts(tmp_path: Path):
    examiner = ObservableExaminer(status_queue=["timeout"])
    report, _, _ = _run(tmp_path, examiner=examiner)
    assert report.outcome_kind == "execution"
    assert report.decision is None
    assert report.to_dict()["semantic"]["abort_class"] == "wall_deadline_exhausted"


def test_proposal_failure_aborts(tmp_path: Path):
    class Boom(ObservableProvider):
        def complete(self, *, system: str, user: str) -> Completion:
            self.complete_calls += 1
            raise RuntimeError("synthetic proposal failure")

    report, provider, _ = _run(tmp_path, provider=Boom())
    assert provider.complete_calls == 1
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] == "backend_error"


def test_unknown_provider_cost_fail_closed(tmp_path: Path):
    class UnknownCost(ObservableProvider):
        def complete(self, *, system: str, user: str) -> Completion:
            self.complete_calls += 1
            return Completion(text=CLEAN, model=self.observed_served_model, estimated_usd=None)  # type: ignore[arg-type]

    report, _, _ = _run(tmp_path, provider=UnknownCost())
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] == "schema_invalid"


def test_over_cap_actual_spend(tmp_path: Path):
    class Costly(ObservableProvider):
        def complete(self, *, system: str, user: str) -> Completion:
            self.complete_calls += 1
            return Completion(text=CLEAN, model=self.observed_served_model, estimated_usd=5.0)

    report, _, _ = _run(tmp_path, provider=Costly(), max_usd=0.01, reserve_usd_proposal=0.01)
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] == "spend_reservation_rejection"


def test_budget_and_deadline_exhaustion(tmp_path: Path):
    class JumpClock:
        def __init__(self) -> None:
            self.now = time.monotonic()

        def __call__(self) -> float:
            return self.now

        def expire(self) -> None:
            self.now += 10_000

    clock = JumpClock()
    provider = ObservableProvider([DIRTY, CLEAN])

    class ExpiringExaminer(ObservableExaminer):
        def observe(self, request: ExaminerObservationRequest) -> ExaminerBackendResult:
            clock.expire()
            return super().observe(request)

    report, _, _ = _run(
        tmp_path,
        provider=provider,
        examiner=ExpiringExaminer(findings_queue=[_citation_finding]),
        clock=clock,
    )
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] in {
        "wall_deadline_exhausted",
        "already_expired_deadline",
    }

    report2, _, _ = _run(
        tmp_path,
        provider=ObservableProvider([DIRTY, CLEAN]),
        examiner=ObservableExaminer(findings_queue=[_citation_finding, []]),
        max_proposal_completions=1,
        session_id="budget-count",
    )
    assert report2.outcome_kind == "execution"
    assert report2.to_dict()["semantic"]["abort_class"] == "proposal_completion_exhausted"


def test_abort_report_shape_and_cli_exit(tmp_path: Path):
    examiner = ObservableExaminer(status_queue=["backend_error"])
    report, _, _ = _run(tmp_path, examiner=examiner)
    payload = report.to_dict()
    assert payload["outcome_kind"] == "execution"
    assert payload["decision"] is None
    assert payload["terminal"] is None
    assert payload["arbitration"] is None
    assert payload["shard_evaluations"] is None
    assert payload["semantic"]["block_kind"] == "abort"
    assert payload["semantic"]["abort_class"] == "backend_error"
    assert report_exit_code(report) == EXIT_TIMEOUT


def test_success_semantic_report_and_public_redaction(tmp_path: Path):
    report, _, _ = _run(tmp_path)
    internal = report.to_dict()
    semantic = internal["semantic"]
    assert semantic["block_kind"] == "success"
    assert semantic["status"] == "ok"
    assert "deterministic" in semantic["score_maps"]
    assert semantic["observation_prompt_sha256"] == PROMPT_SHA256
    assert semantic["registry_sha256"] == REGISTRY_SHA256
    assert semantic["policy_map_sha256"] == POLICY_MAP_SHA256
    redacted = report.with_redaction().to_dict()["semantic"]
    assert "examiner_id" not in redacted
    assert "claim_fingerprints" not in redacted
    assert "provenance" not in redacted
    assert "origin" not in redacted
    assert redacted["visibility"] == "public"


def test_session_and_report_persist_failure(tmp_path: Path):
    failing = FailingContinuityStore(fail_on_save=True)
    report, provider, _ = _run(tmp_path, persist_store=failing)
    assert provider.complete_calls == 0
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] == "backend_error"

    class FailReport(FileContinuityStore):
        def save(self, session_id: str, payload: dict) -> None:
            raise HybridExecutionAbort("backend_error", "report persist failed")

    report2, provider2, _ = _run(
        tmp_path,
        persist_store=FileContinuityStore(tmp_path / "ok"),
        report_store=FailReport(tmp_path / "reports", suffix=".report.json"),
        session_id="report-fail",
        session_dir=str(tmp_path / "ok"),
    )
    assert provider2.complete_calls >= 1
    assert report2.outcome_kind == "execution"
    assert report2.to_dict()["semantic"]["abort_class"] == "backend_error"


def test_off_mode_and_public_surface_unchanged():
    report = run(CLEAN_RUN)
    assert report.schema_version == "0.1.0"
    assert "semantic" not in report.to_dict()
    scored = evaluate(CLEAN)
    assert scored.schema_version == "0.1.0"
    assert "Ready" not in public.__all__
    assert not hasattr(public, "Ready")
    assert "GoverningIntegration" in public.__all__
    assert public.GOVERNING_INTEGRATION_VERSION == GOVERNING_INTEGRATION_VERSION
    assert SEMANTIC_EXAMINER_OPERATIONAL is False
    assert EXAMINER_PIN_KIND == EXAMINER_PIN_KIND_CALLER_CONFIG
    fields = {item.name for item in RuntimeConfig.__dataclass_fields__.values()}
    assert "hybrid" not in "".join(fields).lower()
    assert "semantic" not in "".join(fields).lower()


def test_locked_hashes_unchanged():
    root = Path("ai4/data/semantic_v07")

    def digest(name: str) -> str:
        return hashlib.sha256((root / name).read_bytes()).hexdigest()

    assert digest("observation_prompt_v1.txt") == PROMPT_SHA256
    assert digest("finding_registry_v1.json") == REGISTRY_SHA256
    assert digest("finding_policy_map_v1.json") == POLICY_MAP_SHA256
    assert observation_prompt_sha256() == PROMPT_SHA256
    assert finding_registry_sha256() == REGISTRY_SHA256
    assert finding_policy_map_sha256() == POLICY_MAP_SHA256
    assert PACKAGED_FUSE_ID == "packaged_fuse_v2"
    assert FINDINGS_SCHEMA_VERSION == "ai4.semantic_findings.v0.7-c2"


def test_no_beta_contamination_in_3c_fixtures():
    fixtures = (CLEAN + CLEAN_RUN + DIRTY).lower()
    for forbidden in ("jane doe", "078-05-1120", "heldout", "beta prompt", "build a bomb"):
        assert forbidden not in fixtures


def test_3a_and_3b_stubs_preserved():
    from ai4.constrain._v07_3a import hybrid_ready as hybrid_ready_3a
    from ai4.constrain._v07_3b import hybrid_ready as hybrid_ready_3b
    import ai4.constrain._v07_3a as prim3a
    import ai4.constrain._v07_3b as prim3b

    assert not hasattr(prim3a, "Ready")
    assert not hasattr(prim3b, "Ready")
    assert hybrid_ready_3a().reason == "slice_incomplete"
    assert hybrid_ready_3b().reason == "deferred_to_3c"
    assert isinstance(hybrid_ready(_ready_context()), Ready)


def test_install_requires_ready(tmp_path: Path):
    store = FileContinuityStore(tmp_path)
    orchestrator = HybridOrchestrator(store, session_id="not-ready")
    with pytest.raises(HybridExecutionAbort):
        orchestrator.install(HybridContextBuilder(_config()).build())


class _ExaminerWithoutCostAttr:
    """Live examiner with no last_estimated_usd attribute at all."""

    observed_peer_origin = EXAMINER_ORIGIN
    observed_account_id = "acct-examiner"
    observed_session_token = "sess-examiner"
    observed_served_model = "synthetic-examiner-model"

    def __init__(self) -> None:
        self.requests: list = []
        self.findings_queue: list = []
        self.status_queue: list = []

    def observe(self, request: ExaminerObservationRequest) -> ExaminerBackendResult:
        return ObservableExaminer.observe(self, request)  # type: ignore[arg-type]


def _assert_no_stranded_examiner(authority: RunBudgetAuthority) -> None:
    snap = authority.snapshot()
    assert snap["examiner_reserved"] == 0
    assert snap["usd_reserved"] == 0
    for handle in authority._reservations.values():
        if handle.kind == "examiner_call":
            assert handle.state not in {"reserved", "executing"}


def _govern(
    tmp_path: Path,
    *,
    provider=None,
    examiner=None,
    authority=None,
    max_revision_rounds: int = 2,
    reserve_usd_proposal: float = 0.0,
    reserve_usd_examiner: float = 0.10,
    proposal: str | None = None,
    prompt: str = CLEAN_RUN,
):
    provider = provider or ObservableProvider()
    examiner = examiner or ObservableExaminer()
    if authority is None:
        authority = RunBudgetAuthority(
            deadline_monotonic=time.monotonic() + 30.0,
            max_proposal_completions=3,
            max_examiner_calls=3,
            max_usd=1.0,
        )
    context = _ready_context(proposer=provider, examiner=examiner, budget_authority=authority)
    store = FileContinuityStore(tmp_path)
    orchestrator = HybridOrchestrator(store, session_id="sf-govern")
    orchestrator.install(context)
    backend = bind_evaluator(None, rubric_set="v0.1")
    middleware = ConstraintMiddleware(
        rubrics=packaged_policy_rubrics(),
        max_revision_rounds=max_revision_rounds,
    )
    abort = None
    result = None
    try:
        result = run_governing_loop(
            orchestrator=orchestrator,
            context=context,
            provider=provider,
            examiner_backend=examiner,
            evaluator=backend,
            middleware=middleware,
            prompt=prompt,
            proposal=proposal,
            specified=(),
            max_revision_rounds=max_revision_rounds,
            reserve_usd_proposal=reserve_usd_proposal,
            reserve_usd_examiner=reserve_usd_examiner,
        )
    except HybridExecutionAbort as exc:
        abort = exc
    return result, abort, authority.snapshot(), authority


@pytest.mark.parametrize(
    "cost,expect_ok",
    [
        ("absent", False),
        (None, False),
        ("1.0", False),
        (math.nan, False),
        (math.inf, False),
        (-math.inf, False),
        (-0.01, False),
        (True, False),
        (0.0, True),
        (0.07, True),
    ],
)
def test_sf1_examiner_cost_validation_governing_path(tmp_path: Path, cost, expect_ok):
    if cost == "absent":
        examiner = _ExaminerWithoutCostAttr()
    else:
        examiner = ObservableExaminer()
        examiner.last_estimated_usd = cost  # type: ignore[assignment]
    authority = RunBudgetAuthority(
        deadline_monotonic=time.monotonic() + 30.0,
        max_proposal_completions=3,
        max_examiner_calls=3,
        max_usd=1.0,
    )
    result, abort, snap, auth = _govern(
        tmp_path,
        examiner=examiner,
        authority=authority,
        reserve_usd_examiner=0.10,
    )
    _assert_no_stranded_examiner(auth)
    if expect_ok:
        assert abort is None
        assert result is not None
        assert snap["examiner_committed"] == 1
        assert snap["examiner_reserved"] == 0
        assert snap["usd_committed"] == pytest.approx(float(cost))
    else:
        assert abort is not None
        assert abort.abort_class == "schema_invalid"
        assert snap["examiner_committed"] == 0
        assert snap["examiner_reserved"] == 0
        assert snap["usd_committed"] == pytest.approx(0.0)


def test_sf1_examiner_actual_over_reservation_commits_honestly(tmp_path: Path):
    examiner = ObservableExaminer()
    examiner.last_estimated_usd = 0.15
    authority = RunBudgetAuthority(
        deadline_monotonic=time.monotonic() + 30.0,
        max_proposal_completions=3,
        max_examiner_calls=3,
        max_usd=1.0,
    )
    result, abort, snap, auth = _govern(
        tmp_path,
        examiner=examiner,
        authority=authority,
        reserve_usd_examiner=0.10,
    )
    assert abort is None
    assert result is not None
    _assert_no_stranded_examiner(auth)
    assert snap["examiner_committed"] == 1
    assert snap["examiner_reserved"] == 0
    assert snap["usd_committed"] == pytest.approx(0.15)
    assert snap["usd_committed"] > 0.10


def test_sf1_unknown_examiner_cost_via_run_releases(tmp_path: Path):
    examiner = _ExaminerWithoutCostAttr()
    report, _, _ = _run(tmp_path, examiner=examiner)
    assert report.outcome_kind == "execution"
    assert report.to_dict()["semantic"]["abort_class"] == "schema_invalid"


def test_sf1_examiner_actual_over_run_max_records_then_fails(tmp_path: Path):
    examiner = ObservableExaminer()
    examiner.last_estimated_usd = 0.08
    authority = RunBudgetAuthority(
        deadline_monotonic=time.monotonic() + 30.0,
        max_proposal_completions=3,
        max_examiner_calls=3,
        max_usd=0.05,
    )
    result, abort, snap, auth = _govern(
        tmp_path,
        examiner=examiner,
        authority=authority,
        reserve_usd_examiner=0.01,
    )
    assert result is None
    assert abort is not None
    assert abort.abort_class == "spend_reservation_rejection"
    _assert_no_stranded_examiner(auth)
    assert snap["examiner_committed"] == 1
    assert snap["examiner_reserved"] == 0
    assert snap["usd_committed"] == pytest.approx(0.08)
    assert snap["usd_committed"] > snap["max_usd"]


def test_sf2_role_scoped_provenance_retained_separately():
    proposer = ObservableProvider()
    examiner = ObservableExaminer()
    p_bundle, e_bundle, _, _, p_obs, e_obs = mint_runtime_provenance(
        configured_label="synthetic-proposer/synthetic-proposer-model",
        examiner_configured_label="synthetic-examiner/synthetic-examiner-model",
        proposer=proposer,
        examiner=examiner,
        proposer_requested_origin=PROPOSER_ORIGIN,
        examiner_requested_origin=EXAMINER_ORIGIN,
        origin_allowlist=(PROPOSER_ORIGIN, EXAMINER_ORIGIN),
    )
    assert p_obs["peer_origin"] == PROPOSER_ORIGIN
    assert e_obs["peer_origin"] == EXAMINER_ORIGIN
    assert p_obs["account_id"] == "acct-proposer"
    assert e_obs["account_id"] == "acct-examiner"
    assert p_obs["session_token"] == "sess-proposer"
    assert e_obs["session_token"] == "sess-examiner"
    assert p_obs["served_model"] == "synthetic-proposer-model"
    assert e_obs["served_model"] == "synthetic-examiner-model"
    assert p_bundle.observed_value("transport_bound") == PROPOSER_ORIGIN
    assert e_bundle.observed_value("transport_bound") == EXAMINER_ORIGIN
    assert p_bundle.observed_value("account_observed") == "acct-proposer"
    assert e_bundle.observed_value("account_observed") == "acct-examiner"
    assert p_bundle.observed_value("provider_session_bound") == "sess-proposer"
    assert e_bundle.observed_value("provider_session_bound") == "sess-examiner"
    assert p_bundle.observed_value("served_model_observed") == "synthetic-proposer-model"
    assert e_bundle.observed_value("served_model_observed") == "synthetic-examiner-model"
    context = _ready_context(proposer=proposer, examiner=examiner)
    assert context.examiner_provenance is not None
    assert context.identity_snapshot.proposer_identity == role_observation_identity(
        "proposer", observation_from_bundle(context.provenance)
    )
    assert context.identity_snapshot.examiner_provenance_identity == role_observation_identity(
        "examiner", observation_from_bundle(context.examiner_provenance)
    )
    assert "proposer:" in context.identity_snapshot.proposer_identity
    assert "examiner:" in context.identity_snapshot.examiner_provenance_identity
    assert "acct-proposer" in context.identity_snapshot.proposer_identity
    assert "acct-examiner" in context.identity_snapshot.examiner_provenance_identity
    assert "acct-examiner" not in context.identity_snapshot.proposer_identity
    assert "acct-proposer" not in context.identity_snapshot.examiner_provenance_identity


def test_sf2_proposer_claims_cannot_satisfy_examiner_ready():
    context = _ready_context()
    missing_examiner = replace(context, examiner_provenance=None)
    result = hybrid_ready(missing_examiner)
    assert isinstance(result, NotReady)
    assert result.reason == GATE_RUNTIME_PROVENANCE
    facts = compute_ready_facts(missing_examiner)
    assert GATE_RUNTIME_PROVENANCE in facts.failed_gates
    assert facts.runtime_observed_provenance is False
    assert any(name.startswith("proposer.") for name in facts.observed_claim_names)
    assert not any(name.startswith("examiner.") for name in facts.observed_claim_names)


def test_sf2_examiner_claims_cannot_satisfy_proposer_ready():
    context = _ready_context()
    proposer_only_configured = replace(
        context,
        provenance=bundle_claims([collect_configured("synthetic-proposer/synthetic-proposer-model")]),
    )
    result = hybrid_ready(proposer_only_configured)
    assert isinstance(result, NotReady)
    assert result.reason == GATE_RUNTIME_PROVENANCE
    facts = compute_ready_facts(proposer_only_configured)
    assert facts.runtime_observed_provenance is False
    assert context.examiner_provenance is not None


def test_sf2_examiner_origin_account_session_model_drift_aborts(tmp_path: Path):
    for attr, value, abort_class in (
        ("observed_peer_origin", "https://examiner-drift.test", "origin_allowlist_failure"),
        ("observed_account_id", "acct-examiner-drift", "account_session_mismatch"),
        ("observed_session_token", "sess-examiner-drift", "account_session_mismatch"),
        ("observed_served_model", "synthetic-examiner-drift", "served_model_mismatch"),
    ):
        examiner = ObservableExaminer()
        authority = RunBudgetAuthority(
            deadline_monotonic=time.monotonic() + 30.0,
            max_proposal_completions=3,
            max_examiner_calls=3,
            max_usd=1.0,
        )
        context = _ready_context(examiner=examiner, budget_authority=authority)
        store = FileContinuityStore(tmp_path / attr)
        orchestrator = HybridOrchestrator(store, session_id=f"drift-{attr}")
        orchestrator.install(context)
        setattr(examiner, attr, value)
        backend = bind_evaluator(None, rubric_set="v0.1")
        middleware = ConstraintMiddleware(
            rubrics=packaged_policy_rubrics(),
            max_revision_rounds=2,
        )
        with pytest.raises(HybridExecutionAbort) as exc:
            run_governing_loop(
                orchestrator=orchestrator,
                context=context,
                provider=ObservableProvider(),
                examiner_backend=examiner,
                evaluator=backend,
                middleware=middleware,
                prompt=CLEAN_RUN,
                proposal=None,
                specified=(),
                max_revision_rounds=2,
                reserve_usd_proposal=0.0,
                reserve_usd_examiner=0.0,
            )
        assert exc.value.abort_class == abort_class


def test_sf2_proposer_four_dimension_checks_intact(tmp_path: Path):
    for attr, value, abort_class in (
        ("observed_peer_origin", "https://proposer-drift.test", "origin_allowlist_failure"),
        ("observed_account_id", "acct-proposer-drift", "account_session_mismatch"),
        ("observed_session_token", "sess-proposer-drift", "account_session_mismatch"),
        ("observed_served_model", "synthetic-proposer-drift", "served_model_mismatch"),
    ):
        provider = ObservableProvider()
        authority = RunBudgetAuthority(
            deadline_monotonic=time.monotonic() + 30.0,
            max_proposal_completions=3,
            max_examiner_calls=3,
            max_usd=1.0,
        )
        context = _ready_context(proposer=provider, budget_authority=authority)
        store = FileContinuityStore(tmp_path / f"p-{attr}")
        orchestrator = HybridOrchestrator(store, session_id=f"p-drift-{attr}")
        orchestrator.install(context)
        setattr(provider, attr, value)
        backend = bind_evaluator(None, rubric_set="v0.1")
        middleware = ConstraintMiddleware(
            rubrics=packaged_policy_rubrics(),
            max_revision_rounds=2,
        )
        with pytest.raises(HybridExecutionAbort) as exc:
            run_governing_loop(
                orchestrator=orchestrator,
                context=context,
                provider=provider,
                examiner_backend=ObservableExaminer(),
                evaluator=backend,
                middleware=middleware,
                prompt=CLEAN_RUN,
                proposal=None,
                specified=(),
                max_revision_rounds=2,
                reserve_usd_proposal=0.0,
                reserve_usd_examiner=0.0,
            )
        assert exc.value.abort_class == abort_class


def test_sf2_revision_round_drift_aborts_before_next_decision(tmp_path: Path):
    provider = ObservableProvider([DIRTY, CLEAN])
    examiner = ObservableExaminer(findings_queue=[_citation_finding, []])
    decisions_before_abort = {"count": 0}

    class CountingMiddleware(ConstraintMiddleware):
        def decide(self, evaluation, **kwargs):  # type: ignore[override]
            decisions_before_abort["count"] += 1
            return super().decide(evaluation, **kwargs)

    original_revise = provider.revise

    def _revise_and_drift(*, system: str, user: str, draft: str, feedback: str):
        examiner.observed_account_id = "acct-examiner-revision-drift"
        return original_revise(system=system, user=user, draft=draft, feedback=feedback)

    provider.revise = _revise_and_drift  # type: ignore[method-assign]
    authority = RunBudgetAuthority(
        deadline_monotonic=time.monotonic() + 30.0,
        max_proposal_completions=3,
        max_examiner_calls=3,
        max_usd=1.0,
    )
    context = _ready_context(proposer=provider, examiner=examiner, budget_authority=authority)
    store = FileContinuityStore(tmp_path)
    orchestrator = HybridOrchestrator(store, session_id="revision-drift")
    orchestrator.install(context)
    backend = bind_evaluator(None, rubric_set="v0.1")
    middleware = CountingMiddleware(
        rubrics=packaged_policy_rubrics(),
        max_revision_rounds=2,
    )
    with pytest.raises(HybridExecutionAbort) as exc:
        run_governing_loop(
            orchestrator=orchestrator,
            context=context,
            provider=provider,
            examiner_backend=examiner,
            evaluator=backend,
            middleware=middleware,
            prompt=CLEAN_RUN,
            proposal=None,
            specified=(),
            max_revision_rounds=2,
            reserve_usd_proposal=0.0,
            reserve_usd_examiner=0.0,
        )
    assert exc.value.abort_class == "account_session_mismatch"
    assert decisions_before_abort["count"] == 1
    assert len(examiner.requests) == 1


def test_sf2_role_scoped_snapshot_comparison():
    context = _ready_context()
    installed = context.identity_snapshot
    detect_identity_drift(installed, installed)
    drifted_examiner = replace(
        installed,
        examiner_provenance_identity=role_observation_identity(
            "examiner",
            {
                "peer_origin": EXAMINER_ORIGIN,
                "account_id": "acct-examiner-other",
                "session_token": "sess-examiner",
                "served_model": "synthetic-examiner-model",
            },
        ),
    )
    with pytest.raises(HybridExecutionAbort) as exc:
        detect_identity_drift(installed, drifted_examiner)
    assert exc.value.abort_class == "identity_drift"
    swapped = replace(
        installed,
        proposer_identity=installed.examiner_provenance_identity,
        examiner_provenance_identity=installed.proposer_identity,
    )
    with pytest.raises(HybridExecutionAbort) as exc:
        detect_identity_drift(installed, swapped)
    assert exc.value.abort_class == "identity_drift"


def test_sf2_public_redaction_strips_role_specific_account_session(tmp_path: Path):
    report, _, _ = _run(tmp_path)
    public_payload = report.with_redaction().to_dict()
    blob = json.dumps(public_payload)
    assert "acct-proposer" not in blob
    assert "acct-examiner" not in blob
    assert "sess-proposer" not in blob
    assert "sess-examiner" not in blob
    semantic = public_payload["semantic"]
    assert "provenance" not in semantic
    assert "examiner_id" not in semantic
    assert "origin" not in semantic
    assert "account" not in semantic
    assert semantic["visibility"] == "public"
