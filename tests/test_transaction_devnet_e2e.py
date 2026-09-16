"""DevNet-only E2E entrypoint. CI must not touch a live chain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai4.transaction.desktop_handoff import (
    LIVE_PROOF_HTML_REPO_PATH,
    LIVE_PROOF_SHA256,
    live_proof_https_url,
)
from ai4.transaction.devnet_e2e import (
    EXIT_FAIL,
    EXIT_OK,
    PROOF_MAX_AMOUNT_SOL,
    PUBLIC_DEVNET_RPC_EXAMPLE,
    SECRET_OPTION_TOKENS,
    build_parser,
    e2e_option_strings,
    main,
    observe_devnet_status,
    prepare_devnet_transfer,
    require_devnet,
    resolve_e2e_rpc_url,
    run_devnet_e2e,
)
from ai4.transaction.errors import TransactionControlError, TransactionValidationError
from ai4.transaction.receipt import LIFECYCLE_FAILED, LIFECYCLE_FINALIZED, LIFECYCLE_PREPARED
from ai4.transaction.types import Decision, Network
from tests.transaction_util import fixture_report, solana_address, solana_signature

DEST = solana_address(23)
LIVE_DEST = "4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e"
SIG = solana_signature(11)
RPC = "https://rpc.example.test"
ROOT = Path(__file__).resolve().parents[1]


def _accept(_text: str):
    return fixture_report(decision="accept")


def _clock():
    state = {"t": 0.0}

    def monotonic() -> float:
        return state["t"]

    def sleep(seconds: float) -> None:
        state["t"] += float(seconds)

    return monotonic, sleep


def _rpc_prepare_ok(status_entry=None):
    def fake(_url, method, _params, _timeout):
        if method == "getLatestBlockhash":
            return {"result": {"value": {"blockhash": "11111111111111111111111111111111"}}}
        if method == "getRecentPrioritizationFees":
            return {"result": [{"slot": 1, "prioritizationFee": 1}]}
        if method == "getSignatureStatuses":
            if status_entry is None:
                raise AssertionError("status RPC should not run")
            return {"result": {"value": [status_entry]}}
        raise AssertionError(method)

    return fake


def test_require_devnet_accepts_devnet_and_blank():
    assert require_devnet("devnet") is Network.DEVNET
    assert require_devnet(Network.DEVNET) is Network.DEVNET
    assert require_devnet(None) is Network.DEVNET
    assert require_devnet("  ") is Network.DEVNET


@pytest.mark.parametrize("network", ["mainnet-beta", "localnet", "local", "localhost", "testnet", "ethereum"])
def test_require_devnet_rejects_non_devnet(network):
    with pytest.raises(TransactionValidationError) as exc:
        require_devnet(network)
    blob = " ".join(exc.value.reasons).lower()
    assert "devnet" in blob or "unsupported network" in blob or "not allowed" in blob


def test_run_e2e_rejects_mainnet_before_prepare(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    with pytest.raises(TransactionValidationError, match="non-devnet") as exc:
        run_devnet_e2e(
            destination=DEST,
            amount="0.001",
            rpc_url=RPC,
            network="mainnet-beta",
            prepare_only=True,
            evaluate_fn=_accept,
            rpc_post=_rpc_prepare_ok(),
        )
    assert any("mainnet-beta" in item for item in exc.value.reasons)


def test_cli_rejects_mainnet(monkeypatch, capsys):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    code = main(
        [
            "--destination",
            DEST,
            "--amount",
            "0.001",
            "--network",
            "mainnet-beta",
            "--rpc-url",
            RPC,
            "--prepare-only",
        ],
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    assert code == EXIT_FAIL
    err = capsys.readouterr().err
    assert "mainnet-beta" in err
    assert "devnet" in err.lower()


def test_cli_rejects_localnet(monkeypatch, capsys):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    code = main(
        [
            "--destination",
            DEST,
            "--network",
            "localnet",
            "--rpc-url",
            RPC,
            "--prepare-only",
        ],
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    assert code == EXIT_FAIL
    assert "localnet" in capsys.readouterr().err


def test_prepare_only_allow_prints_binding_and_uris(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    html_path = tmp_path / "ai4_desktop_handoff.html"
    code = main(
        [
            "--destination",
            DEST,
            "--amount",
            "0.001",
            "--rpc-url",
            RPC,
            "--prepare-only",
            "--desktop-handoff-path",
            str(html_path),
        ],
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "=== DecisionReport ===" in captured.out
    assert "=== Approved binding ===" in captured.out
    assert "=== AI4 receipt ===" in captured.out
    assert "sha256" in captured.out
    assert "ai4-network=devnet" in captured.out
    assert "phantom.app/ul/browse" in captured.out
    assert "MOBILE_ONLY" in captured.out
    assert "committed_html" in captured.out
    assert "Approve in Phantom" in captured.out
    assert "http://127.0.0.1" in captured.out
    assert "Prepared and constrained by AI4" in captured.out
    assert '"lifecycle_state": "prepared"' in captured.out
    assert '"network": "devnet"' in captured.out
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert DEST in html
    assert "1000000" in html
    assert "signAndSendTransaction" in html


def test_prepare_only_live_dest_prints_https_owner_url(monkeypatch, capsys):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    code = main(
        [
            "--destination",
            LIVE_DEST,
            "--amount",
            "0.001",
            "--rpc-url",
            RPC,
            "--prepare-only",
            "--no-desktop-handoff",
        ],
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert LIVE_PROOF_SHA256 in captured.out
    assert live_proof_https_url("<COMMIT_SHA>") in captured.out
    assert "rawcdn.githack.com" in captured.out
    assert LIVE_PROOF_HTML_REPO_PATH in captured.out
    assert "Owner HTTPS URL" in captured.out
    assert "python3 -m http.server" not in captured.out
    assert "jsdelivr.net" in captured.out


def test_handoff_binding_hash_survives_e2e_receipt(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    result = run_devnet_e2e(
        destination=DEST,
        amount="0.001",
        rpc_url=RPC,
        prepare_only=True,
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    assert result.prepare is not None and result.prepare.allowed
    assert result.receipt is not None
    assert result.receipt.approved_binding_hash == result.prepare.approved_binding.sha256()
    assert result.receipt.destination == result.prepare.approved_binding.destination
    assert result.receipt.lifecycle_state == LIFECYCLE_PREPARED


def test_unknown_signature_fail_closed(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    observed, lifecycle = observe_devnet_status(
        "not-a-signature",
        rpc_url=RPC,
        rpc_post=_rpc_prepare_ok(),
        timeout_s=1,
        interval_s=0,
        monotonic=lambda: 0.0,
        sleep=lambda _s: None,
    )
    assert observed.fail_closed is True
    assert observed.rpc_used is False
    assert lifecycle == "fail_closed"


def test_malformed_signature_rejected_as_secret_like(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    result = run_devnet_e2e(
        destination=DEST,
        amount="0.001",
        rpc_url=RPC,
        signature='{"privateKey": "00"}',
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
        timeout_s=1,
        interval_s=0,
    )
    assert result.receipt is not None
    assert result.receipt.fail_closed is True
    assert any("key" in item.lower() for item in result.receipt.reasons)


def test_rpc_timeout_fail_closed(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)

    def boom(_url, method, _params, _timeout):
        if method in {"getLatestBlockhash", "getRecentPrioritizationFees"}:
            return _rpc_prepare_ok()(_url, method, _params, _timeout)
        raise TransactionControlError("Solana RPC timed out; fail closed", reasons=("RPC timed out",))

    monotonic, sleep = _clock()
    result = run_devnet_e2e(
        destination=DEST,
        amount="0.001",
        rpc_url=RPC,
        signature=SIG,
        evaluate_fn=_accept,
        rpc_post=boom,
        timeout_s=4,
        interval_s=1,
        monotonic=monotonic,
        sleep=sleep,
    )
    assert result.receipt is not None
    assert result.receipt.fail_closed is True
    assert result.receipt.observed_success is False
    blob = " ".join(result.receipt.reasons).lower()
    assert "timed out" in blob or "timeout" in blob


def test_malformed_rpc_fail_closed(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)

    def malformed(_url, method, _params, _timeout):
        if method in {"getLatestBlockhash", "getRecentPrioritizationFees"}:
            return _rpc_prepare_ok()(_url, method, _params, _timeout)
        return {"result": "not-an-object"}

    result = run_devnet_e2e(
        destination=DEST,
        amount="0.001",
        rpc_url=RPC,
        signature=SIG,
        evaluate_fn=_accept,
        rpc_post=malformed,
        timeout_s=1,
        interval_s=0,
        monotonic=lambda: 0.0,
        sleep=lambda _s: None,
    )
    assert result.receipt is not None
    assert result.receipt.fail_closed is True
    assert result.receipt.lifecycle_state == "fail_closed"
    assert "not an object" in " ".join(result.receipt.reasons)


def test_failed_tx_not_reported_as_confirmed(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    fake = _rpc_prepare_ok(
        {"confirmationStatus": "confirmed", "slot": 4, "err": {"InstructionError": [0, "Custom"]}}
    )
    result = run_devnet_e2e(
        destination=DEST,
        amount="0.001",
        rpc_url=RPC,
        signature=SIG,
        evaluate_fn=_accept,
        rpc_post=fake,
        timeout_s=1,
        interval_s=0,
        monotonic=lambda: 0.0,
        sleep=lambda _s: None,
    )
    assert result.receipt is not None
    assert result.receipt.lifecycle_state == LIFECYCLE_FAILED
    assert result.receipt.observed_success is False
    assert result.receipt.error is not None
    assert result.receipt.to_dict()["lifecycle_state"] != "confirmed"


def test_finalized_represented_correctly(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    fake = _rpc_prepare_ok({"confirmationStatus": "finalized", "slot": 99, "err": None})
    result = run_devnet_e2e(
        destination=DEST,
        amount="0.001",
        rpc_url=RPC,
        signature=SIG,
        evaluate_fn=_accept,
        rpc_post=fake,
        timeout_s=1,
        interval_s=0,
        monotonic=lambda: 0.0,
        sleep=lambda _s: None,
    )
    assert result.receipt is not None
    assert result.receipt.lifecycle_state == LIFECYCLE_FINALIZED
    assert result.receipt.confirmation_status == "finalized"
    assert result.receipt.slot == 99
    assert result.receipt.fail_closed is False
    assert result.receipt.observed_success is True
    assert result.receipt.explorer_url is not None
    assert "cluster=devnet" in result.receipt.explorer_url
    assert SIG in result.receipt.explorer_url


def test_no_silent_public_rpc_default(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    with pytest.raises(TransactionControlError, match="no Solana RPC URL"):
        resolve_e2e_rpc_url(None)
    with pytest.raises(TransactionControlError, match="no Solana RPC URL"):
        prepare_devnet_transfer(
            destination=DEST,
            amount="0.001",
            rpc_url="",
            evaluate_fn=_accept,
            rpc_post=_rpc_prepare_ok(),
        )


def test_rpc_ambiguity_fail_closed(monkeypatch):
    monkeypatch.setenv("AI4_SOLANA_RPC_URL", "https://env.example.test")
    with pytest.raises(TransactionControlError, match="ambiguous"):
        resolve_e2e_rpc_url("https://arg.example.test")


def test_mainnet_rpc_host_rejected():
    with pytest.raises(TransactionControlError, match="mainnet"):
        resolve_e2e_rpc_url("https://api.mainnet-beta.solana.com")


def test_localhost_rpc_host_rejected():
    with pytest.raises(TransactionControlError, match="localnet"):
        resolve_e2e_rpc_url("http://127.0.0.1:8899")


def test_amount_cap_is_tiny(monkeypatch):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    assert PROOF_MAX_AMOUNT_SOL == __import__("decimal").Decimal("0.01")
    result = run_devnet_e2e(
        destination=DEST,
        amount="0.02",
        rpc_url=RPC,
        prepare_only=True,
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    assert result.prepare is not None
    assert result.prepare.decision is Decision.DENY
    assert result.receipt is not None
    assert result.receipt.fail_closed is True
    assert any("exceeds cap" in item for item in result.prepare.reasons)


def test_no_secret_private_key_cli_flags():
    options = [item.lower() for item in e2e_option_strings()]
    joined = " ".join(options)
    for token in SECRET_OPTION_TOKENS:
        assert f"--{token}" not in joined
        assert f"--{token.replace('_', '-')}" not in joined
    dests = [getattr(action, "dest", "") for action in build_parser()._actions]
    lowered = [str(item).lower() for item in dests]
    for banned in ("private_key", "secret", "seed", "keypair", "mnemonic", "keyfile"):
        assert banned not in lowered


def test_example_and_library_source_have_no_secret_flags():
    paths = [
        ROOT / "ai4" / "transaction" / "devnet_e2e.py",
        ROOT / "examples" / "transaction" / "devnet_e2e.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in (
            "--private-key",
            "--secret-key",
            "--keypair",
            "--keyfile",
            "--mnemonic",
            "--seed",
            "--wif",
        ):
            assert token not in text


def test_public_rpc_example_is_documented_not_default():
    help_text = build_parser().format_help()
    assert PUBLIC_DEVNET_RPC_EXAMPLE in help_text
    source = (ROOT / "ai4" / "transaction" / "devnet_e2e.py").read_text(encoding="utf-8")
    assert "silent" in source.lower() or "never inferred" in source or "hardcoded default" in source


def test_cli_prepare_only_json_receipt_is_parseable(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("AI4_SOLANA_RPC_URL", raising=False)
    code = main(
        [
            "--destination",
            DEST,
            "--rpc-url",
            RPC,
            "--prepare-only",
            "--desktop-handoff-path",
            str(tmp_path / "ai4_desktop_handoff.html"),
        ],
        evaluate_fn=_accept,
        rpc_post=_rpc_prepare_ok(),
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    chunk = out.split("=== AI4 receipt ===", 1)[1]
    json_text = chunk.split("--- receipt summary ---", 1)[0].strip()
    payload = json.loads(json_text)
    assert payload["network"] == "devnet"
    assert payload["lifecycle_state"] == "prepared"
    assert payload["attribution"].startswith("Prepared and constrained by AI4")
