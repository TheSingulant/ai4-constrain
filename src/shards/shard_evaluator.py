"""Deterministic per-shard evaluator driven by rubric criteria."""

from __future__ import annotations

import re
from collections.abc import Sequence

from src.shards.models import CriterionResult, Evaluation, Rubric, ShardScore
from src.shards.shard_loader import load_rubrics


class ShardEvaluator:
    """Score text against loaded rubrics. No model calls."""

    def __init__(self, rubrics: Sequence[Rubric] | None = None) -> None:
        self.rubrics = tuple(rubrics) if rubrics is not None else load_rubrics()

    def evaluate(self, text: str) -> Evaluation:
        scores = tuple(self._score_rubric(text, rubric) for rubric in self.rubrics)
        return Evaluation(text=text, shard_scores=scores)

    def _score_rubric(self, text: str, rubric: Rubric) -> ShardScore:
        results: list[CriterionResult] = []
        score = 1.0
        notes: list[str] = []
        for criterion in rubric.criteria:
            passed, evidence = self._run_criterion(text, criterion.fail_if_regex, criterion.pass_if_regex)
            criterion_score = 1.0 if passed else 0.0
            if not passed:
                score -= criterion.weight
                notes.append(f"{criterion.id}: {evidence or criterion.description}")
            results.append(
                CriterionResult(
                    criterion_id=criterion.id,
                    passed=passed,
                    score=criterion_score,
                    evidence=evidence,
                )
            )
        score = max(0.0, min(1.0, score))
        return ShardScore(
            shard_id=rubric.id,
            version=rubric.version,
            kind=rubric.kind,
            priority=rubric.priority,
            score=round(score, 4),
            passed=score + 1e-9 >= rubric.pass_threshold,
            threshold=rubric.pass_threshold,
            results=tuple(results),
            notes=tuple(notes),
        )

    @staticmethod
    def _run_criterion(
        text: str,
        fail_if_regex: Sequence[str],
        pass_if_regex: Sequence[str],
    ) -> tuple[bool, str]:
        for pattern in fail_if_regex:
            match = re.search(pattern, text)
            if match:
                return False, f"matched {pattern!r} at {match.group(0)!r}"
        if pass_if_regex:
            for pattern in pass_if_regex:
                if re.search(pattern, text):
                    return True, f"matched required {pattern!r}"
            return False, "required positive pattern missing"
        return True, ""


# Re-export for callers that import from this module.
__all__ = ["Evaluation", "ShardEvaluator", "ShardScore"]
