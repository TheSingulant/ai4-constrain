"""Deterministic shard disagreement rules for v0.1.

Rule (frozen with the protocol):
1. Evaluate each shard independently.
2. Hard shards (harm_aversion, then privacy) veto: any hard fail means the
   candidate cannot be accepted.
3. Soft shards (truth, autonomy, compassion) request revision only.
4. Revision targets are failing shards sorted by priority (lower number first).
5. If two hard shards fail and any failed criterion lists the other shard in
   conflicts_with, mark irreconcilable and refuse without more model calls.
6. Soft-vs-soft conflict is resolved by priority order in the revision list;
   we do not invent a numeric blend.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.shards.models import ArbitrationResult, Evaluation, Rubric, ShardScore


def _conflict_pairs(rubrics: Sequence[Rubric]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for rubric in rubrics:
        for criterion in rubric.criteria:
            for other in criterion.conflicts_with:
                pairs.add(tuple(sorted((rubric.id, other))))
    return pairs


def arbitrate(
    evaluation: Evaluation,
    rubrics: Sequence[Rubric] | None = None,
) -> ArbitrationResult:
    scores: tuple[ShardScore, ...] = evaluation.shard_scores
    failing = sorted((item for item in scores if not item.passed), key=lambda s: (s.priority, s.shard_id))
    hard_failing = [item for item in failing if item.kind == "hard"]
    targets = tuple(item.shard_id for item in failing)
    notes: list[str] = []

    irreconcilable = False
    if len(hard_failing) >= 2 and rubrics:
        failed_ids = {item.shard_id for item in hard_failing}
        for left, right in _conflict_pairs(rubrics):
            if left in failed_ids and right in failed_ids:
                irreconcilable = True
                notes.append(f"irreconcilable hard pair: {left} vs {right}")

    if not failing:
        return ArbitrationResult(
            verdict="pass",
            veto=False,
            irreconcilable=False,
            revision_targets=(),
            notes=("all shards passed",),
            scores=scores,
        )

    if hard_failing:
        notes.append("hard veto: " + ", ".join(item.shard_id for item in hard_failing))
        return ArbitrationResult(
            verdict="fail",
            veto=True,
            irreconcilable=irreconcilable,
            revision_targets=targets,
            notes=tuple(notes),
            scores=scores,
        )

    notes.append("soft fails: " + ", ".join(targets))
    return ArbitrationResult(
        verdict="fail",
        veto=False,
        irreconcilable=False,
        revision_targets=targets,
        notes=tuple(notes),
        scores=scores,
    )
