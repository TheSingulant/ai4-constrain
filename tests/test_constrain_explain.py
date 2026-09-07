"""Shard-card / --explain projection of DecisionReport."""

from __future__ import annotations

from ai4.constrain import evaluate, format_explain, run, shard_card
from ai4.constrain.explain import SHARD_CARD_SCHEMA, ShardCard

CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
LEAKING = "Jane Doe lives at 123 Main Street. SSN 078-05-1120."
CLEAN = "Please give a brief, checkable outline of options and limits."


def test_shard_card_from_evaluate_accept():
    report = evaluate(CLEAN_TEXT)
    card = shard_card(report)
    assert card.schema == SHARD_CARD_SCHEMA
    assert card.decision == "accept"
    assert card.terminal is None
    assert card.candidate_evaluated is True
    assert [item.shard_id for item in card.shards] == [
        "truth",
        "compassion",
        "autonomy",
        "privacy",
        "harm_aversion",
    ]
    assert all(item.passed for item in card.shards)
    round_trip = ShardCard.from_dict(card.to_dict())
    assert round_trip == card


def test_shard_card_privacy_fail_is_redacted_by_default():
    report = evaluate(LEAKING)
    card = shard_card(report)
    assert card.decision == "revise"
    assert card.veto is True
    privacy = next(item for item in card.shards if item.shard_id == "privacy")
    assert privacy.passed is False
    dumped = str(card.to_dict())
    assert "078-05-1120" not in dumped
    text = format_explain(report)
    assert "privacy" in text
    assert "decision: revise" in text
    assert "078-05-1120" not in text


def test_explain_timeout_has_no_shards():
    report = run(CLEAN, timeout_s=0)
    text = format_explain(report)
    assert "candidate not evaluated" in text
    assert report.decision is None
    card = shard_card(report)
    assert card.shards == ()
    assert card.candidate_evaluated is False
