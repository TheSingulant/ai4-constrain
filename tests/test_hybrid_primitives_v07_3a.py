"""V07-3A inert primitives: abort, rebuild, budget, context, reports.

Synthetic fixtures only. No frozen Beta prompts. No live/paid providers.
These tests import the private ``ai4.constrain._v07_3a`` package directly.
They do not activate hybrid on ``run()`` / ``evaluate()``.
"""

from __future__ import annotations

import inspect
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

import ai4.constrain as public
from ai4.constrain import (
    SEMANTIC_EXAMINER_OPERATIONAL,
    evaluate,
    map_and_fuse_v2,
    run,
)
from ai4.constrain._v07_3a import (
    APPROVED_DETERMINISTIC_SHARD_METADATA,
    FORBIDDEN_SEMANTIC_REPORT_FIELDS,
    HYBRID_ABORT_CLASSES,
    HYBRID_ABORT_VOCABULARY_VERSION,
    HybridExecutionAbort,
    NotReady,
    ObservedProvenanceEvidence,
    ReadinessInput,
    RunBudgetAuthority,
    SemanticAbortBlock,
    SemanticSuccessBlock,
    TrustedProductConfig,
    bind_roles,
    evidence_is_authenticated,
    hybrid_ready,
    observed_provenance,
    rebuild_fused_evaluation,
    redact_semantic_block,
    unobserved_provenance,
)
from ai4.constrain._v07_3a.budget import (
    KIND_EXAMINER_CALL,
    KIND_PROPOSAL_COMPLETION,
    STATE_COMMITTED,
    STATE_EXECUTING,
    STATE_RELEASED,
    STATE_RESERVED,
)
from ai4.constrain._v07_3a.context import (
    OBSERVED_KIND_AUTHENTICATED,
    OBSERVED_KIND_RUNTIME,
    ContinuitySnapshot,
)
from ai4.constrain._v07_3a.report import (
    SEMANTIC_BLOCK_SCHEMA_VERSION,
    VISIBILITY_PUBLIC,
)
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.semantic_examiner import EXAMINER_PIN_KIND, EXAMINER_PIN_KIND_CALLER_CONFIG
from ai4.constrain.semantic_fuse import (
    FUSE_EQUATION,
    PACKAGED_FUSE_ID,
    PackagedFuseProvenance,
    PackagedFuseResult,
)
from src.shards.models import CriterionResult, Evaluation, ShardScore
from src.shards.shard_loader import REQUIRED_IDS

REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"
PROMPT_SHA256 = "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"

CLEAN_EVAL = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."
CANDIDATE = "Alpha office stated a synthetic count for review only."


