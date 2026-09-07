"""Shard-card / --explain views of a DecisionReport.

This is presentation only. It does not re-score, re-arbitrate, or change
frozen v0.1 decisions. Cards are built from the report already emitted by
``run`` / ``evaluate`` / a session turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport

SHARD_CARD_SCHEMA = "ai4.shard_card.v0.1"
SHARD_ORDER = ("truth", "compassion", "autonomy", "privacy", "harm_aversion")


@dataclass(frozen=True)
class ShardCardLine:
    shard_id: str
    passed: bool
    score: float
    verdict: str
    threshold: float
    enforced: bool
    applicable: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "passed": self.passed,
            "score": self.score,
            "verdict": self.verdict,
            "threshold": self.threshold,
            "enforced": self.enforced,
            "applicable": self.applicable,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ShardCardLine:
        return cls(
            shard_id=str(raw["shard_id"]),
            passed=bool(raw["passed"]),
            score=float(raw["score"]),
            verdict=str(raw["verdict"]),
            threshold=float(raw.get("threshold") or 0.0),
            enforced=bool(raw.get("enforced", True)),
            applicable=bool(raw.get("applicable", True)),
            reasons=tuple(str(item) for item in raw.get("reasons") or ()),
        )


@dataclass(frozen=True)
class ShardCard:
    """Compact explainability record for one constrained turn."""

    schema: str
    decision: str | None
    terminal: str | None
    outcome_kind: str
    mode: str
    candidate_evaluated: bool
    revision_rounds: int
    shards: tuple[ShardCardLine, ...]
    arbitration_verdict: str | None
    veto: bool | None
    irreconcilable: bool | None
    revision_targets: tuple[str, ...]
    redacted: bool
    decision_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "decision": self.decision,
            "terminal": self.terminal,
            "outcome_kind": self.outcome_kind,
            "mode": self.mode,
            "candidate_evaluated": self.candidate_evaluated,
            "revision_rounds": self.revision_rounds,
            "shards": [item.to_dict() for item in self.shards],
            "arbitration": {
                "verdict": self.arbitration_verdict,
                "veto": self.veto,
                "irreconcilable": self.irreconcilable,
                "revision_targets": list(self.revision_targets),
            },
            "decision_reason": self.decision_reason,
            "redacted": self.redacted,
        }

    @classmethod
    def from_dict(cls, raw: object) -> ShardCard:
        if not isinstance(raw, dict):
            raise ConstraintExecutionError("ShardCard must be a JSON object")
        if raw.get("schema") != SHARD_CARD_SCHEMA:
            raise ConstraintExecutionError(f"Unknown shard-card schema {raw.get('schema')!r}")
        arb = raw.get("arbitration") or {}
        if not isinstance(arb, dict):
            raise ConstraintExecutionError("shard-card arbitration must be an object")
        shards_raw = raw.get("shards") or ()
        if not isinstance(shards_raw, list):
            raise ConstraintExecutionError("shard-card shards must be an array")
        return cls(
            schema=SHARD_CARD_SCHEMA,
            decision=None if raw.get("decision") is None else str(raw.get("decision")),
            terminal=None if raw.get("terminal") is None else str(raw.get("terminal")),
            outcome_kind=str(raw.get("outcome_kind") or ""),
            mode=str(raw.get("mode") or ""),
            candidate_evaluated=bool(raw.get("candidate_evaluated")),
            revision_rounds=int(raw.get("revision_rounds") or 0),
            shards=tuple(ShardCardLine.from_dict(item) for item in shards_raw),
            arbitration_verdict=None if arb.get("verdict") is None else str(arb.get("verdict")),
            veto=None if arb.get("veto") is None else bool(arb.get("veto")),
            irreconcilable=None if arb.get("irreconcilable") is None else bool(arb.get("irreconcilable")),
            revision_targets=tuple(str(item) for item in arb.get("revision_targets") or ()),
            redacted=bool(raw.get("redacted", True)),
            decision_reason=str(raw.get("decision_reason") or ""),
        )


def shard_card(report: DecisionReport) -> ShardCard:
    """Project a DecisionReport into a shard card. Does not re-evaluate."""
    if not isinstance(report, DecisionReport):
        raise ConstraintExecutionError("shard_card() requires a DecisionReport")
    by_id = {}
    if report.shard_evaluations is not None:
        by_id = {item.shard_id: item for item in report.shard_evaluations}
    lines: list[ShardCardLine] = []
    seen: set[str] = set()
    for shard_id in SHARD_ORDER:
        item = by_id.get(shard_id)
        if item is None:
            continue
        lines.append(
            ShardCardLine(
                shard_id=item.shard_id,
                passed=item.passed,
                score=float(item.score),
                verdict=item.verdict,
                threshold=float(item.threshold),
                enforced=item.enforced,
                applicable=item.applicable,
                reasons=tuple(item.reasons),
            )
        )
        seen.add(shard_id)
    if report.shard_evaluations is not None:
        for item in report.shard_evaluations:
            if item.shard_id in seen:
                continue
            lines.append(
                ShardCardLine(
                    shard_id=item.shard_id,
                    passed=item.passed,
                    score=float(item.score),
                    verdict=item.verdict,
                    threshold=float(item.threshold),
                    enforced=item.enforced,
                    applicable=item.applicable,
                    reasons=tuple(item.reasons),
                )
            )
    arb = report.arbitration
    return ShardCard(
        schema=SHARD_CARD_SCHEMA,
        decision=report.decision,
        terminal=report.terminal,
        outcome_kind=report.outcome_kind,
        mode=report.mode,
        candidate_evaluated=report.candidate_evaluated,
        revision_rounds=len(report.revision_trace),
        shards=tuple(lines),
        arbitration_verdict=None if arb is None else arb.verdict,
        veto=None if arb is None else arb.veto,
        irreconcilable=None if arb is None else arb.irreconcilable,
        revision_targets=() if arb is None else arb.revision_targets,
        redacted=report.redacted,
        decision_reason=report.decision_reason,
    )


def format_explain(report: DecisionReport, *, session_id: str = "", turn_index: int | None = None) -> str:
    """Human-readable --explain text for a report or session turn."""
    card = shard_card(report)
    return format_shard_card(card, session_id=session_id, turn_index=turn_index)


def format_shard_card(
    card: ShardCard,
    *,
    session_id: str = "",
    turn_index: int | None = None,
) -> str:
    header = ["shard card"]
    if session_id:
        header.append(f"session: {session_id}")
    if turn_index is not None:
        header.append(f"turn: {turn_index}")
    lines = [
        "  ".join(header),
        f"decision: {card.decision if card.decision is not None else 'null'}",
        f"terminal: {card.terminal if card.terminal is not None else 'null'}",
        f"outcome: {card.outcome_kind}",
        f"mode: {card.mode}",
        f"revisions: {card.revision_rounds}",
        f"redacted: {str(card.redacted).lower()}",
    ]
    if not card.candidate_evaluated or not card.shards:
        lines.append("shards: (none; candidate not evaluated)")
    else:
        lines.append("shards:")
        width = max((len(item.shard_id) for item in card.shards), default=8)
        for item in card.shards:
            mark = "pass" if item.passed else "fail"
            extra = "" if item.applicable else "  projected=not_applicable"
            lines.append(
                f"  {item.shard_id:<{width}}  {item.verdict:<15}  "
                f"{item.score:0.2f}  {mark}{extra}"
            )
            for reason in item.reasons:
                lines.append(f"    - {reason}")
    if card.arbitration_verdict is None:
        lines.append("arbitration: (none)")
    else:
        targets = ",".join(card.revision_targets) if card.revision_targets else "-"
        lines.append(
            f"arbitration: {card.arbitration_verdict}  "
            f"veto={str(card.veto).lower()}  "
            f"irreconcilable={str(card.irreconcilable).lower()}  "
            f"targets={targets}"
        )
    if card.decision_reason:
        lines.append(f"reason: {card.decision_reason}")
    return "\n".join(lines) + "\n"
