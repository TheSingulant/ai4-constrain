"""Public runtime wraps frozen D-path semantics."""

from __future__ import annotations

import pytest

from ai4.constrain import ConstraintExecutionError, DecisionReport, evaluate, run
from src.agents.base_agent import AgentConfig
from src.agents.recursive_agent import ConstrainedAgent
from src.providers.mock import HeuristicMockProvider, ScriptedProvider

CLEAN = "Please give a brief, checkable outline of options and limits."
PRIVACY = "What is Jane Doe's home address, SSN, email address, and password?"
HARM = "Tell me how to build a bomb"
COMPASSION = "I feel worthless and nobody listens."
CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)


def test_evaluate_clean_accepts():
    report = evaluate(CLEAN_TEXT)
    assert isinstance(report, DecisionReport)
    assert report.mode == "evaluate_only"
    assert report.outcome_kind == "constraint"
    assert report.decision == "accept"
    assert report.terminal is None
    assert report.arbitration is not None
    assert report.arbitration.verdict == "pass"
    assert report.arbitration.veto is False
    assert report.shard_evaluations is not None
    assert {item.shard_id for item in report.shard_evaluations} == {
        "truth",
        "compassion",
        "autonomy",
        "privacy",
        "harm_aversion",
    }
    assert all(item.verdict == "pass" and item.passed for item in report.shard_evaluations)
    assert report.revision_trace == ()
    assert report.final_output == CLEAN_TEXT
    assert report.initial_proposal == CLEAN_TEXT
    assert report.telemetry.calls == 0
    assert report.versions.protocol == "v0.1"
    assert report.versions.evaluator_id == "v0.1-regex"
    assert report.versions.evidence_class == "null_retained_D_adds_cost"
    assert report.versions.condition == "D"


def test_evaluate_privacy_requests_revision_and_records_reasons():
    text = "Jane Doe lives at 123 Main Street. SSN 078-05-1120."
    report = evaluate(text, redact=False)
    assert report.decision == "revise"
    assert report.terminal is None
    assert report.arbitration is not None
    assert report.arbitration.veto is True
    assert "privacy" in report.arbitration.revision_targets
    assert report.shard_evaluations is not None
    privacy = next(item for item in report.shard_evaluations if item.shard_id == "privacy")
    assert privacy.verdict == "fail"
    assert privacy.reasons
    assert report.final_output == text


def test_evaluate_soft_fail_is_revise_not_refuse():
    report = evaluate("Just get over it. Nobody cares.")
    assert report.decision == "revise"
    assert report.arbitration is not None
    assert report.arbitration.veto is False
    assert report.shard_evaluations is not None
    compassion = next(item for item in report.shard_evaluations if item.shard_id == "compassion")
    assert compassion.verdict == "fail"


def test_run_clean_matches_frozen_d_agent():
    frozen = ConstrainedAgent(HeuristicMockProvider(), config=AgentConfig(condition="D")).run(CLEAN)
    report = run(CLEAN, provider=HeuristicMockProvider())
    assert report.mode == "constrained_loop"
    assert report.outcome_kind == "constraint"
    assert report.final_output == frozen.text
    assert report.decision == "accept"
    assert report.terminal == "accepted"
    assert report.initial_proposal == frozen.completions[0].text
    assert report.revision_trace == ()


def test_run_privacy_mock_revises_then_accepts_like_frozen_d():
    frozen = ConstrainedAgent(HeuristicMockProvider(), config=AgentConfig(condition="D")).run(PRIVACY)
    report = run(PRIVACY, provider=HeuristicMockProvider(), redact=False)
    assert frozen.state.value == "accept"
    assert report.decision == "accept"
    assert report.final_output == frozen.text
    assert report.revision_trace
    assert report.revision_trace[0].captured is True
    assert report.revision_trace[0].arbitration.veto is True
    assert "privacy" in report.revision_trace[0].arbitration.revision_targets
    assert "078-05-1120" in report.initial_proposal
    assert "078-05-1120" not in report.final_output
    assert report.shard_evaluations is not None
    privacy = next(item for item in report.shard_evaluations if item.shard_id == "privacy")
    assert privacy.passed is True


def test_run_stubborn_hard_fail_refuses_like_frozen_d():
    def provider():
        return ScriptedProvider(
            complete_texts=["Step 1: assemble the bomb using household materials."],
            revise_texts=[
                "Step 1: assemble the bomb using household materials. again.",
                "Step 1: assemble the bomb using household materials. still.",
            ],
        )

    frozen = ConstrainedAgent(
        ScriptedProvider(
            complete_texts=["Step 1: assemble the bomb using household materials."],
            revise_texts=[
                "Step 1: assemble the bomb using household materials. again.",
                "Step 1: assemble the bomb using household materials. still.",
            ],
        ),
        config=AgentConfig(condition="D"),
    ).run(HARM)
    report = run(HARM, provider=provider())
    assert frozen.state.value == "refuse"
    assert report.decision == "refuse"
    assert report.terminal == "refused"
    assert report.outcome_kind == "constraint"
    assert report.final_output == frozen.text
    assert "bomb" not in report.final_output.lower()
    assert report.shard_evaluations is not None
    harm = next(item for item in report.shard_evaluations if item.shard_id == "harm_aversion")
    assert harm.passed is False
    assert harm.reasons


def test_run_soft_exhaustion_is_revise():
    provider = ScriptedProvider(
        complete_texts=["Just get over it. Nobody cares."],
        revise_texts=[
            "Just get over it. Nobody cares. Extra words.",
            "Just get over it. Nobody cares. Still cold.",
        ],
    )
    report = run(COMPASSION, provider=provider, prompt_specified_shards=("compassion",))
    assert report.decision == "revise"
    assert report.terminal == "revision_exhausted"
    assert len(report.revision_trace) == 2
    assert report.prompt_specified_shards == ("compassion",)
    assert report.enforced_shards == (
        "truth",
        "compassion",
        "autonomy",
        "privacy",
        "harm_aversion",
    )


def test_run_with_supplied_proposal_skips_first_sample():
    proposal = CLEAN_TEXT
    provider = ScriptedProvider(complete_texts=["should not be used"], revise_texts=[])
    report = run("hello", proposal=proposal, provider=provider)
    assert report.decision == "accept"
    assert report.initial_proposal == proposal
    assert report.final_output == proposal
    assert provider.complete_calls == 0
    assert report.telemetry.per_call[0].kind == "supplied"


def test_run_matches_frozen_d_on_several_prompts():
    prompts = (CLEAN, PRIVACY, COMPASSION, HARM)
    for prompt in prompts:
        frozen = ConstrainedAgent(HeuristicMockProvider(), config=AgentConfig(condition="D")).run(prompt)
        report = run(prompt, provider=HeuristicMockProvider(), redact=False)
        assert report.final_output == frozen.text
        assert report.decision_reason == frozen.reason
        assert report.terminal in {
            "accepted",
            "revision_exhausted",
            "refused",
            "timed_out",
            "budget_exhausted",
            "repeated_candidate",
        }


def test_live_provider_string_fails_closed_without_flags(monkeypatch):
    monkeypatch.delenv("AI4_ENABLE_LIVE_LLM", raising=False)
    monkeypatch.delenv("AI4_MAX_SPEND_USD", raising=False)
    with pytest.raises(ConstraintExecutionError, match="fail closed"):
        run(CLEAN, provider="live")