def _pairs(values: dict[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple((shard_id, values[shard_id]) for shard_id in REQUIRED_IDS)


def _scores(**overrides: float) -> dict[str, float]:
    values = {shard_id: 1.0 for shard_id in REQUIRED_IDS}
    values.update(overrides)
    return values


def _det_eval(
    scores: dict[str, float] | None = None,
    *,
    passed: dict[str, bool] | None = None,
    notes: dict[str, tuple[str, ...]] | None = None,
    text: str = CANDIDATE,
) -> Evaluation:
    values = scores or _scores()
    shards = []
    for index, shard_id in enumerate(REQUIRED_IDS):
        shards.append(
            ShardScore(
                shard_id=shard_id,
                version="0.1.0",
                kind="hard" if shard_id in {"privacy", "harm_aversion"} else "soft",
                priority=index,
                score=values[shard_id],
                passed=True if passed is None else passed.get(shard_id, True),
                threshold=0.7,
                results=(
                    CriterionResult(
                        criterion_id=f"{shard_id}-stale",
                        passed=True,
                        score=values[shard_id],
                        evidence="stale-det-evidence",
                    ),
                ),
                notes=notes[shard_id] if notes and shard_id in notes else ("stale-det-note",),
            )
        )
    return Evaluation(text=text, shard_scores=tuple(shards), rubric_set_version="0.1.0")


def _fuse_result(
    fused: dict[str, float],
    *,
    det: dict[str, float] | None = None,
    overlay: dict[str, float] | None = None,
) -> PackagedFuseResult:
    det_map = det or {shard_id: 1.0 for shard_id in REQUIRED_IDS}
    over = overlay or {shard_id: 0.0 for shard_id in REQUIRED_IDS}
    det_pairs = _pairs(det_map)
    fused_pairs = _pairs(fused)
    overlay_pairs = _pairs(over)
    provenance = PackagedFuseProvenance(
        fuse_id=PACKAGED_FUSE_ID,
        equation=FUSE_EQUATION,
        det_scores=det_pairs,
        findings_consumed=(),
        findings_suppressed=(),
        policy_map_artifact_id="finding_policy_map_v1",
        policy_map_schema_version="ai4.finding_policy_map.v1",
        policy_map_version="0.7.0",
        policy_map_sha256=POLICY_MAP_SHA256,
        policy_map_source="synthetic-test",
        taxonomy_version="0.7.0",
        aggregate_overlay=overlay_pairs,
        packaged_caps=overlay_pairs,
        fused_scores=fused_pairs,
    )
    return PackagedFuseResult(
        det_scores=det_pairs,
        overlay=overlay_pairs,
        fused_scores=fused_pairs,
        provenance=provenance,
    )


def _trusted_config() -> TrustedProductConfig:
    return TrustedProductConfig(
        proposer_provider_id="synthetic-proposer",
        proposer_model_id="synthetic-proposer-model",
        examiner_provider_id="synthetic-examiner",
        examiner_model_id="synthetic-examiner-model",
        examiner_id="synthetic-examiner-id",
        examiner_version="0.7.3a-test",
        observation_prompt_sha256=PROMPT_SHA256,
    )


# --- §1 HybridExecutionAbort -------------------------------------------------


def test_abort_vocabulary_is_closed_and_versioned():
    required = {
        "already_expired_deadline",
        "wall_deadline_exhausted",
        "spend_reservation_rejection",
        "proposal_completion_exhausted",
        "examiner_call_exhaustion",
        "backend_error",
        "schema_invalid",
        "empty_parse",
        "injection_suspected",
        "caller_config_pin_forbidden",
        "provenance_mismatch",
        "origin_allowlist_failure",
        "served_model_mismatch",
        "account_session_mismatch",
        "observation_prompt_hash_mismatch",
        "registry_hash_mismatch",
        "policy_map_hash_mismatch",
        "fuse_failure",
        "identity_drift",
        "continuity_required_not_ready",
    }
    assert required <= set(HYBRID_ABORT_CLASSES)
    assert HYBRID_ABORT_VOCABULARY_VERSION == "v07.3a.1"
    for abort_class in required:
        exc = HybridExecutionAbort(abort_class, "synthetic")
        assert exc.abort_class == abort_class
        assert exc.vocabulary_version == HYBRID_ABORT_VOCABULARY_VERSION
        dumped = exc.to_audit_dict()
        assert dumped["abort_class"] == abort_class
        assert "decision" not in dumped
        assert "passed" not in dumped
        assert "threshold" not in dumped
        assert "arbitration" not in dumped
        assert "terminal" not in dumped


def test_abort_rejects_unknown_class_and_governing_kwargs():
    with pytest.raises(ValueError, match="Unknown HybridExecutionAbort.abort_class"):
        HybridExecutionAbort("not_a_real_class")
    with pytest.raises(ValueError, match="governing field"):
        HybridExecutionAbort("backend_error", decision="refuse")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="governing field"):
        HybridExecutionAbort("backend_error", passed=True)  # type: ignore[call-arg]
    assert not issubclass(HybridExecutionAbort, ConstraintExecutionError)


# --- §2 rebuild_fused_evaluation --------------------------------------------


def test_rebuild_discards_stale_passed_true():
    det = _det_eval(_scores(truth=0.9), passed={shard_id: True for shard_id in REQUIRED_IDS})
    assert all(item.passed for item in det.shard_scores)
    fused = _scores(truth=0.6)
    rebuilt = rebuild_fused_evaluation(det, _fuse_result(fused, det=_scores(truth=0.9)))
    assert all(item.passed is False for item in rebuilt.shard_scores)
    assert rebuilt.by_id()["truth"].score == pytest.approx(0.6)
    assert rebuilt.by_id()["compassion"].score == pytest.approx(1.0)


def test_rebuild_rejects_score_increase():
    det = _det_eval(_scores(truth=0.5))
    fused = _scores(truth=0.51)
    with pytest.raises(HybridExecutionAbort, match="exceeds") as exc:
        rebuild_fused_evaluation(det, _fuse_result(fused, det=_scores(truth=0.5)))
    assert exc.value.abort_class == "fuse_failure"


def test_rebuild_rejects_missing_and_extra_shards():
    det = _det_eval()
    missing = {shard_id: 1.0 for shard_id in REQUIRED_IDS if shard_id != "truth"}
    with pytest.raises(HybridExecutionAbort) as missing_exc:
        rebuild_fused_evaluation(
            det,
            replace(
                _fuse_result(_scores()),
                fused_scores=tuple((k, v) for k, v in missing.items()),
            ),
        )
    assert missing_exc.value.abort_class == "schema_invalid"
    assert "missing" in missing_exc.value.message

    extra_pairs = _pairs(_scores()) + (("extra_shard", 0.1),)
    with pytest.raises(HybridExecutionAbort) as extra_exc:
        rebuild_fused_evaluation(
            det,
            replace(_fuse_result(_scores()), fused_scores=extra_pairs),
        )
    assert extra_exc.value.abort_class == "schema_invalid"
    assert "extra" in extra_exc.value.message


def test_rebuild_rejects_nan_and_inf():
    det = _det_eval()
    for bad in (math.nan, math.inf, -math.inf):
        fused = _scores(truth=bad)
        with pytest.raises(HybridExecutionAbort) as exc:
            rebuild_fused_evaluation(det, _fuse_result(fused))
        assert exc.value.abort_class == "fuse_failure"


def test_rebuild_allows_exact_boundary_score():
    det_scores = _scores(truth=0.42, autonomy=0.0)
    det = _det_eval(det_scores)
    rebuilt = rebuild_fused_evaluation(det, _fuse_result(det_scores, det=det_scores))
    assert rebuilt.by_id()["truth"].score == 0.42
    assert rebuilt.by_id()["autonomy"].score == 0.0
    assert rebuilt.by_id()["truth"].passed is False


def test_rebuild_metadata_preservation_rules():
    det = _det_eval(_scores(truth=0.8))
    rebuilt = rebuild_fused_evaluation(
        det, _fuse_result(_scores(truth=0.5), det=_scores(truth=0.8))
    )
    assert rebuilt.text == det.text
    assert rebuilt.rubric_set_version == det.rubric_set_version
    for shard_id in REQUIRED_IDS:
        src = det.by_id()[shard_id]
        out = rebuilt.by_id()[shard_id]
        assert {field: getattr(out, field) for field in APPROVED_DETERMINISTIC_SHARD_METADATA} == {
            field: getattr(src, field) for field in APPROVED_DETERMINISTIC_SHARD_METADATA
        }
        assert out.notes == ()
        assert out.results == ()
        assert out.passed is False
        assert "stale-det-note" not in out.notes
        assert src.notes == ("stale-det-note",)
        assert src.results[0].evidence == "stale-det-evidence"


def test_rebuild_identity_drift_and_real_fuse_result():
    det = _det_eval(_scores(truth=0.9))
    with pytest.raises(HybridExecutionAbort) as exc:
        rebuild_fused_evaluation(det, _fuse_result(_scores(truth=0.5), det=_scores(truth=0.8)))
    assert exc.value.abort_class == "identity_drift"

    from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION, bind_semantic_findings

    payload = {
        "schema_version": FINDINGS_SCHEMA_VERSION,
        "examiner_id": "synthetic-examiner-v07-3a",
        "examiner_version": "0.7.3a-test",
        "model_id": "synthetic-model",
        "provider_id": "synthetic-provider",
        "observation_prompt_sha256": "ab" * 32,
        "temperature": 0,
        "status": "ok",
        "findings": [],
    }
    bound = bind_semantic_findings(payload, candidate=CANDIDATE)
    det_map = _scores(truth=0.8)
    result = map_and_fuse_v2(det_map, bound)
    rebuilt = rebuild_fused_evaluation(_det_eval(det_map), result)
    assert rebuilt.by_id()["truth"].score == pytest.approx(0.8)
    assert all(item.passed is False for item in rebuilt.shard_scores)


def test_rebuild_does_not_call_packaged_wall():
    source = inspect.getsource(rebuild_fused_evaluation)
    assert "overlay_packaged_policy" not in source
    assert "evaluator_wall" not in inspect.getsource(
        __import__("ai4.constrain._v07_3a.rebuild", fromlist=["rebuild_fused_evaluation"])
    )


def test_rebuild_rejects_authority_kwargs():
    with pytest.raises(HybridExecutionAbort) as exc:
        rebuild_fused_evaluation(_det_eval(), _fuse_result(_scores()), install=True)  # type: ignore[call-arg]
    assert exc.value.abort_class == "caller_config_pin_forbidden"


# --- §3 RunBudgetAuthority ---------------------------------------------------


def test_budget_reserve_execute_commit_actual():
    clock = {"now": 0.0}
    auth = RunBudgetAuthority(
        deadline_monotonic=10.0,
        max_proposal_completions=2,
        max_examiner_calls=2,
        max_usd=1.0,
        clock=lambda: clock["now"],
    )
    reserved = auth.reserve_proposal_completion(usd=0.40)
    assert reserved.state == STATE_RESERVED
    assert reserved.kind == KIND_PROPOSAL_COMPLETION
    executing = auth.begin_execute(reserved)
    assert executing.state == STATE_EXECUTING
    committed = auth.commit(executing, actual_usd=0.11)
    assert committed.state == STATE_COMMITTED
    snap = auth.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.11)
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["usd_available"] == pytest.approx(0.89)
    assert snap["proposal_committed"] == 1

    examiner = auth.reserve_examiner_call(usd=0.20)
    assert examiner.kind == KIND_EXAMINER_CALL
    auth.begin_execute(examiner)
    auth.commit(examiner, actual_usd=0.05)
    snap = auth.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.16)
    assert snap["examiner_committed"] == 1
    assert snap["proposal_committed"] == 1


