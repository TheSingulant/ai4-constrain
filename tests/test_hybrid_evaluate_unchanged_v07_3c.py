"""V07-3C: evaluate() remains deterministic and non-hybrid.

Synthetic fixtures only. No frozen Beta prompts. No live/paid providers.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from ai4.constrain.api import evaluate as evaluate_fn
from ai4.constrain.api import run as run_fn
from ai4.constrain import evaluate, run
from ai4.constrain.semantic_findings import SEMANTIC_EXAMINER_OPERATIONAL

CLEAN_EVAL = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
CLEAN_RUN = "Please give a brief, checkable outline of options and limits."


def test_evaluate_source_has_no_governing_integration():
    source = inspect.getsource(evaluate_fn)
    assert "execute_configured" not in source
    assert "semantic" not in source.lower()
    assert "observe_semantic_candidate" not in source
    assert "map_and_fuse_v2" not in source
    assert "_v07_3c" not in source
    params = tuple(inspect.signature(evaluate_fn).parameters)
    assert params == (
        "text",
        "prompt",
        "evaluator",
        "rubric_set",
        "prompt_specified_shards",
        "prompt_id",
        "max_revision_rounds",
        "redact",
    )


def test_evaluate_behavior_unchanged_and_non_hybrid():
    report = evaluate(CLEAN_EVAL)
    payload = report.to_dict()
    assert report.decision == "accept"
    assert report.mode == "evaluate_only"
    assert report.outcome_kind == "constraint"
    assert report.telemetry.calls == 0
    assert report.schema_version == "0.1.0"
    assert "semantic" not in payload
    assert report.terminal is None
    assert SEMANTIC_EXAMINER_OPERATIONAL is False


def test_evaluate_custom_evaluator_cannot_install():
    from src.shards.shard_evaluator import ShardEvaluator

    class _Custom:
        backend_id = "custom-3c-eval-probe"
        version = "0.0-test"

        def evaluate(self, text: str):
            return ShardEvaluator().evaluate(text)

    report = evaluate(CLEAN_EVAL, evaluator=_Custom())
    assert report.schema_version == "0.1.0"
    assert "semantic" not in report.to_dict()
    assert report.evaluator.evaluator_id == "custom-3c-eval-probe"
    assert inspect.getsource(evaluate_fn).count("execute_configured") == 0


def test_default_run_remains_off_byte_compatible():
    source = inspect.getsource(run_fn)
    assert "hybrid" not in source.lower()
    assert "observe_semantic_candidate" not in source
    assert "ever_on" not in source
    report = run(CLEAN_RUN)
    payload = report.to_dict()
    assert report.schema_version == "0.1.0"
    assert report.decision == "accept"
    assert "semantic" not in payload
    assert payload["versions"]["condition"] == "D"


def test_evaluate_module_file_has_no_v07_3c_import():
    text = Path("ai4/constrain/api.py").read_text(encoding="utf-8")
    evaluate_src = inspect.getsource(evaluate_fn)
    assert "_v07_3c" not in evaluate_src
    assert "GoverningIntegration" not in evaluate_src
