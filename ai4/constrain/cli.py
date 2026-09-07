"""Product CLI for the frozen v0.1 shard runtime.

Exit codes (a report is still written for 0/2/3/4):

- 0 accept
- 1 configuration / runtime failure (no usable report)
- 2 revise
- 3 refuse
- 4 timeout / budget / other execution failure

Default reports redact common personal-data patterns. ``--no-redact``
writes raw prompt/draft/evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport

EXIT_ACCEPT = 0
EXIT_CONFIG = 1
EXIT_REVISE = 2
EXIT_REFUSE = 3
EXIT_TIMEOUT = 4


class ConstrainedArgumentParser(argparse.ArgumentParser):
    """Usage errors are configuration failures (exit 1), not revise (exit 2)."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise ConstraintExecutionError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = ConstrainedArgumentParser(
        prog="ai4-constrain",
        description=(
            "Call the frozen condition-D shard runtime and print a DecisionReport. "
            "Exit 0=accept, 1=config/runtime failure, 2=revise, 3=refuse, "
            "4=timeout/execution failure. Default output is redacted. "
            "This is not the experiment harness."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Propose (or take a draft) and apply frozen D control.")
    run_p.add_argument("--prompt", default="", help="User prompt. Required unless --prompt-file is set.")
    run_p.add_argument("--prompt-file", type=Path, default=None, help="Read prompt text from a file.")
    run_p.add_argument("--proposal", default=None, help="Optional first draft. Skips the first model sample.")
    run_p.add_argument("--provider", default="mock", choices=("mock", "live"), help="Proposal backend.")
    run_p.add_argument("--output", type=Path, default=None, help="Write DecisionReport JSON here.")
    run_p.add_argument("--prompt-id", default="", help="Optional caller id recorded on the report.")
    run_p.add_argument("--timeout-s", type=float, default=None, help="Override wall-clock timeout seconds.")
    run_p.add_argument("--max-completions", type=int, default=None, help="Override completion budget.")
    run_p.add_argument(
        "--no-redact",
        action="store_true",
        help="Write raw prompt/draft/evidence. Default redacts common personal-data patterns.",
    )
    run_p.add_argument(
        "--require-accept",
        action="store_true",
        help="If the decision is not accept, keep the terminal exit code (already non-zero).",
    )

    eval_p = sub.add_parser("evaluate", help="Score existing text. No model calls.")
    eval_p.add_argument("--text", default="", help="Candidate text. Required unless --text-file is set.")
    eval_p.add_argument("--text-file", type=Path, default=None, help="Read candidate text from a file.")
    eval_p.add_argument("--prompt", default="", help="Optional prompt recorded on the report.")
    eval_p.add_argument("--output", type=Path, default=None, help="Write DecisionReport JSON here.")
    eval_p.add_argument("--prompt-id", default="", help="Optional caller id recorded on the report.")
    eval_p.add_argument("--no-redact", action="store_true", help="Write raw text and evidence.")
    eval_p.add_argument(
        "--require-accept",
        action="store_true",
        help="If the decision is not accept, keep the terminal exit code (already non-zero).",
    )
    return parser


def _read_text(value: str, path: Path | None, *, flag: str, file_flag: str) -> str:
    if path is not None:
        if not path.is_file():
            raise ConstraintExecutionError(f"{file_flag} not found: {path}")
        return path.read_text(encoding="utf-8")
    if value:
        return value
    raise ConstraintExecutionError(f"{flag} or {file_flag} is required")


def _emit(report: DecisionReport, output: Path | None) -> None:
    rendered = report.to_json() + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)


def report_exit_code(report: DecisionReport) -> int:
    """Map a finished report onto the CLI terminal contract."""
    if report.outcome_kind == "execution":
        return EXIT_TIMEOUT
    if report.decision == "accept":
        return EXIT_ACCEPT
    if report.decision == "revise":
        return EXIT_REVISE
    if report.decision == "refuse":
        return EXIT_REFUSE
    return EXIT_CONFIG


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "evaluate":
            text = _read_text(args.text, args.text_file, flag="--text", file_flag="--text-file")
            report = evaluate(
                text,
                prompt=args.prompt,
                prompt_id=args.prompt_id,
                redact=not args.no_redact,
            )
            _emit(report, args.output)
            return report_exit_code(report)
        prompt = _read_text(args.prompt, args.prompt_file, flag="--prompt", file_flag="--prompt-file")
        kwargs = {
            "proposal": args.proposal,
            "provider": args.provider,
            "prompt_id": args.prompt_id,
            "redact": not args.no_redact,
        }
        if args.timeout_s is not None:
            kwargs["timeout_s"] = args.timeout_s
        if args.max_completions is not None:
            kwargs["max_completions"] = args.max_completions
        report = run(prompt, **kwargs)
        _emit(report, args.output)
        return report_exit_code(report)
    except ConstraintExecutionError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_CONFIG
