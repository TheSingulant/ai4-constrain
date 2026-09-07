"""JSONL traces follow report redaction and do not re-evaluate."""

from __future__ import annotations

from ai4.constrain import ConstrainedSession
from ai4.constrain.trace import JsonlTraceWriter, read_jsonl
from src.providers.mock import HeuristicMockProvider

CLEAN = "Please give a brief, checkable outline of options and limits."
PRIVACY = "What is Jane Doe's home address, SSN, email address, and password?"


def test_jsonl_trace_records_compact_events(tmp_path):
    path = tmp_path / "trace.jsonl"
    session = ConstrainedSession(
        session_id="trace-1",
        tracer=JsonlTraceWriter(path),
        provider=HeuristicMockProvider(),
    )
    session.complete(CLEAN)
    rows = read_jsonl(path)
    kinds = [row["kind"] for row in rows]
    assert kinds[0] == "session_start"
    assert "turn_start" in kinds
    assert "decision" in kinds
    assert "shard_card" in kinds
    assert "complete" in kinds
    assert all(row["schema"] == "ai4.trace.v0.1" for row in rows)
    assert all(row["session_id"] == "trace-1" for row in rows)
    complete = next(row for row in rows if row["kind"] == "complete")
    assert complete["trusted"] is True
    assert complete["text"] == session.last_output


def test_jsonl_redacts_ssn(tmp_path):
    jsonl = tmp_path / "trace.jsonl"
    session = ConstrainedSession(
        session_id="trace-pii",
        tracer=JsonlTraceWriter(jsonl),
        provider=HeuristicMockProvider(),
        redact=True,
    )
    session.complete(PRIVACY)
    raw_jsonl = jsonl.read_text(encoding="utf-8")
    assert "078-05-1120" not in raw_jsonl
    complete = next(row for row in read_jsonl(jsonl) if row["kind"] == "complete")
    assert complete["trusted"] is True
    assert "078-05-1120" not in complete["text"]
