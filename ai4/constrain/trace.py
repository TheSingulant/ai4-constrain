"""JSONL decision traces for local product debugging.

Traces are derived from already-emitted DecisionReports / shard cards.
They do not re-run evaluators, do not enter session history, and are not
configuration. Default payloads follow report redaction.

The complete event records trusted terminal assistant text (possibly
empty), not a failing candidate as if it were conversational output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.explain import ShardCard, shard_card
from ai4.constrain.report import DecisionReport

TRACE_SCHEMA = "ai4.trace.v0.1"
TRACE_KINDS = ("session_start", "turn_start", "decision", "shard_card", "complete")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class TraceEvent:
    kind: str
    session_id: str
    turn_index: int | None
    ts: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema": TRACE_SCHEMA,
            "kind": self.kind,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "ts": self.ts,
        }
        body.update(self.payload)
        return body

    def to_jsonl(self) -> str:
        return _dump(self.to_dict())


def compact_decision_payload(report: DecisionReport) -> dict[str, Any]:
    return {
        "decision": report.decision,
        "terminal": report.terminal,
        "outcome_kind": report.outcome_kind,
        "mode": report.mode,
        "candidate_evaluated": report.candidate_evaluated,
        "revision_rounds": len(report.revision_trace),
        "redacted": report.redacted,
        "provider": report.telemetry.provider,
        "model": report.telemetry.model,
    }


def events_for_turn(
    *,
    session_id: str,
    turn_index: int,
    prompt: str,
    report: DecisionReport,
    card: ShardCard | None = None,
    ts: str | None = None,
    include_full_report: bool = False,
    trusted_output: str = "",
) -> tuple[TraceEvent, ...]:
    stamp = ts or utc_now()
    card = card if card is not None else shard_card(report)
    events = [
        TraceEvent(
            kind="turn_start",
            session_id=session_id,
            turn_index=turn_index,
            ts=stamp,
            payload={"prompt": prompt},
        ),
        TraceEvent(
            kind="decision",
            session_id=session_id,
            turn_index=turn_index,
            ts=stamp,
            payload=compact_decision_payload(report),
        ),
        TraceEvent(
            kind="shard_card",
            session_id=session_id,
            turn_index=turn_index,
            ts=stamp,
            payload={"card": card.to_dict()},
        ),
        TraceEvent(
            kind="complete",
            session_id=session_id,
            turn_index=turn_index,
            ts=stamp,
            payload={
                "text": trusted_output,
                "trusted": bool(trusted_output),
                "redacted": report.redacted,
            },
        ),
    ]
    if include_full_report:
        events.append(
            TraceEvent(
                kind="decision",
                session_id=session_id,
                turn_index=turn_index,
                ts=stamp,
                payload={"report": report.to_dict(), "full": True},
            )
        )
    return tuple(events)


class JsonlTraceWriter:
    """Append-only local JSONL diagnostic. Fail closed if the path cannot be written.

    This is not session state and is not an HTTP surface. Payloads follow
    the same redaction as the DecisionReport they were derived from.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)
        except OSError as exc:
            raise ConstraintExecutionError(f"Cannot open JSONL trace {self.path}: {exc}") from exc

    def write_event(self, event: TraceEvent) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.to_jsonl() + "\n")
                handle.flush()
        except OSError as exc:
            raise ConstraintExecutionError(f"Failed to append JSONL trace: {exc}") from exc

    def write_session_start(self, session_id: str) -> None:
        self.write_event(
            TraceEvent(
                kind="session_start",
                session_id=session_id,
                turn_index=None,
                ts=utc_now(),
                payload={},
            )
        )

    def write_turn(
        self,
        *,
        session_id: str,
        turn_index: int,
        prompt: str,
        report: DecisionReport,
        card: ShardCard | None = None,
        include_full_report: bool = False,
        trusted_output: str = "",
    ) -> None:
        for event in events_for_turn(
            session_id=session_id,
            turn_index=turn_index,
            prompt=prompt,
            report=report,
            card=card,
            include_full_report=include_full_report,
            trusted_output=trusted_output,
        ):
            self.write_event(event)

    def close(self) -> None:
        return None


def dump_jsonl_file(path: str | Path, events: list[TraceEvent]) -> None:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(event.to_jsonl() + "\n")
    except OSError as exc:
        raise ConstraintExecutionError(f"Cannot write JSONL trace {target}: {exc}") from exc


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        raise ConstraintExecutionError(f"JSONL trace not found: {target}")
    rows: list[dict[str, Any]] = []
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConstraintExecutionError(f"Cannot read JSONL trace {target}: {exc}") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConstraintExecutionError(f"Malformed JSONL trace: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConstraintExecutionError("JSONL trace row must be an object")
        rows.append(payload)
    return rows
