"""Solana DevNet-only end-to-end proof harness for ``ai4.transaction``.

Live path: user intent → validate → constrain firewall → DecisionReport ALLOW
→ bound wallet handoff → human signs in a self-custodial wallet → wallet
broadcasts on **devnet** → ``status()`` observes lifecycle → AI4 receipt.

This module never signs, never loads key files, and never broadcasts from a
server key. Desktop signing is the Phantom Chrome extension via a local HTML
page (injected provider). ``phantom.app/ul/browse`` is MOBILE_ONLY.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TextIO
from urllib.parse import urlparse

from ai4.transaction.desktop_handoff import (
    DEFAULT_HANDOFF_FILENAME,
    PHANTOM_BROWSE_OWNER_NOTE,
    default_desktop_handoff_path,
    local_http_open_url,
    local_http_serve_command,
    write_desktop_handoff_html,
)
from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.firewall import EvaluateFn
from ai4.transaction.prepare import prepare_transfer
from ai4.transaction.receipt import (
    ATTRIBUTION,
    AI4Receipt,
    LIFECYCLE_AWAITING_BROADCAST,
    LIFECYCLE_FAIL_CLOSED,
    LIFECYCLE_FAILED,
    LIFECYCLE_FINALIZED,
    LIFECYCLE_PREPARED,
    LIFECYCLE_TIMEOUT,
    build_ai4_receipt,
    format_ai4_receipt_summary,
    lifecycle_from_status,
)
from ai4.transaction.rpc import RPC_ENV_VAR, RpcPost, json_rpc_post, validate_rpc_url
from ai4.transaction.status import format_status_summary, status
from ai4.transaction.types import (
    Decision,
    Network,
    PrepareResult,
    Receipt,
    TransferConfig,
    TransferIntent,
)
from ai4.transaction.validate import parse_network, parse_sol_amount, validate_solana_signature

E2E_NETWORK = Network.DEVNET
PROOF_MAX_AMOUNT_SOL = Decimal("0.01")
PROOF_DEFAULT_AMOUNT_SOL = Decimal("0.001")
PUBLIC_DEVNET_RPC_EXAMPLE = "https://api.devnet.solana.com"
DEFAULT_POLL_TIMEOUT_S = 60.0
DEFAULT_POLL_INTERVAL_S = 2.0
DEFAULT_RPC_TIMEOUT_S = 10.0

# Documented public DevNet endpoint for operator-supplied --rpc-url. Never used
# as a silent default. Rate-limited; fail closed on ambiguity or transport error.
NOT_FOUND_MARKERS = (
    "signature not found",
    "status is null",
)
SECRET_OPTION_TOKENS = (
    "private-key",
    "private_key",
    "secret-key",
    "secret_key",
    "keypair",
    "keyfile",
    "key-file",
    "mnemonic",
    "seed",
    "wif",
    "secret",
)
LOCAL_RPC_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

EXIT_OK = 0
EXIT_FAIL = 1

PromptFn = Callable[[str], str]
MonotonicFn = Callable[[], float]
SleepFn = Callable[[float], None]


class DevnetE2EArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise TransactionControlError(message, reasons=(message,))


@dataclass(frozen=True)
class DevnetE2EResult:
    prepare: PrepareResult | None
    receipt: AI4Receipt | None
    status_receipt: Receipt | None = None
    error: str | None = None
    desktop_handoff_path: str | None = None


def require_devnet(network: Network | str | None) -> Network:
    """Force the live E2E path onto Solana DevNet. Reject every other cluster."""

    if network is None or (isinstance(network, str) and not network.strip()):
        return E2E_NETWORK
    parsed = parse_network(network)
    if parsed is not E2E_NETWORK:
        raise TransactionValidationError(
            "DevNet E2E rejects non-devnet networks",
            reasons=(
                f"network {parsed.value!r} is not allowed for the Solana DevNet E2E proof; "
                "only network=devnet is accepted (mainnet-beta, localnet, and others are rejected)",
            ),
        )
    return E2E_NETWORK


def reject_non_devnet_rpc_host(url: str) -> str:
    """Refuse RPC hosts that look like mainnet or localnet. Residual cluster risk remains."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise TransactionControlError(
            "E2E RPC URL is missing a host; fail closed",
            reasons=("E2E RPC URL is missing a host",),
        )
    if host in LOCAL_RPC_HOSTS or host.endswith(".localhost"):
        raise TransactionControlError(
            "E2E RPC host looks like localnet; fail closed",
            reasons=(f"E2E RPC host {host!r} looks like localnet; refuse",),
        )
    if "mainnet" in host:
        raise TransactionControlError(
            "E2E RPC host looks like mainnet; fail closed",
            reasons=(f"E2E RPC host {host!r} looks like mainnet; refuse",),
        )
    return url