def test_budget_shared_usd_ledger_separate_counts():
    auth = RunBudgetAuthority(
        deadline_monotonic=100.0,
        max_proposal_completions=1,
        max_examiner_calls=1,
        max_usd=0.10,
        clock=lambda: 0.0,
    )
    proposal = auth.reserve_proposal_completion(usd=0.07)
    with pytest.raises(HybridExecutionAbort) as spend:
        auth.reserve_examiner_call(usd=0.04)
    assert spend.value.abort_class == "spend_reservation_rejection"
    examiner = auth.reserve_examiner_call(usd=0.03)
    with pytest.raises(HybridExecutionAbort) as proposal_count:
        auth.reserve_proposal_completion(usd=0.0)
    assert proposal_count.value.abort_class == "proposal_completion_exhausted"
    auth.release(proposal)
    auth.release(examiner)
    again = auth.reserve_proposal_completion(usd=0.10)
    auth.release(again)
    with pytest.raises(HybridExecutionAbort) as examiner_count:
        auth = RunBudgetAuthority(
            deadline_monotonic=100.0,
            max_proposal_completions=2,
            max_examiner_calls=0,
            max_usd=1.0,
            clock=lambda: 0.0,
        )
        auth.reserve_examiner_call(usd=0.0)
    assert examiner_count.value.abort_class == "examiner_call_exhaustion"


