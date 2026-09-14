"""V07-3B session 0.2.0 / DecisionReport 0.2.0 and backward compatibility.

Synthetic fixtures only. Product OFF serialization stays 0.1.x unless an
explicit 0.2.0 object is constructed through the private 3B path.
"""

from __future__ import annotations

import copy
import json

import pytest

from ai4.constrain import evaluate, run
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3b.provenance import bundle_claims, collect_configured
from ai4.constrain._v07_3b.report import (
    REPORT_SCHEMA_VERSION_0_2_0,
    SEMANTIC_DOCUMENT_SCHEMA_VERSION,
    FindingAudit,
    HybridReportDocument,
    SemanticDocument,
    parse_decision_report_document,
    redact_semantic_document,
    serialize_decision_report_document,
    serialize_decision_report_json,
)
from ai4.constrain._v07_3b.session import (
    SESSION_SCHEMA_VERSION_0_2_0,
    HybridSessionDocument,
    HybridSessionIdentity,
    parse_session_document,
    serialize_session_document,
    serialize_session_json,
)
from ai4.constrain._v07_3b.snapshot import ArtifactContinuitySnapshot
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport
from ai4.constrain.semantic_findings import FINDINGS_SCHEMA_VERSION
from ai4.constrain.semantic_fuse import PACKAGED_FUSE_ID
from ai4.constrain.session import SESSION_SCHEMA_VERSION, ConstrainedSession, SessionState
from src.providers.mock import HeuristicMockProvider
from src.shards.shard_loader import REQUIRED_IDS

REGISTRY_SHA256 = "e817eb246889cd19e090f96f005b577252b90b87028c50860e03cacbcee94535"
POLICY_MAP_SHA256 = "c84c613d7811fd0701ac90051d4f5b9640b90e8e978430bbd64f4cca81215a78"
PROMPT_SHA256 = "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"
CLEAN_EVAL = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."


def _score_maps() -> dict[str, dict[str, float]]:
    ones = {shard_id: 1.0 for shard_id in REQUIRED_IDS}
    zeros = {shard_id: 0.0 for shard_id in REQUIRED_IDS}
    return {"deterministic": ones, "overlay": zeros, "fused": ones}


def _semantic_success() -> SemanticDocument:
    return SemanticDocument(
        block_kind="success",
        status="ok",
        observation_prompt_sha256=PROMPT_SHA256,
        registry_sha256=REGISTRY_SHA256,
        policy_map_sha256=POLICY_MAP_SHA256,
        score_maps=_score_maps(),
        findings=(
            FindingAudit(
                finding_id="f1",
                class_id="unsupported_certainty",
                observation_code="ungrounded_certainty_cue",
            ),
        ),
        claim_fingerprints=("cf_v1:synthetic",),
        provenance=bundle_claims((collect_configured("synthetic-examiner"),)),
        examiner_id="synthetic-examiner-id",
        examiner_version="0.7.3b-test",
        provider_id="synthetic-examiner",
        model_id="synthetic-examiner-model",
    )


def _semantic_abort() -> SemanticDocument:
    return SemanticDocument(
        block_kind="abort",
        abort_class="empty_parse",
        detail="synthetic empty",
        observation_prompt_sha256=PROMPT_SHA256,
        registry_sha256=REGISTRY_SHA256,
        policy_map_sha256=POLICY_MAP_SHA256,
        score_maps=_score_maps(),
        findings=(),
        claim_fingerprints=(),
        provenance=bundle_claims((collect_configured("synthetic-examiner"),)),
    )


def _snapshot() -> ArtifactContinuitySnapshot:
    return ArtifactContinuitySnapshot(
        observation_prompt_sha256=PROMPT_SHA256,
        registry_sha256=REGISTRY_SHA256,
        policy_map_sha256=POLICY_MAP_SHA256,
        fuse_id=PACKAGED_FUSE_ID,
        examiner_config_identity="synthetic-examiner",
        examiner_provenance_identity="configured=configured",
        proposer_identity="synthetic-proposer",
        evaluator_identity="v0.1-regex",
        evaluator_fingerprint="frozen:v0.1-regex",
        semantic_schema_version=FINDINGS_SCHEMA_VERSION,
        examiner_call_cap=1,
        semantic_config_version="v07.3b.0",
    )


