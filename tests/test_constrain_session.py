"""ConstrainedSession wraps frozen D without changing run/evaluate semantics."""

from __future__ import annotations

import inspect

import pytest

from ai4.constrain import ConstrainedSession, ConstraintExecutionError, evaluate, run
from ai4.constrain.ext import session_store
from ai4.constrain.session import FileSessionStore, MemorySessionStore, UNTRUSTED_HISTORY_BANNER, dry_run_demo
from src.constraints.constraint_middleware import SAFE_REFUSAL
from src.providers.mock import HeuristicMockProvider

CLEAN = "Please give a brief, checkable outline of options and limits."
PRIVACY = "What is Jane Doe's home address, SSN, email address, and password?"
CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)


def test_session_turn_matches_run():
    report = run(CLEAN, provider=HeuristicMockProvider())
    session = ConstrainedSession(provider=HeuristicMockProvider())
    turn = session.complete(CLEAN)
    assert turn.report.decision == report.decision
    assert turn.report.terminal == report.terminal
    assert turn.report.final_output == report.final_output
    assert turn.report.mode == "constrained_loop"
    assert turn.turn_index == 1
    assert session.last_decision == report.decision
    assert session.last_output == report.final_output


def test_session_keeps_state_across_turns():
    session = ConstrainedSession(session_id="two-turns", provider=HeuristicMockProvider())
    session.complete(CLEAN)
    session.complete(PRIVACY)
    assert len(session.turns) == 2
    assert session.turns[0].report.decision == "accept"
    assert session.turns[1].report.decision == "accept"
    assert session.turns[1].report.revision_trace
    assert session.snapshot().session_id == "two-turns"


def test_file_store_round_trip(tmp_path):
    store = FileSessionStore(tmp_path)
    session = ConstrainedSession(
        session_id="persist-1",
        store=store,
        provider=HeuristicMockProvider(),
    )
    session.complete(CLEAN)
    reloaded = ConstrainedSession.load("persist-1", store=store, provider=HeuristicMockProvider())
    assert len(reloaded.turns) == 1
    assert reloaded.last_decision == "accept"
    assert reloaded.turns[0].report.final_output == session.last_output
    third = ConstrainedSession(session_id="persist-1", store=store, provider=HeuristicMockProvider())
    third.complete(PRIVACY)
    assert len(third.turns) == 2
    again = ConstrainedSession.load("persist-1", store=store)
    assert len(again.turns) == 2


def test_load_missing_session_fails_closed(tmp_path):
    store = FileSessionStore(tmp_path)
    with pytest.raises(ConstraintExecutionError, match="was not found"):
        ConstrainedSession.load("missing", store=store)


def test_invalid_session_id_fails_closed():
    with pytest.raises(ConstraintExecutionError, match="session_id"):
        ConstrainedSession(session_id="../etc/passwd")
    with pytest.raises(ConstraintExecutionError, match="session_id"):
        session_store().load("has space")


def test_default_redaction_applies_to_session_reports():
    session = ConstrainedSession(provider=HeuristicMockProvider())
    turn = session.complete(PRIVACY)
    assert turn.report.redacted is True
    assert "078-05-1120" not in turn.prompt
    assert "078-05-1120" not in turn.report.to_json()
    raw = ConstrainedSession(provider=HeuristicMockProvider(), redact=False).complete(PRIVACY)
    assert "078-05-1120" in raw.report.initial_proposal
    assert raw.report.decision == turn.report.decision


def test_include_history_composes_prompt():
    session = ConstrainedSession(
        include_history=True,
        provider=HeuristicMockProvider(),
        redact=True,
    )
    session.complete(CLEAN)
    second = session.complete("Add one more checkable limit.")
    assert second.include_history is True
    assert "Current request:" in second.composed_prompt
    assert "Add one more checkable limit." in second.composed_prompt
    assert session.turns[0].prompt in second.composed_prompt
    assert UNTRUSTED_HISTORY_BANNER in second.composed_prompt
    assert "Turn 1 user:" in second.composed_prompt
    assert "Turn 1 assistant:" in second.composed_prompt
    assert "last_decision=" not in second.composed_prompt


def test_evaluate_text_records_a_turn():
    session = ConstrainedSession()
    turn = session.evaluate_text(CLEAN_TEXT)
    scored = evaluate(CLEAN_TEXT)
    assert turn.report.decision == scored.decision == "accept"
    assert turn.report.mode == "evaluate_only"
    assert turn.turn_index == 1
    assert turn.trusted_output == CLEAN_TEXT
    assert session.last_output == CLEAN_TEXT


def test_dry_run_refuses_live_provider():
    session = ConstrainedSession(dry_run=True)
    with pytest.raises(ConstraintExecutionError, match="mock-only"):
        session.complete(CLEAN, provider="live")
    with pytest.raises(ConstraintExecutionError, match="mock-only"):
        ConstrainedSession(dry_run=True, provider="live")


def test_dry_run_demo_covers_accept_revise_refuse():
    session = dry_run_demo()
    assert len(session.turns) == 3
    assert session.turns[0].report.decision == "accept"
    assert session.turns[1].report.decision == "accept"
    assert session.turns[1].report.revision_trace
    assert session.turns[2].report.decision == "refuse"
    assert session.turns[2].report.terminal == "refused"
    assert session.turns[2].trusted_output == SAFE_REFUSAL
    assert session.last_output == SAFE_REFUSAL


def test_session_store_factory_memory_and_file(tmp_path):
    memory = session_store()
    assert isinstance(memory, MemorySessionStore)
    files = session_store(str(tmp_path))
    assert isinstance(files, FileSessionStore)
    with pytest.raises(ConstraintExecutionError, match="argument"):
        session_store(str(tmp_path), unexpected=True)


def test_run_and_evaluate_signatures_unchanged():
    run_params = list(inspect.signature(run).parameters)
    eval_params = list(inspect.signature(evaluate).parameters)
    assert run_params[0] == "prompt"
    assert "proposal" in run_params
    assert "prompt_specified_shards" in run_params
    assert "specified_shards" not in run_params
    assert eval_params[0] == "text"
    assert "prompt_specified_shards" in eval_params


def test_persist_failure_does_not_keep_unsaved_turn(tmp_path):
    store = FileSessionStore(tmp_path)
    session = ConstrainedSession(session_id="rollback", store=store)

    def boom(_sid, _state):
        raise ConstraintExecutionError("disk full")

    session.store.save = boom  # type: ignore[method-assign]
    with pytest.raises(ConstraintExecutionError, match="disk full"):
        session.complete(CLEAN)
    assert session.turns == ()