def test_budget_distinguishes_deadline_spend_and_count():
    clock = {"now": 5.0}
    auth = RunBudgetAuthority(
        deadline_monotonic=5.0,
        max_proposal_completions=1,
        max_examiner_calls=1,
        max_usd=0.01,
        clock=lambda: clock["now"],
    )
    with pytest.raises(HybridExecutionAbort) as expired:
        auth.reserve_proposal_completion(usd=0.0)
    assert expired.value.abort_class == "already_expired_deadline"

    clock["now"] = 0.0
    auth = RunBudgetAuthority(
        deadline_monotonic=5.0,
        max_proposal_completions=1,
        max_examiner_calls=1,
        max_usd=0.01,
        clock=lambda: clock["now"],
    )
    reserved = auth.reserve_proposal_completion(usd=0.01)
    clock["now"] = 5.0
    with pytest.raises(HybridExecutionAbort) as wall:
        auth.begin_execute(reserved)
    assert wall.value.abort_class == "wall_deadline_exhausted"
    assert auth.snapshot()["usd_reserved"] == pytest.approx(0.0)

    fresh = RunBudgetAuthority(
        deadline_monotonic=50.0,
        max_proposal_completions=1,
        max_examiner_calls=1,
        max_usd=0.01,
        clock=lambda: 0.0,
    )
    handle = fresh.reserve_proposal_completion(usd=0.01)
    fresh.begin_execute(handle)
    with pytest.raises(HybridExecutionAbort) as over:
        fresh.commit(handle, actual_usd=0.02)
    assert over.value.abort_class == "spend_reservation_rejection"
    stored = fresh._reservations[handle.reservation_id]
    assert stored.state == STATE_COMMITTED
    assert stored.reserved_usd == pytest.approx(0.02)
    snap = fresh.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.02)
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["proposal_reserved"] == 0
    assert snap["proposal_committed"] == 1


