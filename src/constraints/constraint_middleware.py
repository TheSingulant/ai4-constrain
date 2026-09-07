"""Apply evaluator outcomes and revision bounds.

The middleware does not call a model. It only maps arbitration plus budget
into a terminal or in-loop action: accept, revise, refuse, timeout.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.shards.arbitration import ArbitrationResult, arbitrate
from src.shards.models import Evaluation, Rubric
from src.shards.shard_loader import load_rubrics


@dataclass(frozen=True)
class ConstraintDecision:
    action: str
    arbitration: ArbitrationResult
    reason: str
    revision_round: int
    max_revision_rounds: int


class ConstraintMiddleware:
    def __init__(
        self,
        *,
        rubrics: tuple[Rubric, ...] | None = None,
        max_revision_rounds: int = 2,
    ) -> None:
        self.rubrics = rubrics if rubrics is not None else load_rubrics()
        self.max_revision_rounds = max_revision_rounds

    def decide(
        self,
        evaluation: Evaluation,
        *,
        revision_round: int,
        timed_out: bool = False,
        budget_exhausted: bool = False,
    ) -> ConstraintDecision:
        arbitration = arbitrate(evaluation, self.rubrics)
        if timed_out or budget_exhausted:
            return ConstraintDecision(
                action="timeout",
                arbitration=arbitration,
                reason="timeout" if timed_out else "completion budget exhausted",
                revision_round=revision_round,
                max_revision_rounds=self.max_revision_rounds,
            )
        if arbitration.verdict == "pass":
            return ConstraintDecision(
                action="accept",
                arbitration=arbitration,
                reason="all shards passed",
                revision_round=revision_round,
                max_revision_rounds=self.max_revision_rounds,
            )
        if arbitration.irreconcilable:
            return ConstraintDecision(
                action="refuse",
                arbitration=arbitration,
                reason="irreconcilable hard shards",
                revision_round=revision_round,
                max_revision_rounds=self.max_revision_rounds,
            )
        can_revise = revision_round < self.max_revision_rounds
        if can_revise:
            return ConstraintDecision(
                action="revise",
                arbitration=arbitration,
                reason="revision requested: " + ", ".join(arbitration.revision_targets),
                revision_round=revision_round,
                max_revision_rounds=self.max_revision_rounds,
            )
        if arbitration.veto:
            return ConstraintDecision(
                action="refuse",
                arbitration=arbitration,
                reason="hard shard still failing after revision budget",
                revision_round=revision_round,
                max_revision_rounds=self.max_revision_rounds,
            )
        return ConstraintDecision(
            action="revise",
            arbitration=arbitration,
            reason="soft shard still failing; returning last revision",
            revision_round=revision_round,
            max_revision_rounds=self.max_revision_rounds,
        )

    def format_feedback(self, decision: ConstraintDecision, evaluation: Evaluation) -> str:
        lines = ["Shard scores (v0.1):"]
        for score in evaluation.shard_scores:
            mark = "PASS" if score.passed else "FAIL"
            note = "; ".join(score.notes) if score.notes else "ok"
            lines.append(f"- {score.shard_id}: {score.score:.2f} {mark} ({note})")
        targets = decision.arbitration.revision_targets
        if targets:
            lines.append("Revise to pass failing shards, in this order: " + ", ".join(targets) + ".")
        lines.append("Stay useful. Do not mention shard names to the end user.")
        return "\n".join(lines)


SAFE_REFUSAL = (
    "I cannot provide this. The request conflicts with a hard safety or privacy constraint."
)
