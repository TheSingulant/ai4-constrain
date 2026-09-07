"""Shared loop contract: C and D parsers, wording-invariant control."""

from __future__ import annotations

import json

import pytest

from src.control_contract import (
    ControlParseError,
    LoopDecision,
    next_loop_action,
    parse_c_decision,
    parse_d_decision,
)
from src.principles import PrincipleCritic


def _step(decision: LoopDecision, *, used: int = 0, max_rounds: int = 2, budget: bool = True) -> str:
    return next_loop_action(
        decision,
        revision_rounds_used=used,
        max_revision_rounds=max_rounds,
        budget_left=budget,
    )


def test_equivalent_accept_decisions_share_downstream_accept():
    c_docs = (
        {"action": "accept", "critique": "No revision is warranted.", "requested_revision": False},
        {"ACTION": "ACCEPT", "critique": "Clean draft. All five principles hold.", "requested_revision": False},
        json.dumps(
            {
                "action": "Accept",
                "critique": "The current draft is consistent with the principles together.",
                "requested_revision": False,
            }
        ),
        PrincipleCritic().critique("Here is a brief, checkable answer about options."),
    )
    d_docs = (
        parse_d_decision(action="accept", reason="all shards passed"),
        parse_d_decision(action="ACCEPT", reason="pass"),
    )
    c_parsed = [parse_c_decision(item) for item in c_docs]
    assert {item.action for item in c_parsed} == {"accept"}
    assert {_step(item) for item in [*c_parsed, *d_docs]} == {"accept"}


def test_equivalent_revise_decisions_share_downstream_revise_call():
    c_wordings = (
        {
            "action": "revise",
            "critique": "In this draft, privacy is not met because personal data appears.",
            "requested_revision": True,
        },
        {
            "action": "REVISE",
            "critique": (
                "Unified critique: privacy is not met (this draft includes "
                "'078-05-1120'). Improve the whole answer."
            ),
            "requested_revision": True,
        },
        PrincipleCritic().critique("Jane Doe lives at 123 Main. SSN 078-05-1120."),
    )
    d_wordings = (
        parse_d_decision(
            action="revise",
            reason="revision requested: privacy",
            feedback="- privacy: 0.00 FAIL (no_ssn)\nRevise to pass failing shards, in this order: privacy.",
        ),
        parse_d_decision(
            action="Revise",
            reason="revision requested: privacy, truth",
            feedback="Shard scores (v0.1):\n- privacy: 0.20 FAIL (lives at)\n- truth: 1.00 PASS (ok)",
        ),
    )
    c_parsed = [parse_c_decision(item) for item in c_wordings]
    assert {item.action for item in c_parsed} == {"revise"}
    assert {_step(item) for item in [*c_parsed, *d_wordings]} == {"revise_call"}
    assert {_step(item, used=2) for item in [*c_parsed, *d_wordings]} == {"emit_exhausted"}
    assert {_step(item, budget=False) for item in [*c_parsed, *d_wordings]} == {"timeout"}


def test_c_parser_rejects_d_scorecard_shape():
    with pytest.raises(ControlParseError, match="D control|must not include"):
        parse_c_decision(
            {
                "action": "revise",
                "critique": "x",
                "requested_revision": True,
                "shard_id": "privacy",
            }
        )
    with pytest.raises(ControlParseError, match="D control"):
        parse_c_decision(
            {
                "action": "revise",
                "critique": "Shard scores (v0.1): privacy FAIL",
                "requested_revision": True,
            }
        )


def test_c_parser_does_not_emit_refuse():
    with pytest.raises(ControlParseError, match="accept or revise"):
        parse_c_decision(
            {"action": "refuse", "critique": "hard fail", "requested_revision": False}
        )


def test_d_refuse_is_available_only_on_d_parser():
    decision = parse_d_decision(action="refuse", reason="hard shard still failing after revision budget")
    assert _step(decision, used=2) == "refuse"
    assert decision.requested_revision is False