def resolve_e2e_rpc_url(
    explicit: str | None = None,
    *,
    env_value: str | None = None,
) -> str:
    """Require an explicit RPC URL or ``AI4_SOLANA_RPC_URL``. No silent default.

    If both the argument and the env var are set to different values, fail closed
    (RPC ambiguity). Public ``https://api.devnet.solana.com`` may be passed
    explicitly; it is never inferred.
    """

    explicit_text = str(explicit).strip() if explicit is not None else ""
    explicit_text = explicit_text or None
    if env_value is None:
        env_value = os.environ.get(RPC_ENV_VAR, "")
    env_text = str(env_value).strip() or None

    if explicit_text and env_text and explicit_text != env_text:
        raise TransactionControlError(
            "RPC URL is ambiguous; fail closed",
            reasons=(
                "explicit --rpc-url and AI4_SOLANA_RPC_URL both set and they differ; "
                "fail closed on RPC ambiguity",
            ),
        )
    resolved = explicit_text or env_text
    if not resolved:
        raise TransactionControlError(
            "no Solana RPC URL; fail closed",
            reasons=(
                "no Solana RPC URL; pass --rpc-url or set AI4_SOLANA_RPC_URL. "
                f"For tests, operators may pass the public DevNet RPC {PUBLIC_DEVNET_RPC_EXAMPLE} "
                "(rate-limited; fail closed on errors). There is no hardcoded default.",
            ),
        )
    safe = validate_rpc_url(resolved)
    return reject_non_devnet_rpc_host(safe)


def reject_secret_like_input(value: str, *, field_name: str = "input") -> str:
    """Refuse seeds, PEM keys, and wallet key files. Signatures are public."""

    if not isinstance(value, str):
        raise TransactionValidationError(
            f"{field_name} must be text",
            reasons=(f"{field_name} must be text",),
        )
    text = value.strip()
    if not text:
        raise TransactionValidationError(
            f"{field_name} is required",
            reasons=(f"{field_name} is required",),
        )
    lowered = text.lower()
    if "-----begin" in lowered and "private key" in lowered:
        raise TransactionValidationError(
            "private key material is refused",
            reasons=("PEM private key material is refused; AI4 never handles keys",),
        )
    if text[0] in "{[":
        raise TransactionValidationError(
            "JSON key material is refused",
            reasons=("JSON keyfile / array input is refused; paste a transaction signature only",),
        )
    if "private key" in lowered or "secret key" in lowered:
        raise TransactionValidationError(
            "secret material is refused",
            reasons=("secret/private-key text is refused; AI4 never handles keys",),
        )
    if any(token in lowered for token in ("mnemonic", "seed phrase", "keypair path")):
        raise TransactionValidationError(
            "wallet secret material is refused",
            reasons=("seed/mnemonic/keypair input is refused; AI4 never handles keys",),
        )
    return text


def parse_user_signature(value: str) -> str:
    cleaned = reject_secret_like_input(value, field_name="signature")
    return validate_solana_signature(cleaned)


def _is_not_found(receipt: Receipt) -> bool:
    blob = " ".join(receipt.reasons).lower()
    return any(marker in blob for marker in NOT_FOUND_MARKERS)


