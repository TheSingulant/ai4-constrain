"""Sibling identity discovery CLI. Not the constrain product CLI.

A signed AI4 identity record binds claims and provenance to an agent identity;
it does not prove the agent is aligned, safe, or correctly governed.

Identity is not trust. Resolution is not verification. Naming is not policy
authority.

Never prints SAFE, ALIGNED, accept, revise, or refuse as statuses.
Never reuses constrain exit codes 2/3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai4.identity.errors import IdentityError
from ai4.identity.resolve.file_resolver import FileResolver
from ai4.identity.resolve.fetch import LocalFileFetcher
from ai4.identity.resolve.pipeline import discover_and_verify
from ai4.identity.resolve.types import ResolveResult, Status
from ai4.identity.timeutil import SystemClock
from ai4.identity.trust import TrustContext

GOVERNING_PRINCIPLE_CLI = (
    "A signed AI4 identity record binds claims and provenance to an agent identity;\n"
    "it does not prove the agent is aligned, safe, or correctly governed."
)

EXIT_OK = 0
EXIT_FAIL_CLOSED = 1
EXIT_SIGNATURE = 5
EXIT_TRUST = 6
EXIT_BINDING = 7


class IdentityArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise IdentityError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = IdentityArgumentParser(
        prog="ai4-identity",
        description=(
            "Resolve a .ai4 name into hash-bound provenance inputs for the existing "
            "identity kernel. Resolution is not verification. Naming is not policy "
            "authority. This is not the constrain CLI."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    resolve_p = sub.add_parser(
        "resolve",
        help="Lookup a .ai4 name and check published hashes. Does not set current trust.",
    )
    _add_common(resolve_p)

    verify_p = sub.add_parser(
        "verify",
        help="Resolve, check hashes, then run kernel signature/trust/report checks.",
    )
    _add_common(verify_p)
    verify_p.add_argument(
        "--trust",
        type=Path,
        default=None,
        help="TrustContext JSON. Required for CURRENT TRUST MATCHED: yes. Never inferred from the name.",
    )
    verify_p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional DecisionReport JSON for report-binding comparison.",
    )
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="ASCII .ai4 name to look up.")
    parser.add_argument(
        "--resolver",
        default="file",
        help="Resolver kind. First slice supports file only.",
    )
    parser.add_argument(
        "--records",
        type=Path,
        required=True,
        help="FileResolver JSON records path or directory of fixtures.",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=None,
        dest="max_age",
        help="Fail closed if discovery captured_at is older than this many seconds.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = _run(args)
    except IdentityError as exc:
        result = ResolveResult(
            status=Status("no", "no", "no", "not_requested", "not_requested"),
            detail=str(exc),
        )
        _emit(result)
        return EXIT_FAIL_CLOSED
    _emit(result)
    return _exit_code(args.command, result, args)


def _run(args: argparse.Namespace) -> ResolveResult:
    if args.resolver != "file":
        raise IdentityError(
            f"unknown resolver kind {args.resolver!r}; live Unstoppable REST is not enabled"
        )
    resolver = FileResolver(args.records)
    base = args.records if args.records.is_dir() else args.records.parent
    fetcher = LocalFileFetcher(base)
    trust = None
    report = None
    verify_signature = args.command == "verify"
    if args.command == "verify":
        if args.trust is not None:
            trust = TrustContext.from_dict(_load_json(args.trust))
        if args.report is not None:
            report = _load_json(args.report)
    return discover_and_verify(
        args.name,
        resolver,
        fetcher=fetcher,
        clock=SystemClock(),
        max_age_s=args.max_age,
        trust=trust,
        report=report,
        verify_signature=verify_signature,
    )


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityError(f"failed to read {path}: {exc}") from exc


def _emit(result: ResolveResult) -> None:
    sys.stderr.write(GOVERNING_PRINCIPLE_CLI + "\n\n")
    sys.stderr.write(result.status.human_lines() + "\n")
    if result.detail:
        sys.stderr.write(f"detail: {result.detail}\n")
    sys.stdout.write(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")


def _exit_code(command: str, result: ResolveResult, args: argparse.Namespace) -> int:
    status = result.status
    if status.name_resolved != "yes":
        return EXIT_FAIL_CLOSED
    if status.manifest_integrity_verified != "yes":
        return EXIT_FAIL_CLOSED
    if command == "resolve":
        return EXIT_OK
    if status.signature_valid == "no":
        return EXIT_SIGNATURE
    if "expired" in result.detail or status.report_binding_matched == "expired":
        if getattr(args, "trust", None) is not None and status.current_trust_matched != "yes":
            return EXIT_TRUST
        if getattr(args, "report", None) is not None and status.report_binding_matched != "yes":
            return EXIT_BINDING
        return EXIT_FAIL_CLOSED
    if getattr(args, "trust", None) is not None and status.current_trust_matched != "yes":
        return EXIT_TRUST
    if getattr(args, "report", None) is not None and status.report_binding_matched != "yes":
        return EXIT_BINDING
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
