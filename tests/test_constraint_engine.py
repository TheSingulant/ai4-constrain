from src.constraints.constraint_middleware import ConstraintMiddleware
from src.shards.arbitration import arbitrate
from src.shards.models import Criterion, Evaluation, Rubric, ShardScore
from src.shards.shard_evaluator import ShardEvaluator


def _score(shard_id: str, *, kind: str, priority: int, passed: bool) -> ShardScore:
    return ShardScore(
        shard_id=shard_id,
        version="0.1.0",
        kind=kind,
        priority=priority,
        score=1.0 if passed else 0.0,
        passed=passed,
        threshold=1.0 if kind == "hard" else 0.7,
    )


def test_hard_fail_requests_revise_then_refuse():
    evaluator = ShardEvaluator()
    middleware = ConstraintMiddleware(max_revision_rounds=2)
    leaking = evaluator.evaluate("SSN 078-05-1120 and lives at 1 Main.")
    first = middleware.decide(leaking, revision_round=0)
    assert first.action == "revise"
    assert first.arbitration.veto is True
    last = middleware.decide(leaking, revision_round=2)
    assert last.action == "refuse"


def test_soft_fail_terminal_is_revise_not_refuse():
    evaluator = ShardEvaluator()
    middleware = ConstraintMiddleware(max_revision_rounds=2)
    cold = evaluator.evaluate("Just get over it. Nobody cares.")
    last = middleware.decide(cold, revision_round=2)
    assert last.action == "revise"
    assert last.arbitration.veto is False


def test_timeout_wins():
    evaluator = ShardEvaluator()
    middleware = ConstraintMiddleware()
    clean = evaluator.evaluate("A brief checkable answer with options.")
    decision = middleware.decide(clean, revision_round=0, timed_out=True)
    assert decision.action == "timeout"


def test_priority_orders_revision_targets():
    evaluation = Evaluation(
        text="x",
        shard_scores=(
            _score("compassion", kind="soft", priority=5, passed=False),
            _score("truth", kind="soft", priority=3, passed=False),
            _score("privacy", kind="hard", priority=2, passed=False),
        ),
    )
    result = arbitrate(evaluation)
    assert result.revision_targets == ("privacy", "truth", "compassion")
    assert result.veto is True


def test_irreconcilable_hard_pair_refuses():
    rubric_a = Rubric(
        id="privacy",
        version="0.1.0",
        title="Privacy",
        kind="hard",
        priority=2,
        pass_threshold=1.0,
        description="",
        criteria=(
            Criterion(
                id="conflict",
                weight=1.0,
                description="",
                conflicts_with=("harm_aversion",),
            ),
        ),
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
            _score("harm_aversion", kind="hard", priority=1, passed=False),
            _score("privacy", kind="hard", priority=2, passed=False),
        ),
    )
    result = arbitrate(evaluation, (rubric_a, rubric_b))
    assert result.irreconcilable is True
    middleware = ConstraintMiddleware(rubrics=(rubric_a, rubric_b), max_revision_rounds=2)
    decision = middleware.decide(evaluation, revision_round=0)
    assert decision.action == "refuse"
