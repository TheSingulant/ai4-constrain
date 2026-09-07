"""Offline experiment runner for conditions A, B, C, D."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.agents.base_agent import AgentConfig
from src.agents.recursive_agent import ConstrainedAgent
from src.metrics import item_metrics, summarize
from src.paths import DEFAULT_FIXTURE
from src.providers.base import LLMProvider
from src.providers.mock import HeuristicMockProvider
from src.shards.shard_evaluator import ShardEvaluator
from src.shards.shard_loader import REQUIRED_IDS

CONDITIONS = ("A", "B", "C", "D")
KNOWN_SHARDS = frozenset(REQUIRED_IDS)

# Frozen benchmark categories (synthetic fixtures only).
BENCHMARK_CATEGORIES = (
    "truth_vs_compassion",
    "autonomy_vs_harm",
    "privacy_vs_transparency",
    "loyalty_vs_impartiality",
    "benign",
    "overcautious_refusal",
    "clarification",
    "insufficient_facts",
    "adversarial_evaluator_injection",
)


@dataclass(frozen=True)
class PromptCase:
    id: str
    prompt: str
    specified_shards: tuple[str, ...]
    category: str = ""


class ExperimentConfigError(ValueError):
    """Invalid runner config or fixture. Fail closed."""


def validate_experiment_config(
    conditions: Sequence[str],
    *,
    fixture: Path | None = None,
    config: AgentConfig | None = None,
) -> tuple[str, ...]:
    """Validate condition ids, optional fixture path, and agent bounds."""
    selected = tuple(item.upper() for item in conditions)
    unknown = [item for item in selected if item not in CONDITIONS]
    if unknown:
        raise ExperimentConfigError(
            f"Unknown condition {unknown[0]}. Expected one of {CONDITIONS}."
        )
    if fixture is not None and not fixture.is_file():
        raise ExperimentConfigError(f"Fixture not found: {fixture}")
    if config is not None:
        if config.timeout_s < 0:
            raise ExperimentConfigError("timeout_s must be >= 0")
        if config.max_revision_rounds < 0:
            raise ExperimentConfigError("max_revision_rounds must be >= 0")
        if config.max_completions < 0:
            raise ExperimentConfigError("max_completions must be >= 0")
        if config.condition.upper() not in CONDITIONS:
            raise ExperimentConfigError(
                f"Unknown condition {config.condition!r}. Expected one of {CONDITIONS}."
            )
    return selected


def load_cases(path: Path | None = None) -> list[PromptCase]:
    source = path or DEFAULT_FIXTURE
    if not source.is_file():
        raise ExperimentConfigError(f"Fixture not found: {source}")
    cases: list[PromptCase] = []
    for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExperimentConfigError(f"Malformed fixture JSON at line {line_no}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ExperimentConfigError(f"Fixture line {line_no} must be a JSON object")
        if "id" not in raw or "prompt" not in raw:
            raise ExperimentConfigError(f"Fixture line {line_no} missing id or prompt")
        specified = tuple(raw.get("specified_shards") or [])
        unknown = [item for item in specified if item not in KNOWN_SHARDS]
        if unknown:
            raise ExperimentConfigError(
                f"Unknown specified_shards {unknown} in case {raw.get('id')!r}"
            )
        category = str(raw.get("category") or "")
        if category and category not in BENCHMARK_CATEGORIES:
            raise ExperimentConfigError(
                f"Unknown category {category!r} in case {raw.get('id')!r}"
            )
        cases.append(
            PromptCase(
                id=str(raw["id"]),
                prompt=str(raw["prompt"]),
                specified_shards=specified,
                category=category,
            )
        )
    if not cases:
        raise ExperimentConfigError(f"Fixture is empty: {source}")
    return cases


def run_condition(
    condition: str,
    cases: Sequence[PromptCase],
    *,
    provider: LLMProvider | None = None,
    config: AgentConfig | None = None,
) -> dict:
    condition = condition.upper()
    cfg = config or AgentConfig(condition=condition)
    validate_experiment_config((condition,), config=cfg)
    agent = ConstrainedAgent(
        provider or HeuristicMockProvider(),
        evaluator=ShardEvaluator(),
        config=cfg,
    )
    rows = []
    for case in cases:
        result = agent.run(
            case.prompt,
            prompt_id=case.id,
            specified_shards=case.specified_shards,
        )
        rows.append(item_metrics(result, case.prompt, category=case.category))
    return {
        "protocol": "v0.1",
        "condition": condition,
        "items": rows,
        "summary": summarize(rows),
    }


def compare_primary(results_by_condition: dict[str, dict]) -> dict:
    """Primary comparison is D vs C, as frozen in the protocol."""
    if "C" not in results_by_condition or "D" not in results_by_condition:
        return {"primary": "D_vs_C", "available": False}
    c_sum = results_by_condition["C"]["summary"]
    d_sum = results_by_condition["D"]["summary"]
    return {
        "primary": "D_vs_C",
        "available": True,
        "c_violation_rate": c_sum["specified_constraint_violation_rate"],
        "d_violation_rate": d_sum["specified_constraint_violation_rate"],
        "c_mean_usefulness": c_sum["mean_usefulness_proxy"],
        "d_mean_usefulness": d_sum["mean_usefulness_proxy"],
        "d_fewer_violations": d_sum["specified_constraint_violation_rate"]
        < c_sum["specified_constraint_violation_rate"],
        "d_usefulness_not_worse": d_sum["mean_usefulness_proxy"] >= c_sum["mean_usefulness_proxy"],
    }


def run_experiment(
    conditions: Sequence[str] | None = None,
    *,
    fixture: Path | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    selected = validate_experiment_config(conditions or CONDITIONS, fixture=fixture)
    cases = load_cases(fixture)
    by_condition = {
        condition: run_condition(condition, cases, provider=provider, config=AgentConfig(condition=condition))
        for condition in selected
    }
    return {
        "protocol": "v0.1",
        "conditions": list(selected),
        "results": by_condition,
        "primary_comparison": compare_primary(by_condition),
    }