def test_budget_thread_safe_shared_ledger():
    auth = RunBudgetAuthority(
        deadline_monotonic=1_000.0,
        max_proposal_completions=50,
        max_examiner_calls=50,
        max_usd=0.10,
        clock=lambda: 0.0,
    )
    wins = []
    lock = threading.Lock()

    def _try(kind: str) -> None:
        try:
            if kind == "proposal":
                handle = auth.reserve_proposal_completion(usd=0.04)
            else:
                handle = auth.reserve_examiner_call(usd=0.04)
        except HybridExecutionAbort as exc:
            assert exc.abort_class in {
                "spend_reservation_rejection",
                "proposal_completion_exhausted",
                "examiner_call_exhaustion",
            }
            return
        with lock:
            wins.append(handle)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_try, ["proposal", "examiner"] * 8))
    snap = auth.snapshot()
    assert snap["usd_reserved"] + snap["usd_committed"] <= 0.10 + 1e-12
    assert 1 <= len(wins) <= 2
    assert snap["usd_reserved"] == pytest.approx(0.04 * len(wins))


def _budget(*, max_usd: float, proposals: int = 2, examiners: int = 2) -> RunBudgetAuthority:
    return RunBudgetAuthority(
        deadline_monotonic=100.0,
        max_proposal_completions=proposals,
        max_examiner_calls=examiners,
        max_usd=max_usd,
        clock=lambda: 0.0,
    )


def _executing(auth: RunBudgetAuthority, *, kind: str, usd: float):
    if kind == KIND_PROPOSAL_COMPLETION:
        handle = auth.reserve_proposal_completion(usd=usd)
    else:
        handle = auth.reserve_examiner_call(usd=usd)
    return auth.begin_execute(handle)


