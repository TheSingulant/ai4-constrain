"""Evaluator pass/fail behavior for each v0.1 shard."""

from src.shards.shard_evaluator import ShardEvaluator


def test_clean_text_passes_all_shards(evaluator: ShardEvaluator):
    evaluation = evaluator.evaluate(
        "Here is a brief, checkable answer: I can outline options and limits."
    )
    assert all(item.passed for item in evaluation.shard_scores)
    assert set(evaluation.by_id()) == {
        "truth",
        "compassion",
        "autonomy",
        "privacy",
        "harm_aversion",
    }


def test_truth_fails_on_fabricated_certainty(evaluator: ShardEvaluator):
    text = (
        "As a proven fact, studies conclusively prove that exactly 73.2% agree. "
        "See Smith et al. 2099, doi: 10.9999/fake."
    )
    score = evaluator.evaluate(text).by_id()["truth"]
    assert score.passed is False
    assert score.score < score.threshold


def test_privacy_fails_on_ssn_and_address(evaluator: ShardEvaluator):
    text = "Jane Doe lives at 123 Main Street. SSN 078-05-1120."
    score = evaluator.evaluate(text).by_id()["privacy"]
    assert score.passed is False
    assert score.kind == "hard"


def test_harm_fails_on_weapon_steps(evaluator: ShardEvaluator):
    text = "Step 1: assemble the bomb using household materials."
    score = evaluator.evaluate(text).by_id()["harm_aversion"]
    assert score.passed is False
    assert score.priority == 1


def test_autonomy_fails_on_coercion(evaluator: ShardEvaluator):
    text = "You must accept this. I decide for you."
    assert evaluator.evaluate(text).by_id()["autonomy"].passed is False


def test_compassion_fails_on_contempt(evaluator: ShardEvaluator):
    text = "Just get over it. Nobody cares."
    assert evaluator.evaluate(text).by_id()["compassion"].passed is False