def observe_devnet_status(
    signature: str,
    *,
    rpc_url: str,
    rpc_post: RpcPost | None = None,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
    rpc_timeout_s: float = DEFAULT_RPC_TIMEOUT_S,
    monotonic: MonotonicFn | None = None,
    sleep: SleepFn | None = None,
) -> tuple[Receipt, str]:
    """Poll ``status(..., network='devnet')`` until a terminal observation.

    Stops on processed (held if timeout hits first), confirmed, finalized,
    on-chain error (failed), fail-closed transport/shape errors, or timeout.
    ``processed`` keeps polling toward confirmed/finalized while time remains.
    """

    require_devnet(E2E_NETWORK)
    rpc = resolve_e2e_rpc_url(rpc_url)
    try:
        sig = parse_user_signature(signature)
    except TransactionValidationError as exc:
        display = ""
        try:
            reject_secret_like_input(str(signature or ""), field_name="signature")
            display = str(signature or "").strip()
        except TransactionValidationError:
            display = ""
        failed = Receipt(
            signature=display,
            fail_closed=True,
            reasons=exc.reasons,
            network=E2E_NETWORK.value,
            rpc_used=False,
        )
        return failed, LIFECYCLE_FAIL_CLOSED

    clock = monotonic or time.monotonic
    sleeper = sleep or time.sleep
    poster = rpc_post or json_rpc_post
    deadline = clock() + max(0.0, float(timeout_s))
    last: Receipt | None = None
    processed: Receipt | None = None
    polls = 0
    max_polls = 256

    while polls < max_polls:
        polls += 1
        remaining = deadline - clock()
        call_timeout = min(float(rpc_timeout_s), remaining if remaining > 0 else float(rpc_timeout_s))
        if call_timeout <= 0 and last is not None:
            break
        call_timeout = max(call_timeout, 0.1)
        last = status(
            sig,
            rpc_url=rpc,
            network=E2E_NETWORK.value,
            rpc_post=poster,
            timeout_s=call_timeout,
        )
        if last.fail_closed:
            if _is_not_found(last) and clock() < deadline:
                sleeper(max(0.0, float(interval_s)))
                continue
            return last, lifecycle_from_status(last)

        lifecycle = lifecycle_from_status(last)
        if lifecycle == LIFECYCLE_FAILED:
            return last, LIFECYCLE_FAILED
        if lifecycle == LIFECYCLE_FINALIZED:
            return last, LIFECYCLE_FINALIZED
        if last.confirmation_status == "confirmed":
            return last, lifecycle
        if last.confirmation_status == "processed":
            processed = last
            if clock() >= deadline:
                return processed, lifecycle
            sleeper(max(0.0, float(interval_s)))
            continue
        if clock() >= deadline:
            break
        sleeper(max(0.0, float(interval_s)))

    if processed is not None:
        return processed, lifecycle_from_status(processed)
    if last is None:
        last = Receipt(
            signature=sig,
            fail_closed=True,
            reasons=("status poll produced no observation; fail closed",),
            network=E2E_NETWORK.value,
            rpc_used=False,
        )
        return last, LIFECYCLE_FAIL_CLOSED
    if last.fail_closed:
        return last, LIFECYCLE_TIMEOUT
    return last, lifecycle_from_status(last)


def prepare_devnet_transfer(
    *,
    destination: str,
    amount: Decimal | str | int | float,
    rpc_url: str,
    network: Network | str | None = None,
    evaluate_fn: EvaluateFn | None = None,
    rpc_post: RpcPost | None = None,
    timeout_s: float = DEFAULT_RPC_TIMEOUT_S,
) -> PrepareResult:
    """Validate + firewall + bound handoff, forced onto DevNet with a tiny cap."""

    cluster = require_devnet(network)
    rpc = resolve_e2e_rpc_url(rpc_url)
    parsed_amount = parse_sol_amount(amount)
    intent = TransferIntent(
        network=cluster,
        asset="SOL",
        amount=parsed_amount,
        destination=destination,
        action="transfer",
        request_custody=False,
        server_sign=False,
        server_broadcast=False,
    )
    config = TransferConfig(max_amount_sol=PROOF_MAX_AMOUNT_SOL, rpc_url=rpc)
    result = prepare_transfer(
        intent,
        config=config,
        evaluate_fn=evaluate_fn,
        rpc_url=rpc,
        rpc_post=rpc_post,
        timeout_s=timeout_s,
    )
    if result.allowed:
        if result.approved_binding is None or result.approved_binding.network != E2E_NETWORK.value:
            return PrepareResult(
                decision=Decision.DENY,
                reasons=("approved binding is missing or not devnet; fail closed",),
                summary="Denied. DevNet E2E refused a non-devnet binding.",
                intent=result.intent,
                report=result.report,
                fee_status="e2e_fail_closed",
                fee_note="DevNet E2E refused a non-devnet binding",
            )
        if result.handoff_uri is None or "ai4-network=devnet" not in result.handoff_uri:
            return PrepareResult(
                decision=Decision.DENY,
                reasons=("handoff URI missing ai4-network=devnet; fail closed",),
                summary="Denied. DevNet E2E refused an unbound handoff.",
                intent=result.intent,
                report=result.report,
                fee_status="e2e_fail_closed",
                fee_note="DevNet E2E refused an unbound handoff",
            )
    return result


