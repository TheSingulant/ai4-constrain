"""Stage 2D stress-benchmark runner scaffold.

Offline/mock by default. Wires the frozen C/D LoopDecision path.
Live path is guarded by the $2 pre-request cap and is not executed in
this authoring PR.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from src.agents.base_agent import AgentConfig
from src.agents.recursive_agent import ConstrainedAgent
from src.providers.base import LLMProvider
from src.providers.live import LiveProvider
from src.providers.mock import HeuristicMockProvider
from src.shards.shard_evaluator import ShardEvaluator
from src.stage2d.constants import (
    STAGE2D_CONDITIONS,
    STAGE2D_DEV_SET,
    STAGE2D_HELDOUT,
    STAGE2D_MAX_SPEND_USD,
    STAGE2D_PRIMARY_CONDITIONS,
    STAGE2D_PROTOCOL,
)
from src.stage2d.metrics import compare_c_vs_d, stage2d_item_row, summarize_stage2d
from src.stage2d.schema import Stage2DCase, Stage2DCaseError, load_cases
from src.stage2d.spend import Stage2DLiveGuard, Stage2DSpendError, assert_stage2d_live_allowed


class Stage2DConfigError(ValueError):
    """Invalid Stage 2D runner config. Fail closed."""


def validate_conditions(conditions: Sequence[str]) -> tuple[str, ...]:
    selected = tuple(item.upper() for item in conditions)
    unknown = [item for item in selected if item not in STAGE2D_CONDITIONS]
    if unknown:
        raise Stage2DConfigError(
            f"Unknown condition {unknown[0]}. Expected one of {STAGE2D_CONDITIONS}."
        )
    return selected


def load_stage2d_cases(path: Path | None = None) -> list[Stage2DCase]:
    source = path or STAGE2D_DEV_SET
    return load_cases(source)


def _provider(name: str) -> LLMProvider:
    if name == "mock":
        return HeuristicMockProvider()
    if name == "live":
        assert_stage2d_live_allowed()
        return Stage2DLiveGuard(LiveProvider())
    raise Stage2DConfigError(f"Unknown provider {name!r}. Use mock or live.")


def run_condition(
    condition: str,
    cases: Sequence[Stage2DCase],
    *,
    provider: LLMProvider | None = None,
    config: AgentConfig | None = None,
) -> dict:
    condition = condition.upper()
    if condition not in STAGE2D_CONDITIONS:
        raise Stage2DConfigError(
            f"Unknown condition {condition}. Expected one of {STAGE2D_CONDITIONS}."
        )
    cfg = config or AgentConfig(condition=condition)
    if cfg.condition.upper() not in STAGE2D_CONDITIONS:
        raise Stage2DConfigError(
            f"Unknown condition {cfg.condition!r}. Expected one of {STAGE2D_CONDITIONS}."
        )
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
        rows.append(stage2d_item_row(case, result))
    return {
        "protocol": STAGE2D_PROTOCOL,
        "condition": condition,
        "items": rows,
        "summary": summarize_stage2d(rows),
    }


def run_stage2d(
    conditions: Sequence[str] | None = None,
    *,
    fixture: Path | None = None,
    provider: LLMProvider | None = None,
    provider_name: str = "mock",
    allow_heldout: bool = False,
) -> dict:
    """Run Stage 2D conditions on a fixture.

    Held-out is loadable for hash and schema tests. Scoring the held-out
    split as a live benchmark is not authorized from this authoring PR.
    """
    selected = validate_conditions(conditions or STAGE2D_PRIMARY_CONDITIONS)
    source = fixture or STAGE2D_DEV_SET
    if source.resolve() == STAGE2D_HELDOUT.resolve() and not allow_heldout:
        raise Stage2DConfigError(
            "Held-out scoring is blocked in the authoring runner. "
            "Pass allow_heldout only for offline load tests, not paid runs."
        )
    cases = load_stage2d_cases(source)
    active = provider if provider is not None else _provider(provider_name)
    by_condition = {
        condition: run_condition(
            condition,
            cases,
            provider=active,
            config=AgentConfig(condition=condition),
        )
        for condition in selected
    }
    return {
        "protocol": STAGE2D_PROTOCOL,
        "conditions": list(selected),
        "fixture": str(source),
        "max_spend_usd": STAGE2D_MAX_SPEND_USD,
        "results": by_condition,
        "primary_comparison": compare_c_vs_d(by_condition),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="ai4-stage2d",
        description="Stage 2D stress-benchmark runner (offline/mock by default).",
    )
    parser.add_argument(
        "--condition",
        default="CD",
        help="C, D, CD, all, or a comma list. Default CD (primary).",
    )
    parser.add_argument("--fixture", type=Path, default=STAGE2D_DEV_SET)
    parser.add_argument("--provider", default="mock", choices=("mock", "live"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--allow-heldout",
        action="store_true",
        help="Permit loading the held-out file. Does not authorize a paid run.",
    )
    args = parser.parse_args(argv)
    raw = args.condition.strip().upper()
    if raw in {"ALL", "*"}:
        selected = STAGE2D_CONDITIONS
    elif raw in {"CD", "PRIMARY"}:
        selected = STAGE2D_PRIMARY_CONDITIONS
    else:
        selected = tuple(item.strip() for item in raw.split(",") if item.strip())
    if args.provider == "live":
        try:
            assert_stage2d_live_allowed()
        except Stage2DSpendError as exc:
            raise SystemExit(str(exc)) from exc
    try:
        payload = run_stage2d(
            selected,
            fixture=args.fixture,
            provider_name=args.provider,
            allow_heldout=args.allow_heldout,
        )
    except (Stage2DConfigError, Stage2DCaseError, Stage2DSpendError) as exc:
        raise SystemExit(str(exc)) from exc
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
