"""Desktop injected-provider handoff vs mobile Phantom browse UL."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ai4.transaction.binding import verify_solana_pay_binding
from ai4.transaction.desktop_handoff import (
    DEVNET_GENESIS_HASH,
    LIVE_PROOF_HTML_REPO_PATH,
    LIVE_PROOF_SHA256,
    PHANTOM_BROWSE_CHANNEL,
    PHANTOM_BROWSE_OWNER_NOTE,
    render_desktop_handoff_html,
    write_desktop_handoff_html,
)
from ai4.transaction.errors import TransactionControlError
from ai4.transaction.handoff import phantom_browse_uri, solana_pay_transfer_uri
from ai4.transaction.types import ApprovedBinding, NormalizedIntent, Network, Asset
from ai4.transaction.validate import validate_solana_address
from tests.transaction_util import solana_address

LIVE_DEST = "4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e"
LIVE_HASH = "fe30e76ac25e766f37d4f719caaa7efa7b2603afbf388dbca609154258a37da0"
DEST = solana_address(23)
RPC = "https://rpc.example.test"


def _live_binding() -> ApprovedBinding:
    return ApprovedBinding(
        network="devnet",
        asset="SOL",
        action="transfer",
        amount_sol="0.001",
        lamports=1_000_000,
        destination=LIVE_DEST,
    )


def test_live_proof_binding_hash_unchanged():
    assert validate_solana_address(LIVE_DEST) == LIVE_DEST
    assert _live_binding().sha256() == LIVE_HASH
    assert LIVE_HASH == LIVE_PROOF_SHA256


def test_phantom_browse_is_labeled_mobile_only():
    assert PHANTOM_BROWSE_CHANNEL == "mobile_only"
    assert "MOBILE_ONLY" in PHANTOM_BROWSE_OWNER_NOTE
    assert "Chrome/desktop extension does not consume" in PHANTOM_BROWSE_OWNER_NOTE
    inner = solana_pay_transfer_uri(DEST, Decimal("0.001"), network="devnet")
    browse = phantom_browse_uri(inner)
    assert browse.startswith("https://phantom.app/ul/browse/")
    assert phantom_browse_uri.__doc__ is not None
    assert "MOBILE_ONLY" in phantom_browse_uri.__doc__
    assert "Chrome/desktop" in phantom_browse_uri.__doc__


def test_solana_pay_uri_still_verifies_against_binding():
    dest = validate_solana_address(LIVE_DEST)
    intent = NormalizedIntent(
        network=Network.DEVNET,
        asset=Asset.SOL,
        amount=Decimal("0.001"),
        destination=dest,
        lamports=1_000_000,
        action="transfer",
    )
    uri = solana_pay_transfer_uri(dest, Decimal("0.001"), network="devnet")
    verify_solana_pay_binding(uri, intent)
    assert uri.startswith(f"solana:{dest}?")
    assert "ai4-network=devnet" in uri
    assert "amount=0.001" in uri


def test_desktop_html_embeds_exact_binding_fields(tmp_path: Path):
    binding = _live_binding()
    uri = solana_pay_transfer_uri(LIVE_DEST, Decimal("0.001"), network="devnet")
    html = render_desktop_handoff_html(
        binding,
        rpc_url="https://api.devnet.solana.com",
        handoff_uri=uri,
    )
    assert LIVE_DEST in html
    assert "1000000" in html
    assert '"network":"devnet"' in html or '"network": "devnet"' in html
    assert LIVE_HASH in html
    assert '"lamports":1000000' in html
    assert "SystemProgram.transfer" in html
    assert "signAndSendTransaction" in html
    assert "window.phantom" in html
    assert DEVNET_GENESIS_HASH in html
    assert "Approve in Phantom" in html
    assert "https" in html
    assert "MOBILE_ONLY" in html
    assert uri in html
    path = write_desktop_handoff_html(
        tmp_path / "ai4_desktop_handoff.html",
        binding,
        rpc_url="https://api.devnet.solana.com",
        handoff_uri=uri,
    )
    saved = path.read_text(encoding="utf-8")
    assert LIVE_HASH in saved
    assert binding.destination in saved


def test_desktop_html_has_no_secret_prompts():
    html = render_desktop_handoff_html(
        _live_binding(),
        rpc_url="https://api.devnet.solana.com",
        handoff_uri="solana:x",
    )
    lowered = html.lower()
    assert "<input" not in lowered
    assert 'type="password"' not in lowered
    assert "prompt(" not in html
    assert "<textarea id=\"sig\" readonly" in html or "<textarea id='sig' readonly" in html
    assert "--private-key" not in html
    assert "--seed" not in html
    assert "BEGIN PRIVATE KEY" not in html


def test_desktop_html_refuses_mainnet_binding():
    binding = ApprovedBinding(
        network="mainnet-beta",
        asset="SOL",
        action="transfer",
        amount_sol="0.001",
        lamports=1_000_000,
        destination=DEST,
    )
    with pytest.raises(TransactionControlError, match="DevNet-only"):
        render_desktop_handoff_html(
            binding,
            rpc_url="https://api.devnet.solana.com",
            handoff_uri="solana:x",
        )


def test_committed_https_live_proof_html_bakes_binding():
    path = Path(__file__).resolve().parents[1] / LIVE_PROOF_HTML_REPO_PATH
    assert path.is_file()
    html = path.read_text(encoding="utf-8")
    assert LIVE_DEST in html
    assert "1000000" in html
    assert LIVE_HASH in html
    assert "devnet" in html
    assert "Approve in Phantom" in html
    assert "signAndSendTransaction" in html
    assert "SystemProgram.transfer" in html
    assert "<input" not in html.lower()
    assert 'type="password"' not in html.lower()
    assert "--private-key" not in html
    assert "--seed" not in html
    assert "BEGIN PRIVATE KEY" not in html
    assert html.count("Approve in Phantom") >= 1


def test_desktop_html_refuses_mainnet_rpc_host():
    with pytest.raises(TransactionControlError, match="mainnet"):
        render_desktop_handoff_html(
            _live_binding(),
            rpc_url="https://api.mainnet-beta.solana.com",
            handoff_uri="solana:x",
        )
