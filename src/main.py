"""CLI for the v0.1 offline experiment harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.experiment import CONDITIONS, run_experiment
from src.providers.live import LiveProvider
from src.providers.mock import HeuristicMockProvider
from src.shards.shard_evaluator import ShardEvaluator


def _provider(name: str):
    if name == "mock":
        return HeuristicMockProvider()
    if name == "live":
        return LiveProvider()
    raise SystemExit(f"Unknown provider {name!r}. Use mock or live.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai4-experiment",
        description="AI4 v0.1 offline shard-evaluation experiment runner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    experiment = sub.add_parser("experiment", help="Run A/B/C/D conditions on a fixture file.")
    experiment.add_argument(
        "--condition",
        default="all",
        help="A, B, C, D, or all (default all).",
    )
    experiment.add_argument("--fixture", type=Path, default=None, help="JSONL prompt fixture.")
    experiment.add_argument("--provider", default="mock", choices=("mock", "live"))
    experiment.add_argument("--output", type=Path, default=None, help="Write JSON results here.")

    evaluate = sub.add_parser("evaluate", help="Score one text against v0.1 shard rubrics.")
    evaluate.add_argument("--text", required=True, help="Candidate text to score.")

    stage2d = sub.add_parser(
        "stage2d",
        help="Stage 2D stress benchmark (offline/mock by default; $2 live cap).",
    )
    stage2d.add_argument(
        "--condition",
        default="CD",
        help="C, D, CD, all, or a comma list. Default CD (primary).",
    )
    stage2d.add_argument("--fixture", type=Path, default=None, help="Stage 2D JSONL fixture.")
    stage2d.add_argument("--provider", default="mock", choices=("mock", "live"))
    stage2d.add_argument("--output", type=Path, default=None, help="Write JSON results here.")
    stage2d.add_argument(
        "--allow-heldout",
        action="store_true",
        help="Permit loading the held-out file. Does not authorize a paid run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "stage2d":
        from src.stage2d.constants import STAGE2D_DEV_SET
        from src.stage2d.runner import main as stage2d_main

        stage_argv = [
            "--condition",
            args.condition,
            "--provider",
            args.provider,
            "--fixture",
            str(args.fixture or STAGE2D_DEV_SET),
        ]
        if args.output:
            stage_argv.extend(["--output", str(args.output)])
        if args.allow_heldout:
            stage_argv.append("--allow-heldout")
        return stage2d_main(stage_argv)
    if args.command == "evaluate":
        evaluation = ShardEvaluator().evaluate(args.text)
        payload = {
            "text": evaluation.text,
            "scores": {
                item.shard_id: {
                    "score": item.score,
                    "passed": item.passed,
                    "kind": item.kind,
                    "notes": list(item.notes),
                }
                for item in evaluation.shard_scores
            },
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.condition.lower() == "all":
        conditions = CONDITIONS
    else:
        conditions = (args.condition.upper(),)
    result = run_experiment(conditions, fixture=args.fixture, provider=_provider(args.provider))
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