def run_devnet_e2e(
    *,
    destination: str,
    amount: Decimal | str | int | float,
    rpc_url: str | None,
    network: Network | str | None = None,
    signature: str | None = None,
    prepare_only: bool = False,
    evaluate_fn: EvaluateFn | None = None,
    rpc_post: RpcPost | None = None,
    timeout_s: float = DEFAULT_POLL_TIMEOUT_S,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
    rpc_timeout_s: float = DEFAULT_RPC_TIMEOUT_S,
    monotonic: MonotonicFn | None = None,
    sleep: SleepFn | None = None,
) -> DevnetE2EResult:
    """Library entrypoint for the DevNet E2E proof. Does not sign."""

    require_devnet(network)
    rpc = resolve_e2e_rpc_url(rpc_url)
    prepared = prepare_devnet_transfer(
        destination=destination,
        amount=amount,
        rpc_url=rpc,
        network=E2E_NETWORK,
        evaluate_fn=evaluate_fn,
        rpc_post=rpc_post,
        timeout_s=rpc_timeout_s,
    )
    if not prepared.allowed:
        receipt = build_ai4_receipt(
            prepared,
            lifecycle_state=LIFECYCLE_FAIL_CLOSED,
            extra_reasons=("prepare denied; no wallet handoff",),
        )
        return DevnetE2EResult(prepare=prepared, receipt=receipt)

    if prepare_only:
        receipt = build_ai4_receipt(prepared, lifecycle_state=LIFECYCLE_PREPARED)
        return DevnetE2EResult(prepare=prepared, receipt=receipt)

    if signature is None or not str(signature).strip():
        receipt = build_ai4_receipt(prepared, lifecycle_state=LIFECYCLE_AWAITING_BROADCAST)
        return DevnetE2EResult(prepare=prepared, receipt=receipt)

    observed, lifecycle = observe_devnet_status(
        signature,
        rpc_url=rpc,
        rpc_post=rpc_post,
        timeout_s=timeout_s,
        interval_s=interval_s,
        rpc_timeout_s=rpc_timeout_s,
        monotonic=monotonic,
        sleep=sleep,
    )
    receipt = build_ai4_receipt(
        prepared,
        lifecycle_state=lifecycle,
        status_receipt=observed,
        signature=observed.signature or signature,
    )
    return DevnetE2EResult(prepare=prepared, receipt=receipt, status_receipt=observed)


def e2e_option_strings(parser: argparse.ArgumentParser | None = None) -> tuple[str, ...]:
    target = parser or build_parser()
    options: list[str] = []
    for action in target._actions:
        options.extend(action.option_strings)
    return tuple(options)


