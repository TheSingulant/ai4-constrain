"""Independent oracles for the PR-A adversarial-review defects."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

import ai4.constrain as public
from ai4.constrain import ConstraintExecutionError, RuntimeConfig, evaluate, run
from ai4.constrain.ext import FrozenV01RegexEvaluator, PREFLIGHT_PROBE
from ai4.constrain.rubrics import packaged_rubric_bytes
from src.agents.base_agent import AgentConfig
from src.agents.recursive_agent import ConstrainedAgent
from src.protocol_labels import FROZEN_TERMINAL_LABELS, frozen_terminal_label
from src.providers.mock import HeuristicMockProvider, ScriptedProvider
from src.shards.arbitration import arbitrate
from src.shards.models import Evaluation
from src.shards.shard_loader import REQUIRED_IDS

CLEAN = "Please give a brief, checkable outline of options and limits."
CLEAN_TEXT = (
    "Here is a brief, checkable answer: I can outline options and limits, "
    "and I will mark anything I cannot verify."
)
LEAKING = "Jane Doe lives at 123 Main Street. SSN 078-05-1120."
REPO_RUBRICS = Path(__file__).resolve().parents[1] / "rubrics" / "v0.1"


def test_timeout_before_first_eval_does_not_report_all_shards_passed():
    frozen = ConstrainedAgent(
        HeuristicMockProvider(),
        config=AgentConfig(condition="D", timeout_s=0),
    ).run(CLEAN)
    assert frozen.completions == []
    assert frozen.evaluation is not None
    # Independent oracle: the frozen agent scores the empty leftover string as a pass.
    assert all(item.passed for item in frozen.evaluation.shard_scores)

    report = run(CLEAN, timeout_s=0, provider=HeuristicMockProvider())
    assert report.outcome_kind == "execution"
    assert report.decision is None
    assert report.terminal == "timed_out"
    assert report.candidate_evaluated is False
    assert report.shard_evaluations is None
    assert report.arbitration is None
    assert report.revision_trace == ()
    raw = report.to_json()
    assert "all shards passed" not in raw.lower()
    assert '"candidate_evaluated": false' in raw


def test_zero_budget_before_first_eval_is_execution_not_refuse():
    frozen = ConstrainedAgent(
        HeuristicMockProvider(),
        config=AgentConfig(condition="D", max_completions=0),
    ).run(CLEAN)
    assert frozen.completions == []
    report = run(CLEAN, max_completions=0, provider=HeuristicMockProvider())
    assert report.outcome_kind == "execution"
    assert report.decision is None
    assert report.terminal == frozen_terminal_label(frozen.state, frozen.reason)
    assert report.candidate_evaluated is False
    assert report.shard_evaluations is None
    assert report.arbitration is None
    assert report.decision != "refuse"


def test_unknown_runtime_config_ids_fail_closed():
    with pytest.raises(ConstraintExecutionError, match="Unknown evaluator"):
        run(CLEAN, config=RuntimeConfig(evaluator_id="llm-judge-v2"))
    with pytest.raises(ConstraintExecutionError, match="Unknown provider"):
        run(CLEAN, config=RuntimeConfig(provider_id="unregistered-backend"))
    with pytest.raises(ConstraintExecutionError, match="Unknown rubric set"):
        run(CLEAN, config=RuntimeConfig(rubric_set="v9.9"))


def test_runtime_config_provider_id_is_operative(monkeypatch):
    monkeypatch.delenv("AI4_ENABLE_LIVE_LLM", raising=False)
    with pytest.raises(ConstraintExecutionError, match="fail closed"):
        run(CLEAN, config=RuntimeConfig(provider_id="live"))


def test_prompt_specified_shards_do_not_narrow_enforcement():
    leaking = LEAKING
    frozen_eval = FrozenV01RegexEvaluator().evaluate(leaking)
    frozen_arb = arbitrate(frozen_eval, FrozenV01RegexEvaluator().rubrics)
    assert frozen_eval.by_id()["privacy"].passed is False
    assert frozen_arb.veto is True

    report = evaluate(leaking, prompt_specified_shards=("compassion",), redact=False)
    assert report.enforced_shards == REQUIRED_IDS
    assert report.shard_control_scope == "all_required_v0.1"
    assert report.prompt_specified_shards == ("compassion",)
    assert report.shard_evaluations is not None
    privacy = next(item for item in report.shard_evaluations if item.shard_id == "privacy")
    compassion = next(item for item in report.shard_evaluations if item.shard_id == "compassion")
    assert privacy.enforced is True
    assert privacy.passed is False
    assert privacy.applicable is False
    assert privacy.verdict == "not_applicable"
    assert compassion.applicable is True
    assert report.arbitration is not None
    assert report.arbitration.veto is True
    assert report.decision == "revise"


def test_incomplete_custom_evaluator_rejected_before_provider_complete():
    class Incomplete:
        backend_id = "incomplete"
        version = "0"
        rubrics = FrozenV01RegexEvaluator().rubrics

        def evaluate(self, text: str) -> Evaluation:
            return Evaluation(text=text, shard_scores=())

    provider = ScriptedProvider(complete_texts=["MUST NOT RUN"], revise_texts=["MUST NOT RUN"])
    with pytest.raises(ConstraintExecutionError, match="did not execute"):
        run("hello", provider=provider, evaluator=Incomplete())
    assert provider.complete_calls == 0
    assert provider.revise_calls == 0


def test_revision_trace_uses_captured_not_replayed_scores():
    real = FrozenV01RegexEvaluator()
    fail = real.evaluate(LEAKING)
    passed = real.evaluate(CLEAN_TEXT)

    def relabel(template: Evaluation, text: str) -> Evaluation:
        return Evaluation(
            text=text,
            shard_scores=template.shard_scores,
            rubric_set_version=template.rubric_set_version,
        )

    class Flip:
        backend_id = "flip"
        version = "0"
        rubrics = real.rubrics

        def __init__(self) -> None:
            self.counts: dict[str, int] = {}

        def evaluate(self, text: str) -> Evaluation:
            if text == PREFLIGHT_PROBE:
                return relabel(passed, text)
            if text != LEAKING:
                return relabel(passed, text)
            self.counts[text] = self.counts.get(text, 0) + 1
            if self.counts[text] == 1:
                return relabel(fail, text)
            return relabel(passed, text)

    flip = Flip()
    provider = ScriptedProvider(complete_texts=[LEAKING], revise_texts=[CLEAN_TEXT])
    report = run("annotate this", provider=provider, evaluator=flip, redact=False)
    assert report.revision_trace
    first = report.revision_trace[0]
    assert first.captured is True
    privacy = next(item for item in first.shard_evaluations if item.shard_id == "privacy")
    assert privacy.passed is False
    # Independent: a later evaluate of the same draft now returns pass.
    replay = flip.evaluate(LEAKING)
    assert replay.by_id()["privacy"].passed is True
    assert privacy.passed is False


def test_terminal_labels_are_frozen_or_null():
    accepted = run(CLEAN)
    assert accepted.terminal in FROZEN_TERMINAL_LABELS
    scored = evaluate(CLEAN_TEXT)
    assert scored.terminal is None
    timed = run(CLEAN, timeout_s=0)
    assert timed.terminal == "timed_out"
    assert timed.terminal in FROZEN_TERMINAL_LABELS


def test_public_module_does_not_export_experiment_test_surface():
    assert not hasattr(public, "ScriptedProvider")
    assert not hasattr(public, "HeuristicMockProvider")
    assert not hasattr(public, "register_evaluator")
    assert not hasattr(public, "registered_evaluators")
    signature = inspect.signature(run)
    assert "now" not in signature.parameters
    assert "specified_shards" not in signature.parameters
    assert "prompt_specified_shards" in signature.parameters


def test_packaged_rubrics_match_frozen_repo_bytes():
    packaged = packaged_rubric_bytes()
    assert tuple(packaged) == REQUIRED_IDS
    for shard_id, data in packaged.items():
        repo = (REPO_RUBRICS / f"{shard_id}.yaml").read_bytes()
        assert hashlib.sha256(data).hexdigest() == hashlib.sha256(repo).hexdigest()


def test_default_report_redacts_personal_data_without_changing_verdicts():
    raw = evaluate(LEAKING, redact=False)
    redacted = evaluate(LEAKING)
    assert "078-05-1120" in raw.to_json()
    assert "078-05-1120" not in redacted.to_json()
    assert "078-05-1120" not in redacted.initial_proposal
    assert raw.decision == redacted.decision == "revise"
    assert raw.shard_evaluations is not None and redacted.shard_evaluations is not None
    assert [item.passed for item in raw.shard_evaluations] == [
        item.passed for item in redacted.shard_evaluations
    ]


def test_docs_state_d_did_not_win_stage2d():
    readme = Path("README.md").read_text(encoding="utf-8")
    runtime = Path("docs/constrain-runtime.md").read_text(encoding="utf-8")
    for text in (readme, runtime):
        collapsed = " ".join(text.replace("**", "").split())
        assert "null_retained_D_adds_cost" in collapsed
        assert "did not establish D as superior to C" in collapsed
        assert "condition-D" in collapsed or "condition D" in collapsed
