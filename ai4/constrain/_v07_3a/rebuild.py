"""rebuild_fused_evaluation (V07-3A §2).

Internal helper: replace deterministic shard scores with fused scores.
This does not re-evaluate ``passed`` against packaged thresholds (that
wall step is deferred to a later slice) and does not treat leftover
deterministic notes/results as governing semantic evidence.

Not imported by ``api.run`` / ``api.evaluate`` / ConstraintMiddleware.
"""

from __future__ import annotations

import math
from typing import Any

from src.shards.models import Evaluation, ShardScore
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain._v07_3a._common import reject_authority_kwargs
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain.semantic_fuse import PackagedFuseResult

# Product-owned rubric identity copied from the deterministic Evaluation.
# Score is replaced. passed/notes/results are discarded, not reused as
# semantic evidence and not recomputed by the evaluator wall.
APPROVED_DETERMINISTIC_SHARD_METADATA = frozenset(
    {
        "shard_id",
        "version",
        "kind",
        "priority",
        "threshold",
    }
)

_DISCARDED_DETERMINISTIC_FIELDS = frozenset({"passed", "score", "notes", "results"})


def _finite_score(raw: object, *, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HybridExecutionAbort("fuse_failure", f"{field} must be a finite number")
    number = float(raw)
    if not math.isfinite(number):
        raise HybridExecutionAbort("fuse_failure", f"{field} is not finite")
    return number


def _score_map_from_eval(evaluation: Evaluation) -> dict[str, float]:
    present = [item.shard_id for item in evaluation.shard_scores]
    unique = set(present)
    extra = sorted(unique - set(REQUIRED_IDS))
    missing = [shard_id for shard_id in REQUIRED_IDS if shard_id not in unique]
    if extra or missing or len(present) != len(REQUIRED_IDS) or len(unique) != len(REQUIRED_IDS):
        raise HybridExecutionAbort(
            "schema_invalid",
            f"det_eval shard set mismatch; missing={missing}, extra={extra}",
        )
    out: dict[str, float] = {}
    by_id: dict[str, ShardScore] = {}
    for item in evaluation.shard_scores:
        if not isinstance(item, ShardScore):
            raise HybridExecutionAbort("schema_invalid", "det_eval entries must be ShardScore")
        by_id[item.shard_id] = item
        out[item.shard_id] = _finite_score(item.score, field=f"det_eval.{item.shard_id}.score")
    return out


def _score_map_from_pairs(pairs: object, *, label: str) -> dict[str, float]:
    if not isinstance(pairs, tuple):
        raise HybridExecutionAbort("schema_invalid", f"{label} must be a tuple of pairs")
    out: dict[str, float] = {}
    for item in pairs:
        if not isinstance(item, tuple) or len(item) != 2:
            raise HybridExecutionAbort("schema_invalid", f"{label} entries must be (shard_id, score)")
        shard_id, raw = item
        if not isinstance(shard_id, str) or not shard_id:
            raise HybridExecutionAbort("schema_invalid", f"{label} shard id must be a non-empty string")
        if shard_id in out:
            raise HybridExecutionAbort("schema_invalid", f"duplicate shard {shard_id!r} in {label}")
        out[shard_id] = _finite_score(raw, field=f"{label}.{shard_id}")
    extra = sorted(set(out) - set(REQUIRED_IDS))
    missing = [shard_id for shard_id in REQUIRED_IDS if shard_id not in out]
    if extra or missing:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"{label} shard set mismatch; missing={missing}, extra={extra}",
        )
    return out


def rebuild_fused_evaluation(
    det_eval: Evaluation,
    fuse_result: PackagedFuseResult,
    **kwargs: Any,
) -> Evaluation:
    """Build an Evaluation whose scores come only from ``fuse_result``.

    Invariants
    ----------
    - Deterministic ``passed`` values are discarded (never reused).
    - Fused scores are the only replacement score source.
    - No fused score may exceed the matching deterministic score.
    - Required shard set must match exactly; extra shards fail closed.
    - NaN / Inf fail closed.
    - Only ``APPROVED_DETERMINISTIC_SHARD_METADATA`` is copied from det.
    - ``passed`` is left False; packaged wall re-evaluation of passed is
      not invoked here (later slice).
    """
    reject_authority_kwargs(kwargs, label="rebuild_fused_evaluation")
    if not isinstance(det_eval, Evaluation):
        raise HybridExecutionAbort("schema_invalid", "det_eval must be an Evaluation")
    if not isinstance(fuse_result, PackagedFuseResult):
        raise HybridExecutionAbort(
            "schema_invalid",
            "fuse_result must be a V07-1 PackagedFuseResult",
        )
    if not isinstance(det_eval.text, str):
        raise HybridExecutionAbort("schema_invalid", "det_eval.text must be a string")

    det_from_eval = _score_map_from_eval(det_eval)
    det_from_fuse = _score_map_from_pairs(fuse_result.det_scores, label="fuse_result.det_scores")
    fused = _score_map_from_pairs(fuse_result.fused_scores, label="fuse_result.fused_scores")

    for shard_id in REQUIRED_IDS:
        if det_from_fuse[shard_id] != det_from_eval[shard_id]:
            raise HybridExecutionAbort(
                "identity_drift",
                f"fuse_result.det_scores.{shard_id}={det_from_fuse[shard_id]!r} "
                f"does not match det_eval.{shard_id}={det_from_eval[shard_id]!r}",
            )
        if fused[shard_id] > det_from_eval[shard_id]:
            raise HybridExecutionAbort(
                "fuse_failure",
                f"fused.{shard_id}={fused[shard_id]} exceeds "
                f"det.{shard_id}={det_from_eval[shard_id]}",
            )
        if fused[shard_id] < 0:
            raise HybridExecutionAbort(
                "fuse_failure",
                f"fused.{shard_id}={fused[shard_id]} is negative",
            )

    by_id = {item.shard_id: item for item in det_eval.shard_scores}
    rebuilt: list[ShardScore] = []
    for shard_id in REQUIRED_IDS:
        source = by_id[shard_id]
        rebuilt.append(
            ShardScore(
                shard_id=source.shard_id,
                version=source.version,
                kind=source.kind,
                priority=source.priority,
                score=fused[shard_id],
                passed=False,
                threshold=source.threshold,
                results=(),
                notes=(),
            )
        )
    return Evaluation(
        text=det_eval.text,
        shard_scores=tuple(rebuilt),
        rubric_set_version=det_eval.rubric_set_version,
    )


__all__ = [
    "APPROVED_DETERMINISTIC_SHARD_METADATA",
    "rebuild_fused_evaluation",
]
