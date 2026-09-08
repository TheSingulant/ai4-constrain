"""Evaluator policy wall: judges score; they do not define policy.

Option A (PR-D): evaluator implementations may be substituted behind one
frozen v0.1 scoring/control contract. Packaged rubrics, REQUIRED_IDS,
kinds, priorities, thresholds, conflicts, pass/fail derivation,
arbitration, D bounds, and refusal semantics stay product-owned.

Evaluators may return a complete finite [0, 1] score per required shard
plus untrusted notes/evidence. They cannot set version, kind, priority,
threshold, passed, conflict sets, or the shard set.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from src.shards.models import Evaluation, Rubric, ShardScore
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.rubrics import load_packaged_rubrics

# Same epsilon the frozen regex evaluator uses when deriving passed.
_PASS_EPSILON = 1e-9


def packaged_policy_rubrics() -> tuple[Rubric, ...]:
    """Load the frozen packaged v0.1 rubrics. Never evaluator.rubrics."""
    return load_packaged_rubrics()


def _finite_unit_interval(value: object, *, shard_id: str) -> float:
    """Accept only a finite real in [0, 1]. Bool is not a score."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConstraintExecutionError(
            f"Evaluator score for {shard_id!r} must be a finite real in [0, 1]; "
            f"got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ConstraintExecutionError(
            f"Evaluator score for {shard_id!r} must be a finite real in [0, 1]; "
            f"got {number!r}"
        )
    if number < 0.0 or number > 1.0:
        raise ConstraintExecutionError(
            f"Evaluator score for {shard_id!r} is outside [0, 1]: {number!r}"
        )
    return number


def _policy_signature(rubric: Rubric) -> tuple[object, ...]:
    conflicts = frozenset(
        str(other) for criterion in rubric.criteria for other in criterion.conflicts_with
    )
    return (
        str(rubric.id),
        str(rubric.version),
        str(rubric.kind),
        int(rubric.priority),
        float(rubric.pass_threshold),
        conflicts,
    )


def assert_rubrics_match_packaged(
    rubrics: Sequence[Rubric],
    packaged: Sequence[Rubric] | None = None,
) -> None:
    """Fail closed when exposed .rubrics disagree with packaged policy."""
    policy = tuple(packaged) if packaged is not None else packaged_policy_rubrics()
    exposed = tuple(rubrics)
    ids = [str(item.id) for item in exposed]
    if sorted(ids) != sorted(REQUIRED_IDS) or len(ids) != len(REQUIRED_IDS):
        extra = sorted(set(ids) - set(REQUIRED_IDS))
        missing = [item for item in REQUIRED_IDS if item not in set(ids)]
        raise ConstraintExecutionError(
            "Evaluator.rubrics is inconsistent with packaged v0.1 policy "
            f"(missing={missing}, extra={extra}, duplicates={len(ids) != len(set(ids))})"
        )
    by_id = {str(item.id): item for item in exposed}
    for rubric in policy:
        got = by_id[rubric.id]
        if _policy_signature(got) != _policy_signature(rubric):
            raise ConstraintExecutionError(
                f"Evaluator.rubrics for {rubric.id!r} disagrees with packaged "
                "v0.1 version/kind/priority/threshold/conflicts; refusing"
            )


def assert_evaluator_rubrics(evaluator: object, packaged: Sequence[Rubric] | None = None) -> None:
    """``.rubrics`` is unnecessary. If present, it must match packaged policy."""
    if not hasattr(evaluator, "rubrics"):
        return
    rubrics = getattr(evaluator, "rubrics")
    if rubrics is None:
        return
    if not isinstance(rubrics, (tuple, list)):
        raise ConstraintExecutionError(
            "Evaluator.rubrics must be a sequence of packaged-compatible rubrics "
            "or omitted"
        )
    if not rubrics:
        return
    assert_rubrics_match_packaged(rubrics, packaged)


def overlay_packaged_policy(
    evaluation: Evaluation,
    packaged: Sequence[Rubric] | None = None,
) -> Evaluation:
    """Overwrite policy fields and recompute passed before arbitration.

    Missing, extra, or duplicate shards fail closed. Score is validated
    as a finite [0, 1] real. version/kind/priority/threshold come from
    packaged rubrics. ``passed`` is derived from score vs the frozen
    threshold. Notes and criterion evidence are untrusted revision-feedback
    and report text, not policy authority.
    """
    if evaluation is None:
        raise ConstraintExecutionError("Required evaluator returned no evaluation")
    if not isinstance(evaluation, Evaluation):
        raise ConstraintExecutionError("Evaluator must return an Evaluation")
    policy = tuple(packaged) if packaged is not None else packaged_policy_rubrics()
    scores = evaluation.shard_scores
    if not isinstance(scores, tuple):
        raise ConstraintExecutionError("Evaluation.shard_scores must be a tuple")
    ids: list[str] = []
    by_id: dict[str, ShardScore] = {}
    for item in scores:
        if not isinstance(item, ShardScore):
            raise ConstraintExecutionError(
                f"Evaluator returned a non-ShardScore entry: {type(item).__name__}"
            )
        shard_id = str(item.shard_id)
        ids.append(shard_id)
        if shard_id in by_id:
            raise ConstraintExecutionError(
                f"Evaluator returned duplicate shard {shard_id!r}; refusing"
            )
        by_id[shard_id] = item
    extra = sorted(set(ids) - set(REQUIRED_IDS))
    missing = [item for item in REQUIRED_IDS if item not in by_id]
    if extra or missing or len(ids) != len(REQUIRED_IDS) or len(by_id) != len(REQUIRED_IDS):
        raise ConstraintExecutionError(
            "Evaluator must score exactly the required v0.1 shards; "
            f"missing={missing}, extra={extra}"
        )
    overlaid: list[ShardScore] = []
    for rubric in policy:
        raw = by_id[rubric.id]
        score = _finite_unit_interval(raw.score, shard_id=rubric.id)
        passed = score + _PASS_EPSILON >= rubric.pass_threshold
        overlaid.append(
            ShardScore(
                shard_id=rubric.id,
                version=str(rubric.version),
                kind=str(rubric.kind),
                priority=int(rubric.priority),
                score=score,
                passed=passed,
                threshold=float(rubric.pass_threshold),
                results=raw.results,
                notes=raw.notes,
            )
        )
    return Evaluation(
        text=evaluation.text,
        shard_scores=tuple(overlaid),
        rubric_set_version=evaluation.rubric_set_version,
    )


__all__ = [
    "assert_evaluator_rubrics",
    "assert_rubrics_match_packaged",
    "overlay_packaged_policy",
    "packaged_policy_rubrics",
]