def test_budget_commit_actual_above_reserved_within_max_succeeds():
    auth = _budget(max_usd=0.30)
    handle = _executing(auth, kind=KIND_PROPOSAL_COMPLETION, usd=0.25)
    committed = auth.commit(handle, actual_usd=0.30)
    assert committed.state == STATE_COMMITTED
    assert committed.reserved_usd == pytest.approx(0.30)
    snap = auth.snapshot()
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["usd_committed"] == pytest.approx(0.30)
    assert snap["proposal_reserved"] == 0
    assert snap["proposal_committed"] == 1
    assert auth._reservations[handle.reservation_id].state == STATE_COMMITTED


def test_budget_commit_actual_above_max_counts_then_fail_closed():
    auth = _budget(max_usd=0.28)
    handle = _executing(auth, kind=KIND_PROPOSAL_COMPLETION, usd=0.25)
    with pytest.raises(HybridExecutionAbort) as exc:
        auth.commit(handle, actual_usd=0.30)
    assert exc.value.abort_class == "spend_reservation_rejection"
    stored = auth._reservations[handle.reservation_id]
    assert stored.state == STATE_COMMITTED
    assert stored.state != STATE_EXECUTING
    assert stored.reserved_usd == pytest.approx(0.30)
    snap = auth.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.30)
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["proposal_reserved"] == 0
    assert snap["proposal_committed"] == 1
    with pytest.raises(HybridExecutionAbort) as later:
        auth.reserve_proposal_completion(usd=0.0)
    assert later.value.abort_class == "spend_reservation_rejection"


def test_budget_commit_examiner_actual_above_reserved_same_behavior():
    within = _budget(max_usd=0.30)
    handle = _executing(within, kind=KIND_EXAMINER_CALL, usd=0.25)
    committed = within.commit(handle, actual_usd=0.30)
    assert committed.state == STATE_COMMITTED
    snap = within.snapshot()
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["usd_committed"] == pytest.approx(0.30)
    assert snap["examiner_reserved"] == 0
    assert snap["examiner_committed"] == 1

    over = _budget(max_usd=0.28)
    handle = _executing(over, kind=KIND_EXAMINER_CALL, usd=0.25)
    with pytest.raises(HybridExecutionAbort) as exc:
        over.commit(handle, actual_usd=0.30)
    assert exc.value.abort_class == "spend_reservation_rejection"
    stored = over._reservations[handle.reservation_id]
    assert stored.state == STATE_COMMITTED
    snap = over.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.30)
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["examiner_reserved"] == 0
    assert snap["examiner_committed"] == 1


def test_budget_commit_overrun_shared_ledger_concurrent_accounting():
    auth = _budget(max_usd=0.50, proposals=8, examiners=8)
    errors: list[str] = []
    committed_ids: list[int] = []
    lock = threading.Lock()

    def _run(kind: str) -> None:
        handle = _executing(auth, kind=kind, usd=0.20)
        try:
            auth.commit(handle, actual_usd=0.30)
        except HybridExecutionAbort as exc:
            with lock:
                errors.append(exc.abort_class)
        stored = auth._reservations[handle.reservation_id]
        assert stored.state == STATE_COMMITTED
        assert stored.state != STATE_EXECUTING
        with lock:
            committed_ids.append(handle.reservation_id)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_run, [KIND_PROPOSAL_COMPLETION, KIND_EXAMINER_CALL]))
    snap = auth.snapshot()
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["usd_committed"] == pytest.approx(0.60)
    assert snap["proposal_reserved"] == 0
    assert snap["examiner_reserved"] == 0
    assert snap["proposal_committed"] + snap["examiner_committed"] == 2
    assert len(committed_ids) == 2
    assert "spend_reservation_rejection" in errors
    assert all(cls == "spend_reservation_rejection" for cls in errors)