def test_old_session_and_new_off_session_round_trip_byte_for_byte():
    session = ConstrainedSession(provider=HeuristicMockProvider(), persist=False)
    session.complete(CLEAN_RUN)
    state = session.snapshot()
    assert state.schema_version == SESSION_SCHEMA_VERSION == "0.1.1"
    product_json = state.to_json()
    product_dict = state.to_dict()
    assert "ever_on" not in product_dict
    assert "hybrid_identity" not in product_dict

    old_loaded = SessionState.from_dict(json.loads(product_json))
    assert old_loaded.to_json() == product_json

    new_doc = parse_session_document(product_dict)
    assert new_doc.schema_version == "0.1.1"
    assert new_doc.identity.ever_on is False
    assert serialize_session_json(new_doc) == product_json
    assert serialize_session_document(new_doc) == product_dict


def test_new_reader_loads_explicit_0_2_0_and_old_reader_fails():
    session = ConstrainedSession(provider=HeuristicMockProvider(), persist=False)
    session.complete(CLEAN_RUN)
    off = session.snapshot()
    hybrid = HybridSessionDocument(
        schema_version=SESSION_SCHEMA_VERSION_0_2_0,
        off_state=off,
        identity=HybridSessionIdentity(ever_on=False, artifact_snapshot=_snapshot()),
    )
    payload = serialize_session_document(hybrid)
    assert payload["schema_version"] == "0.2.0"
    assert payload["ever_on"] is False
    parsed = parse_session_document(payload)
    assert parsed.identity.ever_on is False
    assert parsed.durable_intent() is False

    with pytest.raises(ConstraintExecutionError, match="schema_version|hybrid identity"):
        SessionState.from_dict(payload)

    ever_on = HybridSessionDocument(
        schema_version=SESSION_SCHEMA_VERSION_0_2_0,
        off_state=off,
        identity=HybridSessionIdentity(ever_on=True, artifact_snapshot=_snapshot()),
    )
    ever_payload = serialize_session_document(ever_on)
    parsed_on = parse_session_document(ever_payload)
    assert parsed_on.identity.ever_on is True
    assert parsed_on.durable_intent() is True
    assert parsed_on.continuity_required() is True
    with pytest.raises(ConstraintExecutionError, match="schema_version|hybrid identity"):
        SessionState.from_dict(ever_payload)


def test_old_reader_rejects_injected_hybrid_identity_on_0_1_x():
    session = ConstrainedSession(provider=HeuristicMockProvider(), persist=False)
    session.complete(CLEAN_RUN)
    payload = session.snapshot().to_dict()
    injected = dict(payload)
    injected["ever_on"] = True
    with pytest.raises(ConstraintExecutionError, match="hybrid identity"):
        SessionState.from_dict(injected)
    with pytest.raises(HybridExecutionAbort) as exc:
        parse_session_document(injected)
    assert exc.value.abort_class == "schema_invalid"


def test_continuity_mirror_only_tightens():
    session = ConstrainedSession(provider=HeuristicMockProvider(), persist=False)
    session.complete(CLEAN_RUN)
    off = session.snapshot()
    payload = serialize_session_document(
        HybridSessionDocument(
            schema_version=SESSION_SCHEMA_VERSION_0_2_0,
            off_state=off,
            identity=HybridSessionIdentity(ever_on=True),
            ever_required=False,
        )
    )
    payload["ever_required"] = True
    parsed = parse_session_document(payload)
    assert parsed.identity.ever_on is True
    assert parsed.ever_required is True
    disagree = copy.deepcopy(payload)
    disagree["hybrid_identity"] = {"schema_version": "0.2.0", "ever_on": False, "artifact_snapshot": None}
    disagree["ever_on"] = True
    with pytest.raises(HybridExecutionAbort):
        parse_session_document(disagree)


