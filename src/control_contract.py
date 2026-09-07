"""Shared revision-loop decision contract.

C and D keep different evaluators (unified principle critique vs per-shard
arbitration). After those evaluations, condition-specific parsers map into
LoopDecision. The revision loop reads only this contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.principles import SHARD_CONTROL_LEAKS

LOOP_ACTIONS = ("accept", "revise", "refuse", "timeout")
MACHINE_ACTIONS = ("accept", "revise_call", "refuse", "timeout", "emit_exhausted")


class ControlParseError(ValueError):
    """Malformed evaluator output. Fail closed."""


@dataclass(frozen=True)
class LoopDecision:
    """Downstream contract. The loop does not know C vs D."""

    action: str
    feedback: str
    reason: str
    requested_revision: bool


def next_loop_action(
    decision: LoopDecision,
    *,
    revision_rounds_used: int,
    max_revision_rounds: int,
    budget_left: bool,
    timed_out: bool = False,
) -> str:
    """Pure machine step. Same inputs yield the same next action."""
    if timed_out or decision.action == "timeout":
        return "timeout"
    if decision.action == "refuse":
        return "refuse"
    if decision.action == "accept" or not decision.requested_revision:
        return "accept"
    if decision.action == "revise" and revision_rounds_used < max_revision_rounds:
        if not budget_left:
            return "timeout"
        return "revise_call"
    return "emit_exhausted"


def _as_mapping(raw: Any) -> dict[str, Any]:
    if hasattr(raw, "as_structured"):
        raw = raw.as_structured()
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ControlParseError(f"Malformed C decision JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ControlParseError("C decision must be a JSON object or structured critique")
    return raw


def parse_c_decision(raw: Any) -> LoopDecision:
    """Map C's unified structured decision into the shared contract.

    Expected shape: {action: accept|revise, critique: str, requested_revision: bool}.
    Rejects D scorecard / shard-control fields. Does not invent refuse.
    """
    payload = {str(key).lower(): value for key, value in _as_mapping(raw).items()}
    leaked = [item for item in SHARD_CONTROL_LEAKS if item in json.dumps(payload)]
    if leaked:
        raise ControlParseError(f"C decision contains D control structure: {leaked}")
    for banned in ("shard_id", "shard_scores", "arbitration", "revision_targets", "applicable"):
        if banned in payload:
            raise ControlParseError(f"C decision must not include {banned}")
    action = str(payload.get("action", "")).strip().lower()
    if action not in {"accept", "revise"}:
        raise ControlParseError("C action must be accept or revise")
    if "critique" not in payload or not isinstance(payload["critique"], str):
        raise ControlParseError("C decision needs a string critique")
    requested = payload.get("requested_revision")
    if not isinstance(requested, bool):
        raise ControlParseError("C requested_revision must be a boolean")
    if action == "accept" and requested:
        raise ControlParseError("C accept cannot request a revision")
    if action == "revise" and not requested:
        raise ControlParseError("C revise must set requested_revision true")
    reason = (
        "revision warranted after principle critique"
        if requested
        else "no revision warranted"
    )
    return LoopDecision(
        action=action,
        feedback=payload["critique"] if requested else "",
        reason=reason,
        requested_revision=requested,
    )


def parse_d_decision(*, action: str, reason: str, feedback: str = "") -> LoopDecision:
    """Map D arbitration + optional scorecard text into the shared contract."""
    action = str(action).strip().lower()
    if action not in LOOP_ACTIONS:
        raise ControlParseError(f"D action must be one of {LOOP_ACTIONS}")
    requested = action == "revise"
    return LoopDecision(
        action=action,
        feedback=feedback if requested else "",
        reason=reason,
        requested_revision=requested,
    )