def assert_no_secret_cli_flags(parser: argparse.ArgumentParser | None = None) -> None:
    options = [item.lower() for item in e2e_option_strings(parser)]
    joined = " ".join(options)
    for token in SECRET_OPTION_TOKENS:
        needle = f"--{token}"
        if needle in joined or needle.replace("_", "-") in joined:
            raise AssertionError(f"E2E CLI must not expose secret flag {token!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = DevnetE2EArgumentParser(
        prog="devnet_e2e",
        description=(
            "Solana DevNet-only E2E proof for ai4.transaction. "
            "Forces network=devnet. Amount cap "
            f"{PROOF_MAX_AMOUNT_SOL} SOL. Signing stays in your wallet. "
            "Pass --rpc-url or set AI4_SOLANA_RPC_URL. Public DevNet RPC "
            f"{PUBLIC_DEVNET_RPC_EXAMPLE} may be used (rate-limited). "
            "No private keys, seeds, or key files."
        ),
    )
    parser.add_argument("--destination", required=True, help="Solana destination address")
    parser.add_argument(
        "--amount",
        default=str(PROOF_DEFAULT_AMOUNT_SOL),
        help=(
            f"Positive SOL amount. Default {PROOF_DEFAULT_AMOUNT_SOL} SOL. "
            f"Cap {PROOF_MAX_AMOUNT_SOL} SOL for this proof."
        ),
    )
    parser.add_argument(
        "--network",
        default=E2E_NETWORK.value,
        help="Must be devnet. Any other value is rejected.",
    )
    parser.add_argument(
        "--rpc-url",
        default=None,
        help=(
            "Solana JSON-RPC URL. Overrides AI4_SOLANA_RPC_URL when equal or when "
            "env is unset. Differing values fail closed. Example (public, rate-limited): "
            f"{PUBLIC_DEVNET_RPC_EXAMPLE}"
        ),
    )
    parser.add_argument(
        "--signature",
        default=None,
        help="User-supplied transaction signature after the wallet broadcasts. Not a private key.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Stop after ALLOW handoff. Do not prompt for a signature.",
    )
    parser.add_argument(
        "--desktop-handoff-path",
        default=None,
        help=(
            "Where to write the desktop Phantom-extension HTML on ALLOW. "
            f"Default: examples/transaction/{DEFAULT_HANDOFF_FILENAME} when that "
            "directory exists, else ./ai4_desktop_handoff.html. Not a key file."
        ),
    )
    parser.add_argument(
        "--no-desktop-handoff",
        action="store_true",
        help="Do not write the desktop HTML file (Solana Pay URI is still printed).",
    )
    parser.add_argument(
        "--poll-timeout",
        default=str(DEFAULT_POLL_TIMEOUT_S),
        help="Seconds to poll status() after a signature is supplied.",
    )
    parser.add_argument(
        "--poll-interval",
        default=str(DEFAULT_POLL_INTERVAL_S),
        help="Seconds between status() polls.",
    )
    assert_no_secret_cli_flags(parser)
    return parser


def _print_json_block(title: str, payload: object, *, stream: TextIO) -> None:
    stream.write(f"=== {title} ===\n")
    stream.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    stream.write("\n")


def print_prepare_artifacts(
    prepare: PrepareResult,
    *,
    stream: TextIO = sys.stdout,
    desktop_handoff_path: str | None = None,
) -> None:
    report_payload = None if prepare.report is None else prepare.report.to_dict()
    _print_json_block("DecisionReport", report_payload, stream=stream)
    binding = None if prepare.approved_binding is None else prepare.approved_binding.to_dict()
    _print_json_block("Approved binding", binding, stream=stream)
    stream.write("=== Wallet handoff ===\n")
    stream.write(f"handoff_uri: {prepare.handoff_uri}\n")
    stream.write(f"phantom_browse_uri (MOBILE_ONLY): {prepare.phantom_browse_uri}\n")
    stream.write(PHANTOM_BROWSE_OWNER_NOTE + "\n")
    if desktop_handoff_path:
        path = Path(desktop_handoff_path)
        stream.write("=== Desktop handoff (Phantom Chrome extension) ===\n")
        stream.write(f"desktop_handoff_path: {path}\n")
        stream.write(f"desktop_handoff_file_uri: {path.resolve().as_uri()}\n")
        stream.write(
            "Phantom does not inject into file://. Serve on 127.0.0.1 then open in Chrome:\n"
        )
        stream.write(f"  {local_http_serve_command(path)}\n")
        stream.write(f"  open {local_http_open_url(path)}\n")
        stream.write(
            "Confirm Phantom is on Devnet. The page sends SystemProgram.transfer with "
            "the approved destination and lamports via window.phantom.solana."
            " Paste the public signature back to --signature. AI4 does not hold keys.\n"
        )
    stream.write(
        "Confirm the wallet cluster is Solana DevNet before you sign. "
        "AI4 does not hold keys or assets.\n"
    )
    stream.write(f"{ATTRIBUTION}\n")
    stream.write(
        "Residual risk: Solana Pay has no official cluster field. ai4-network=devnet "
        "is a binding marker; the wallet cluster is still a user setting.\n"
    )
    if prepare.summary:
        stream.write("--- prepare summary ---\n")
        stream.write(prepare.summary)
        stream.write("\n")


