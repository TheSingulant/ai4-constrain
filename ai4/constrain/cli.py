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
import json
import sys
from pathlib import Path

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.explain import format_explain, format_shard_card, shard_card
from ai4.constrain.ext import session_store
from ai4.constrain.report import DecisionReport
from ai4.constrain.session import ConstrainedSession, dry_run_demo, trusted_assistant_output
from ai4.constrain.trace import JsonlTraceWriter

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


def _add_redact_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Write raw prompt/draft/evidence. Default redacts common personal-data patterns.",
    )


def _add_explain_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Print a shard card to stderr. JSON on stdout is unchanged.",
    )
    parser.add_argument(
        "--trace-jsonl",
        type=Path,
        default=None,
        help="Append a compact JSONL decision trace for this call.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = ConstrainedArgumentParser(
        prog="ai4-constrain",
        description=(
            "Call the frozen condition-D shard runtime and print a DecisionReport. "
            "Exit 0=accept, 1=config/runtime failure, 2=revise, 3=refuse, "
            "4=timeout/execution failure. Default output is redacted. "
            "Session wraps the same path. This is not the experiment harness."
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
    _add_redact_flag(run_p)
    _add_explain_flags(run_p)
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
    _add_redact_flag(eval_p)
    _add_explain_flags(eval_p)
    eval_p.add_argument(
        "--require-accept",
        action="store_true",
        help="If the decision is not accept, keep the terminal exit code (already non-zero).",
    )

    explain_p = sub.add_parser("explain", help="Print a shard card for existing text (evaluate-only).")
    explain_p.add_argument("--text", default="", help="Candidate text. Required unless --text-file is set.")
    explain_p.add_argument("--text-file", type=Path, default=None, help="Read candidate text from a file.")
    explain_p.add_argument("--prompt", default="", help="Optional prompt recorded on the report.")
    _add_redact_flag(explain_p)
    explain_p.add_argument("--json", action="store_true", dest="as_json", help="Print shard-card JSON instead of text.")

    sess = sub.add_parser("session", help="Persistent ConstrainedSession over frozen D.")
    sess_sub = sess.add_subparsers(dest="session_command", required=True)

    complete_p = sess_sub.add_parser("complete", help="One session turn wrapping run().")
    complete_p.add_argument("--prompt", default="", help="User prompt. Required unless --prompt-file is set.")
    complete_p.add_argument("--prompt-file", type=Path, default=None, help="Read prompt text from a file.")
    complete_p.add_argument("--session-id", default="", help="Session id. Generated if omitted.")
    complete_p.add_argument(
        "--store-dir",
        type=Path,
        default=None,
        help="Directory for JSON session snapshots. Default is in-memory (this process only).",
    )
    complete_p.add_argument("--include-history", action="store_true", help="Prepend untrusted prior user/trusted-assistant turns to the prompt.")
    complete_p.add_argument("--provider", default="mock", choices=("mock", "live"), help="Proposal backend.")
    complete_p.add_argument("--output", type=Path, default=None, help="Write session-turn JSON here.")
    complete_p.add_argument("--dry-run", action="store_true", help="Force mock-only; refuse live providers.")
    _add_redact_flag(complete_p)
    _add_explain_flags(complete_p)

    show_p = sess_sub.add_parser("show", help="Print a stored session snapshot.")
    show_p.add_argument("--session-id", required=True, help="Session id to load.")
    show_p.add_argument("--store-dir", type=Path, required=True, help="Directory used by session complete.")
    show_p.add_argument("--explain", action="store_true", help="Print the last turn's shard card to stderr.")

    demo_p = sess_sub.add_parser("demo", help="Dry-run mock conversation (accept / revise / refuse).")
    demo_p.add_argument("--store-dir", type=Path, default=None, help="Optional snapshot directory.")
    demo_p.add_argument("--trace-jsonl", type=Path, default=None, help="Write a JSONL trace of the demo.")
    demo_p.add_argument("--include-history", action="store_true", help="Compose later demo prompts with prior turns.")
    demo_p.add_argument("--explain", action="store_true", help="Print a shard card per turn to stderr.")
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


def _emit_json(payload: dict, output: Path | None) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)


def _maybe_explain(report: DecisionReport, enabled: bool, *, session_id: str = "", turn_index: int | None = None) -> None:
    if not enabled:
        return
    sys.stderr.write(format_explain(report, session_id=session_id, turn_index=turn_index))


def _maybe_trace(report: DecisionReport, path: Path | None, *, prompt: str, session_id: str, turn_index: int) -> None:
    if path is None:
        return
    writer = JsonlTraceWriter(path)
    writer.write_turn(
        session_id=session_id,
        turn_index=turn_index,
        prompt=prompt,
        report=report,
        trusted_output=trusted_assistant_output(report),
    )


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


def _cmd_evaluate(args: argparse.Namespace) -> int:
    text = _read_text(args.text, args.text_file, flag="--text", file_flag="--text-file")
    report = evaluate(
        text,
        prompt=args.prompt,
        prompt_id=args.prompt_id,
        redact=not args.no_redact,
    )
    _emit(report, args.output)
    _maybe_explain(report, args.explain)
    _maybe_trace(
        report,
        args.trace_jsonl,
        prompt=args.prompt or text,
        session_id=args.prompt_id or "evaluate",
        turn_index=1,
    )
    return report_exit_code(report)


def _cmd_run(args: argparse.Namespace) -> int:
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
    _maybe_explain(report, args.explain)
    _maybe_trace(
        report,
        args.trace_jsonl,
        prompt=prompt,
        session_id=args.prompt_id or "run",
        turn_index=1,
    )
    return report_exit_code(report)


def _cmd_explain(args: argparse.Namespace) -> int:
    text = _read_text(args.text, args.text_file, flag="--text", file_flag="--text-file")
    report = evaluate(text, prompt=args.prompt, redact=not args.no_redact)
    card = shard_card(report)
    if args.as_json:
        sys.stdout.write(json.dumps(card.to_dict(), indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(format_shard_card(card))
    return report_exit_code(report)


def _session_from_args(args: argparse.Namespace) -> ConstrainedSession:
    store = session_store(str(args.store_dir) if getattr(args, "store_dir", None) else None)
    tracer = JsonlTraceWriter(args.trace_jsonl) if getattr(args, "trace_jsonl", None) else None
    session_id = str(getattr(args, "session_id", "") or "") or None
    return ConstrainedSession(
        session_id=session_id,
        store=store,
        tracer=tracer,
        include_history=bool(getattr(args, "include_history", False)),
        provider=getattr(args, "provider", "mock"),
        redact=not bool(getattr(args, "no_redact", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        persist=True,
    )


def _cmd_session_complete(args: argparse.Namespace) -> int:
    prompt = _read_text(args.prompt, args.prompt_file, flag="--prompt", file_flag="--prompt-file")
    session = _session_from_args(args)
    turn = session.complete(prompt)
    envelope = {
        "session_id": session.session_id,
        **turn.to_dict(),
    }
    _emit_json(envelope, args.output)
    _maybe_explain(
        turn.report,
        args.explain,
        session_id=session.session_id,
        turn_index=turn.turn_index,
    )
    return report_exit_code(turn.report)


def _cmd_session_show(args: argparse.Namespace) -> int:
    store = session_store(str(args.store_dir))
    session = ConstrainedSession.load(args.session_id, store=store)
    sys.stdout.write(session.snapshot().to_json() + "\n")
    if args.explain:
        sys.stderr.write(session.explain())
    return EXIT_ACCEPT if session.last_turn is not None else EXIT_CONFIG


def _cmd_session_demo(args: argparse.Namespace) -> int:
    store = session_store(str(args.store_dir) if args.store_dir else None)
    tracer = JsonlTraceWriter(args.trace_jsonl) if args.trace_jsonl else None
    session = dry_run_demo(
        store=store,
        tracer=tracer,
        include_history=bool(args.include_history),
    )
    payload = {
        "session_id": session.session_id,
        "turns": [
            {
                "turn_index": turn.turn_index,
                "decision": turn.report.decision,
                "terminal": turn.report.terminal,
                "shard_card": turn.card().to_dict(),
            }
            for turn in session.turns
        ],
    }
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    if args.explain:
        for turn in session.turns:
            sys.stderr.write(turn.explain(session_id=session.session_id))
            sys.stderr.write("\n")
    return EXIT_ACCEPT


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "evaluate":
            return _cmd_evaluate(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "explain":
            return _cmd_explain(args)
        if args.command == "session":
            if args.session_command == "complete":
                return _cmd_session_complete(args)
            if args.session_command == "show":
                return _cmd_session_show(args)
            if args.session_command == "demo":
                return _cmd_session_demo(args)
            raise ConstraintExecutionError(f"Unknown session command {args.session_command!r}")
        raise ConstraintExecutionError(f"Unknown command {args.command!r}")
    except ConstraintExecutionError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_CONFIG
    except KeyboardInterrupt:
        sys.stderr.write("stopped\n")
        return EXIT_ACCEPT
