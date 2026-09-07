"""DecisionReport serialization and arbitration projection."""

from __future__ import annotations

import json

import pytest

from ai4.constrain import ConstraintExecutionError, DecisionReport, evaluate, run
from ai4.constrain.ext import FrozenV01RegexEvaluator
from ai4.constrain.report import (
    ArbitrationRecord,
    ShardEvaluationRecord,
    arbitration_record,
    shard_records,
)
from src.protocol_labels import FROZEN_TERMINAL_LABELS
from src.shards.arbitration import arbitrate
from src.shards.models import Criterion, Evaluation, Rubric, ShardScore

CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)


def test_evaluate_round_trip_json():
    report = evaluate(CLEAN_TEXT, prompt="check this", prompt_id="t1")
    restored = DecisionReport.from_json(report.to_json())
    assert restored == report
    payload = json.loads(report.to_json())
    assert payload["schema_version"] == "0.1.0"
    assert payload["decision"] == "accept"
    assert payload["outcome_kind"] == "constraint"
    assert payload["terminal"] is None
    assert "versions" in payload
    assert payload["versions"]["runtime_version"] == "0.1.0"
    assert payload["arbitration"]["verdict"] == "pass"
    assert payload["versions"]["evidence_class"] == "null_retained_D_adds_cost"


def test_run_round_trip_after_revision():
    report = run(
        "What is Jane Doe's home address, SSN, email address, and password?",
        redact=False,
    )
    restored = DecisionReport.from_dict(json.loads(report.to_json()))
    assert restored.decision == report.decision
    assert restored.revision_trace == report.revision_trace
    assert restored.final_output == report.final_output
    assert restored.telemetry.calls == report.telemetry.calls
    assert restored.terminal in FROZEN_TERMINAL_LABELS


def test_from_json_malformed_fails_closed():
    with pytest.raises(ConstraintExecutionError, match="Malformed"):
        DecisionReport.from_json("{")
    with pytest.raises(ConstraintExecutionError, match="must be a JSON object"):
        DecisionReport.from_dict([])
    with pytest.raises(ConstraintExecutionError, match="missing keys"):
        DecisionReport.from_dict({"schema_version": "0.1.0"})
    with pytest.raises(ConstraintExecutionError, match="Unsupported"):
        DecisionReport.from_dict(
            {
                "schema_version": "9.9.9",
                "mode": "evaluate_only",
                "outcome_kind": "constraint",
                "prompt": "",
                "initial_proposal": "",
                "shard_evaluations": [],
                "arbitration": {
                    "verdict": "pass",
                    "veto": False,
                    "irreconcilable": False,
                    "revision_targets": [],
                    "notes": [],
                },
                "decision": "accept",
                "terminal": None,
                "decision_reason": "",
                "revision_trace": [],
                "final_output": "",
                "telemetry": {},
                "versions": {},
            }
        )
    with pytest.raises(ConstraintExecutionError, match="Unknown frozen terminal"):
        DecisionReport.from_dict(
            {
                "schema_version": "0.1.0",
                "mode": "evaluate_only",
                "outcome_kind": "constraint",
                "prompt": "",
                "initial_proposal": "",
                "shard_evaluations": [],
                "arbitration": {
                    "verdict": "pass",
                    "veto": False,
                    "irreconcilable": False,
                    "revision_targets": [],
                    "notes": [],
                },
                "decision": "accept",
                "terminal": "revision_requested",
                "decision_reason": "",
                "revision_trace": [],
                "final_output": "",
                "telemetry": {},
                "versions": {},
            }
        )


def test_serialized_report_has_no_secret_fields():
    report = evaluate(CLEAN_TEXT)
    raw = report.to_json().lower()
    for banned in ("api_key", "authorization", "sk-live", "sk-proj", "begin rsa"):
        assert banned not in raw
    payload = report.to_dict()
    assert "metadata" not in payload["telemetry"]


def test_arbitration_record_preserves_irreconcilable():
    def score(shard_id: str, *, kind: str, priority: int, passed: bool) -> ShardScore:
        return ShardScore(
            shard_id=shard_id,
            version="0.1.0",
            kind=kind,
            priority=priority,
            score=1.0 if passed else 0.0,
            passed=passed,
            threshold=1.0,
        )

    rubric_a = Rubric(
        id="privacy",
        version="0.1.0",
        title="Privacy",
        kind="hard",
        priority=2,
        pass_threshold=1.0,
        description="",
        criteria=(Criterion(id="conflict", weight=1.0, description="", conflicts_with=("harm_aversion",)),),
    )
    rubric_b = Rubric(
        id="harm_aversion",
        version="0.1.0",
        title="Harm",
        kind="hard",
        priority=1,
        pass_threshold=1.0,
        description="",
        criteria=(Criterion(id="other", weight=1.0, description=""),),
    )
    evaluation = Evaluation(
        text="x",
        shard_scores=(
            score("harm_aversion", kind="hard", priority=1, passed=False),
            score("privacy", kind="hard", priority=2, passed=False),
        ),
    )
    result = arbitrate(evaluation, (rubric_a, rubric_b))
    record = arbitration_record(result)
    assert isinstance(record, ArbitrationRecord)
    assert record.irreconcilable is True
    assert record.veto is True
    assert record.verdict == "fail"


def test_shard_records_include_verdicts_and_criteria():
    evaluation = FrozenV01RegexEvaluator().evaluate("Jane Doe lives at 123 Main. SSN 078-05-1120.")
    records = shard_records(evaluation)
    privacy = next(item for item in records if item.shard_id == "privacy")
    assert isinstance(privacy, ShardEvaluationRecord)
    assert privacy.verdict == "fail"
    assert privacy.enforced is True
    assert privacy.applicable is True
    assert privacy.criteria
    assert any(not item.passed for item in privacy.criteria)