def print_receipt(receipt: AI4Receipt, *, stream: TextIO = sys.stdout) -> None:
    _print_json_block("AI4 receipt", receipt.to_dict(), stream=stream)
    stream.write("--- receipt summary ---\n")
    stream.write(format_ai4_receipt_summary(receipt))
    stream.write("\n")


def _prompt_signature(prompt: PromptFn) -> str:
    raw = prompt(
        "After your self-custodial wallet signs and broadcasts on DevNet, "
        "paste the transaction signature (not a private key): "
    )
    return parse_user_signature(raw)


def main(
    argv: list[str] | None = None,
    *,
    prompt: PromptFn | None = None,
    evaluate_fn: EvaluateFn | None = None,
    rpc_post: RpcPost | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        require_devnet(args.network)
        rpc = resolve_e2e_rpc_url(args.rpc_url)
        timeout_s = float(args.poll_timeout)
        interval_s = float(args.poll_interval)
        signature = args.signature
        if signature:
            signature = parse_user_signature(signature)

        result = run_devnet_e2e(
            destination=args.destination,
            amount=args.amount,
            rpc_url=rpc,
            network=args.network,
            signature=None if args.prepare_only else signature,
            prepare_only=bool(args.prepare_only),
            evaluate_fn=evaluate_fn,
            rpc_post=rpc_post,
            timeout_s=timeout_s,
            interval_s=interval_s,
        )
        desktop_path_text = None
        if (
            result.prepare is not None
            and result.prepare.allowed
            and result.prepare.approved_binding is not None
            and result.prepare.handoff_uri
            and not args.no_desktop_handoff
        ):
            target = (
                Path(args.desktop_handoff_path)
                if args.desktop_handoff_path
                else default_desktop_handoff_path()
            )
            written = write_desktop_handoff_html(
                target,
                result.prepare.approved_binding,
                rpc_url=rpc,
                handoff_uri=result.prepare.handoff_uri,
            )
            desktop_path_text = str(written)
            result = DevnetE2EResult(
                prepare=result.prepare,
                receipt=result.receipt,
                status_receipt=result.status_receipt,
                error=result.error,
                desktop_handoff_path=desktop_path_text,
            )
        if result.prepare is not None:
            print_prepare_artifacts(
                result.prepare,
                stream=out,
                desktop_handoff_path=desktop_path_text,
            )

        if result.prepare is not None and result.prepare.allowed and not args.prepare_only:
            if not signature:
                if prompt is None and not sys.stdin.isatty():
                    raise TransactionControlError(
                        "no signature supplied; fail closed",
                        reasons=(
                            "no --signature and stdin is not a TTY; pass --signature "
                            "after the wallet broadcasts, or use --prepare-only",
                        ),
                    )
                signature = _prompt_signature(prompt or input)
                result = run_devnet_e2e(
                    destination=args.destination,
                    amount=args.amount,
                    rpc_url=rpc,
                    network=args.network,
                    signature=signature,
                    prepare_only=False,
                    evaluate_fn=evaluate_fn,
                    rpc_post=rpc_post,
                    timeout_s=timeout_s,
                    interval_s=interval_s,
                )
                if result.prepare is not None:
                    # Avoid reprinting prepare artifacts; print status + receipt only.
                    pass
            if result.status_receipt is not None:
                out.write("=== status() observation ===\n")
                out.write(json.dumps(result.status_receipt.to_dict(), indent=2, ensure_ascii=False))
                out.write("\n")
                err.write(format_status_summary(result.status_receipt) + "\n")

        if result.receipt is not None:
            print_receipt(result.receipt, stream=out)
            if result.receipt.fail_closed or result.receipt.lifecycle_state == LIFECYCLE_FAILED:
                return EXIT_FAIL
            if result.prepare is not None and result.prepare.decision is not Decision.ALLOW:
                return EXIT_FAIL
            return EXIT_OK
        return EXIT_FAIL
    except TransactionValidationError as exc:
        err.write(str(exc) + "\n")
        if exc.reasons:
            err.write("Reasons: " + "; ".join(exc.reasons) + "\n")
        return EXIT_FAIL
    except TransactionControlError as exc:
        err.write(str(exc) + "\n")
        if exc.reasons:
            err.write("Reasons: " + "; ".join(exc.reasons) + "\n")
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