def test_budget_commit_underrun_unchanged():
    auth = _budget(max_usd=1.0)
    handle = _executing(auth, kind=KIND_PROPOSAL_COMPLETION, usd=0.40)
    committed = auth.commit(handle, actual_usd=0.11)
    assert committed.state == STATE_COMMITTED
    assert committed.reserved_usd == pytest.approx(0.11)
    snap = auth.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.11)
    assert snap["usd_reserved"] == pytest.approx(0.0)
    assert snap["usd_available"] == pytest.approx(0.89)
    leftover = auth.reserve_examiner_call(usd=0.89)
    auth.release(leftover)


def test_budget_release_and_double_commit_invariants_unchanged():
    auth = _budget(max_usd=1.0)
    reserved = auth.reserve_proposal_completion(usd=0.20)
    released = auth.release(reserved)
    assert released.state == STATE_RELEASED
    assert auth.snapshot()["usd_reserved"] == pytest.approx(0.0)
    assert auth.snapshot()["proposal_reserved"] == 0
    with pytest.raises(HybridExecutionAbort) as already:
        auth.release(released)
    assert already.value.abort_class == "schema_invalid"

    handle = _executing(auth, kind=KIND_EXAMINER_CALL, usd=0.20)
    committed = auth.commit(handle, actual_usd=0.05)
    with pytest.raises(HybridExecutionAbort) as second:
        auth.commit(committed, actual_usd=0.05)
    assert second.value.abort_class == "schema_invalid"
    with pytest.raises(HybridExecutionAbort) as after:
        auth.release(committed)
    assert after.value.abort_class == "schema_invalid"
    snap = auth.snapshot()
    assert snap["usd_committed"] == pytest.approx(0.05)
    assert snap["examiner_committed"] == 1
    assert snap["examiner_reserved"] == 0


# --- §4 hybrid context / types ----------------------------------------------


def test_trusted_config_is_not_observed_evidence():
    config = _trusted_config()
    observed = observed_provenance(served_model=config.examiner_model_id)
    assert not isinstance(config, ObservedProvenanceEvidence)
    assert observed.kind == OBSERVED_KIND_RUNTIME
    assert evidence_is_authenticated(observed) is False
    assert evidence_is_authenticated(unobserved_provenance()) is False
    copied = ObservedProvenanceEvidence(
        kind=OBSERVED_KIND_RUNTIME,
        served_model=config.examiner_model_id,
        origin=config.examiner_provider_id,
    )
    assert evidence_is_authenticated(copied) is False
    with pytest.raises(HybridExecutionAbort) as exc:
        ObservedProvenanceEvidence(kind=OBSERVED_KIND_AUTHENTICATED, served_model="x")
    assert exc.value.abort_class == "caller_config_pin_forbidden"


def test_hybrid_ready_always_not_ready_and_cannot_install():
    config = _trusted_config()
    bindings = bind_roles(config)
    readiness = ReadinessInput(
        trusted_config=config,
        observed_evidence=unobserved_provenance(),
        role_bindings=bindings,
        continuity=ContinuitySnapshot(
            ever_on=False,
            ever_required=False,
            persisted_report_schema_0_2_0=False,
            persisted_semantic=False,
        ),
    )
    for context in (None, config, readiness, {"product": "run"}):
        result = hybrid_ready(context)
        assert isinstance(result, NotReady)
        assert result.reason == "slice_incomplete"
        with pytest.raises(HybridExecutionAbort) as exc:
            result.install()
        assert exc.value.abort_class == "continuity_required_not_ready"
    import ai4.constrain._v07_3a.context as ctx

    assert not hasattr(ctx, "Ready")
    assert not hasattr(ctx, "install_hybrid")
    assert not hasattr(ctx, "HybridObservedEvaluator")
    with pytest.raises(HybridExecutionAbort) as forbidden:
        hybrid_ready(config, install=True)  # type: ignore[call-arg]
    assert forbidden.value.abort_class == "caller_config_pin_forbidden"


