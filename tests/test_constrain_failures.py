"""Fail-closed behavior for missing/unknown/broken constraint pieces."""

from __future__ import annotations

import pytest

from ai4.constrain import ConstraintExecutionError, evaluate, run
from ai4.constrain.ext import FrozenV01RegexEvaluator, http_service, session_store
from src.shards.models import Evaluation

CLEAN = "Here is a brief, checkable answer about options."


def test_unknown_evaluator_fails_closed():
    with pytest.raises(ConstraintExecutionError, match="Unknown evaluator"):
        run(CLEAN, evaluator="llm-judge-v2")
    with pytest.raises(ConstraintExecutionError, match="Unknown evaluator"):
        evaluate(CLEAN, evaluator="not-registered")


def test_unknown_rubric_set_fails_closed():
    with pytest.raises(ConstraintExecutionError, match="rubric set"):
        run(CLEAN, rubric_set="v9.9")
    with pytest.raises(ConstraintExecutionError, match="rubric set"):
        evaluate(CLEAN, rubric_set="experimental")


def test_unknown_provider_fails_closed():
    with pytest.raises(ConstraintExecutionError, match="Unknown provider"):
        run(CLEAN, provider="unregistered-backend")


def test_unknown_specified_shard_fails_closed():
    with pytest.raises(ConstraintExecutionError, match="Unknown prompt_specified"):
        run(CLEAN, prompt_specified_shards=("loyalty",))
    with pytest.raises(ConstraintExecutionError, match="Unknown prompt_specified"):
        evaluate(CLEAN, prompt_specified_shards=("not_a_shard",))


def test_incomplete_evaluator_fails_closed():
    class Incomplete:
        backend_id = "incomplete"
        version = "0"
        rubrics = FrozenV01RegexEvaluator().rubrics

        def evaluate(self, text: str) -> Evaluation:
            return Evaluation(text=text, shard_scores=())

    with pytest.raises(ConstraintExecutionError, match="did not execute"):
        evaluate(CLEAN, evaluator=Incomplete())


def test_evaluator_exception_fails_closed():
    class Boom:
        backend_id = "boom"
        version = "0"
        rubrics = FrozenV01RegexEvaluator().rubrics

        def evaluate(self, text: str) -> Evaluation:
            raise RuntimeError("backend down")

    with pytest.raises(ConstraintExecutionError, match="failed to execute|backend down"):
        evaluate(CLEAN, evaluator=Boom())


def test_session_and_http_hooks_are_reserved():
    with pytest.raises(ConstraintExecutionError, match="later PR"):
        session_store("unused")
    with pytest.raises(ConstraintExecutionError, match="later PR"):
        http_service()


def test_run_rejects_non_string_prompt():
    with pytest.raises(ConstraintExecutionError, match="prompt"):
        run(None)  # type: ignore[arg-type]


def test_evaluator_still_loads_if_repo_rubric_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.shards.shard_loader.RUBRICS_DIR", tmp_path / "missing-rubrics")
    evaluation = FrozenV01RegexEvaluator().evaluate(CLEAN)
    assert all(item.passed for item in evaluation.shard_scores)