def test_old_report_and_new_off_report_byte_for_byte():
    report = evaluate(CLEAN_EVAL)
    product_json = report.to_json()
    product_dict = report.to_dict()
    assert product_dict["schema_version"] == "0.1.0"
    assert "semantic" not in product_dict
    assert DecisionReport.from_json(product_json).to_json() == product_json
    doc = parse_decision_report_document(product_dict)
    assert doc.schema_version == "0.1.0"
    assert doc.semantic is None
    assert serialize_decision_report_json(doc) == product_json
    assert serialize_decision_report_document(doc) == product_dict
    loop = run(CLEAN_RUN)
    assert loop.to_dict()["schema_version"] == "0.1.0"
    assert "semantic" not in loop.to_dict()


def test_report_0_2_0_semantic_success_and_abort_and_redaction():
    off = evaluate(CLEAN_EVAL)
    success_doc = HybridReportDocument(
        schema_version=REPORT_SCHEMA_VERSION_0_2_0,
        off_report=off,
        semantic=_semantic_success(),
    )
    payload = serialize_decision_report_document(success_doc)
    assert payload["schema_version"] == "0.2.0"
    assert payload["semantic"]["schema_version"] == SEMANTIC_DOCUMENT_SCHEMA_VERSION
    assert payload["semantic"]["status"] == "ok"
    assert "decision" not in payload["semantic"]
    assert "threshold" not in payload["semantic"]
    assert "passed" not in payload["semantic"]
    assert "arbitration" not in payload["semantic"]
    assert "terminal" not in payload["semantic"]
    parsed = parse_decision_report_document(payload)
    assert parsed.semantic is not None
    assert parsed.semantic.findings_count == 1
    public = redact_semantic_document(parsed.semantic)
    assert public["visibility"] == "public"
    assert "examiner_id" not in public
    assert "claim_fingerprints" not in public
    assert "provenance" not in public
    assert "provider_id" not in public
    assert public["finding_ids"] == ["f1"]

    abort_doc = HybridReportDocument(
        schema_version=REPORT_SCHEMA_VERSION_0_2_0,
        off_report=off,
        semantic=_semantic_abort(),
    )
    abort_payload = serialize_decision_report_document(abort_doc)
    abort_parsed = parse_decision_report_document(abort_payload)
    assert abort_parsed.semantic is not None
    assert abort_parsed.semantic.abort_class == "empty_parse"
    assert "decision" not in abort_parsed.semantic.to_dict()

    with pytest.raises(ConstraintExecutionError, match="schema_version|hybrid identity"):
        DecisionReport.from_dict(payload)


def test_semantic_null_and_governing_fields_fail_closed():
    off = evaluate(CLEAN_EVAL)
    payload = off.to_dict()
    payload["semantic"] = None
    with pytest.raises(ConstraintExecutionError, match="hybrid identity"):
        DecisionReport.from_dict(payload)
    with pytest.raises(HybridExecutionAbort, match="null"):
        parse_decision_report_document(payload)
    with pytest.raises(TypeError):
        SemanticDocument(  # type: ignore[call-arg]
            block_kind="success",
            status="ok",
            observation_prompt_sha256=PROMPT_SHA256,
            registry_sha256=REGISTRY_SHA256,
            policy_map_sha256=POLICY_MAP_SHA256,
            score_maps=_score_maps(),
            findings=(),
            claim_fingerprints=(),
            provenance=bundle_claims((collect_configured("x"),)),
            decision="accept",
        )
    raw_020 = serialize_decision_report_document(
        HybridReportDocument(
            schema_version=REPORT_SCHEMA_VERSION_0_2_0,
            off_report=off,
            semantic=_semantic_success(),
        )
    )
    raw_020["semantic"] = None
    with pytest.raises(HybridExecutionAbort, match="null"):
        parse_decision_report_document(raw_020)


def test_product_paths_do_not_emit_hybrid_reports_or_set_ever_on():
    report = evaluate(CLEAN_EVAL)
    loop = run(CLEAN_RUN)
    session = ConstrainedSession(provider=HeuristicMockProvider(), persist=False)
    turn = session.complete(CLEAN_RUN)
    for payload in (report.to_dict(), loop.to_dict(), turn.report.to_dict(), session.snapshot().to_dict()):
        assert payload["schema_version"] in {"0.1.0", "0.1.1"}
        assert "semantic" not in payload
        assert payload.get("ever_on") is None
    assert session.snapshot().schema_version == "0.1.1"
