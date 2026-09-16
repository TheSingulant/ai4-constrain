"""CLI for the transaction-control scaffold.

Exit codes:
- 0 ALLOW, or status with an unambiguous RPC result
- 1 DENY, fail-closed, or usage/config error
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.prepare import prepare_transfer
from ai4.transaction.status import format_status_summary, status
from ai4.transaction.types import Decision, TransferConfig, TransferIntent
from ai4.transaction.validate import parse_max_amount

EXIT_OK = 0
EXIT_FAIL = 1


class TransactionArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise TransactionControlError(message, reasons=(message,))


def build_parser() -> argparse.ArgumentParser:
    parser = TransactionArgumentParser(
        prog="ai4-transaction",
        description=(
            "Prepare or observe a v1 native SOL transfer through the "
            "ai4.transaction firewall. Signing stays in the user wallet. "
            "This is a scaffold, not a released PyPI feature claim."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_p = sub.add_parser(
        "prepare",
        help="Validate, run the firewall, print DecisionReport JSON and a summary.",
    )
    prepare_p.add_argument("--network", required=True, help="mainnet-beta, devnet, or localnet")
    prepare_p.add_argument("--asset", required=True, help="SOL (v1 native SOL only)")
    prepare_p.add_argument("--amount", required=True, help="Positive SOL amount, at most 9 decimals")
    prepare_p.add_argument("--destination", required=True, help="Solana destination address")
    prepare_p.add_argument(
        "--rpc-url",
        default=None,
        help="Optional Solana RPC URL. Overrides AI4_SOLANA_RPC_URL when set.",
    )
    prepare_p.add_argument(
        "--max-amount",
        default=None,
        help="Optional SOL cap. Default is 1 SOL.",
    )

    status_p = sub.add_parser(
        "status",
        help="Poll signature status. Fails closed without an RPC URL.",
    )
    status_p.add_argument("signature", help="Solana transaction signature (base58)")
    status_p.add_argument(
        "--rpc-url",
        default=None,
        help="Optional Solana RPC URL. Overrides AI4_SOLANA_RPC_URL when set.",
    )
    status_p.add_argument(
        "--network",
        default=None,
        help="Optional cluster for an explorer link (mainnet-beta, devnet, localnet).",
    )
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _run_prepare(args: argparse.Namespace) -> int:
    max_amount: Decimal | str | None = args.max_amount
    if max_amount is not None:
        max_amount = parse_max_amount(max_amount)
    config = TransferConfig(max_amount_sol=max_amount) if max_amount is not None else TransferConfig()
    if args.rpc_url:
        config = TransferConfig(max_amount_sol=config.max_amount_sol, rpc_url=args.rpc_url)
    intent = TransferIntent(
        network=args.network,
        asset=args.asset,
        amount=args.amount,
        destination=args.destination,
    )
    result = prepare_transfer(intent, config=config, rpc_url=args.rpc_url)
    payload = result.to_dict()
    if result.report is not None:
        # DecisionReport JSON is the constrain artifact; keep it top-level too.
        payload["decision_report"] = result.report.to_dict()
    _print_json(payload)
    print(result.summary, file=sys.stderr)
    return EXIT_OK if result.decision is Decision.ALLOW else EXIT_FAIL


def _run_status(args: argparse.Namespace) -> int:
    receipt = status(args.signature, rpc_url=args.rpc_url, network=args.network)
    _print_json(receipt.to_dict())
    print(format_status_summary(receipt), file=sys.stderr)
    return EXIT_FAIL if receipt.fail_closed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "prepare":
            return _run_prepare(args)
        if args.command == "status":
            return _run_status(args)
        raise TransactionControlError("unknown command", reasons=("unknown command",))
    except TransactionValidationError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL
    except TransactionControlError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