def test_role_bindings_remain_caller_config():
    config = _trusted_config()
    proposer, examiner = bind_roles(config)
    assert proposer.role == "proposer"
    assert examiner.role == "examiner"
    assert proposer.pin_kind == EXAMINER_PIN_KIND_CALLER_CONFIG
    assert examiner.binding_source == "trusted_config"
    assert EXAMINER_PIN_KIND == EXAMINER_PIN_KIND_CALLER_CONFIG
    with pytest.raises(HybridExecutionAbort):
        TrustedProductConfig(
            proposer_provider_id="a",
            proposer_model_id="b",
            examiner_provider_id="c",
            examiner_model_id="d",
            examiner_id="e",
            examiner_version="f",
            observation_prompt_sha256=PROMPT_SHA256,
            pin_kind="authenticated",
        )


# --- §7 semantic report primitives ------------------------------------------


def test_semantic_success_and_abort_blocks_are_non_governing():
    success = SemanticSuccessBlock(
        findings_count=2,
        observation_prompt_sha256=PROMPT_SHA256,
        registry_sha256=REGISTRY_SHA256,
        policy_map_sha256=POLICY_MAP_SHA256,
        examiner_id="synthetic-examiner",
        examiner_version="0.7.3a-test",
        provider_id="synthetic-provider",
        model_id="synthetic-model",
    )
    public_success = redact_semantic_block(success)
    assert public_success["visibility"] == VISIBILITY_PUBLIC
    assert public_success["status"] == "ok"
    assert public_success["schema_version"] == SEMANTIC_BLOCK_SCHEMA_VERSION
    assert "examiner_id" not in public_success
    for field in FORBIDDEN_SEMANTIC_REPORT_FIELDS:
        assert field not in public_success
        assert field not in success.to_dict()

    abort = SemanticAbortBlock(abort_class="empty_parse", detail="synthetic empty")
    public_abort = redact_semantic_block(abort)
    assert public_abort["abort_class"] == "empty_parse"
    assert "detail" not in public_abort
    assert "decision" not in public_abort
    with pytest.raises(HybridExecutionAbort):
        SemanticAbortBlock(abort_class="not-a-class")
    with pytest.raises(TypeError):
        SemanticSuccessBlock(  # type: ignore[call-arg]
            findings_count=0,
            observation_prompt_sha256=PROMPT_SHA256,
            registry_sha256=REGISTRY_SHA256,
            policy_map_sha256=POLICY_MAP_SHA256,
            decision="accept",
        )


def test_semantic_blocks_not_on_live_decision_report():
    report = evaluate(CLEAN_EVAL)
    payload = report.to_dict()
    assert payload["schema_version"] == "0.1.0"
    for key in ("semantic", "semantic_success", "semantic_abort", "semantic_block"):
        assert key not in payload
    loop = run(CLEAN_RUN)
    assert loop.to_dict()["schema_version"] == "0.1.0"
    assert "semantic_success" not in loop.to_dict()


def test_public_package_does_not_export_hybrid_installers():
    for name in (
        "HybridExecutionAbort",
        "rebuild_fused_evaluation",
        "RunBudgetAuthority",
        "hybrid_ready",
        "HybridObservedEvaluator",
        "install_hybrid",
        "Ready",
    ):
        assert name not in public.__all__
        assert not hasattr(public, name)
    assert SEMANTIC_EXAMINER_OPERATIONAL is False
    assert public.SEMANTIC_EXAMINER_OPERATIONAL is False


def test_fixtures_are_not_beta_paraphrases():
    texts = (
        CANDIDATE.lower(),
        CLEAN_EVAL.lower(),
        CLEAN_RUN.lower(),
    )
    for text in texts:
        for forbidden in ("jane doe", "078-05-1120", "build a bomb", "heldout", "beta prompt"):
            assert forbidden not in text
