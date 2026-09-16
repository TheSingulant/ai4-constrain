"""Desktop Phantom extension handoff (injected provider). Not a Universal Link.

Phantom ``https://phantom.app/ul/browse/...`` is a **mobile** deeplink
(iOS/Android in-app browser). The Chrome/desktop extension does not consume
it. Desktop signing uses ``window.phantom.solana`` (or legacy
``window.solana``) on a page served at https, localhost, or 127.0.0.1.

This module renders a self-contained HTML page that asks Phantom to
``signAndSendTransaction`` a ``SystemProgram.transfer`` using the **exact**
approved destination and lamports. AI4 never sees keys. The page does not
sign; the user's extension does.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from ai4.transaction.errors import TransactionControlError
from ai4.transaction.receipt import ATTRIBUTION
from ai4.transaction.rpc import validate_rpc_url
from ai4.transaction.types import ApprovedBinding, Network

# Public Solana DevNet genesis hash. Used as a fail-closed RPC cluster check.
DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
WEB3_CDN = "https://unpkg.com/@solana/web3.js@1.98.4/lib/index.iife.min.js"
DEFAULT_HANDOFF_FILENAME = "ai4_desktop_handoff.html"
DEFAULT_SERVE_PORT = 8765

PHANTOM_BROWSE_CHANNEL = "mobile_only"
PHANTOM_BROWSE_OWNER_NOTE = (
    "MOBILE_ONLY: https://phantom.app/ul/browse/<url> is a Phantom iOS/Android "
    "in-app browser Universal Link. The Chrome/desktop extension does not consume "
    "it and commonly redirects to phantom.com/download while the extension stays idle. "
    "Desktop owners must use the injected-provider HTML handoff on http://127.0.0.1."
)


def default_desktop_handoff_path() -> Path:
    examples = Path(__file__).resolve().parents[2] / "examples" / "transaction" / DEFAULT_HANDOFF_FILENAME
    if examples.parent.is_dir():
        return examples
    return Path.cwd() / DEFAULT_HANDOFF_FILENAME


def local_http_open_url(path: Path, *, port: int = DEFAULT_SERVE_PORT) -> str:
    return f"http://127.0.0.1:{port}/{path.name}"


def local_http_serve_command(path: Path, *, port: int = DEFAULT_SERVE_PORT) -> str:
    from shlex import quote

    directory = quote(str(path.resolve().parent))
    return f"python3 -m http.server {port} --bind 127.0.0.1 --directory {directory}"


def render_desktop_handoff_html(
    binding: ApprovedBinding,
    *,
    rpc_url: str,
    handoff_uri: str,
) -> str:
    """Render a self-contained DevNet desktop handoff page.

    Destination, lamports, network, and sha256 are taken from ``binding``.
    Refuses non-devnet bindings and credentialed / mainnet-looking RPC URLs.
    """

    if binding.network != Network.DEVNET.value:
        raise TransactionControlError(
            "desktop handoff is DevNet-only",
            reasons=(f"approved binding network is {binding.network!r}, not devnet",),
        )
    if binding.action != "transfer" or binding.asset != "SOL":
        raise TransactionControlError(
            "desktop handoff is native SOL transfer only",
            reasons=("desktop handoff requires asset=SOL action=transfer",),
        )
    if not isinstance(binding.lamports, int) or binding.lamports <= 0:
        raise TransactionControlError(
            "desktop handoff lamports are invalid",
            reasons=("approved binding lamports must be a positive int",),
        )
    safe_rpc = validate_rpc_url(rpc_url)
    host = safe_rpc.lower()
    if "mainnet" in host:
        raise TransactionControlError(
            "desktop handoff RPC looks like mainnet; fail closed",
            reasons=("desktop handoff RPC host looks like mainnet; refuse",),
        )
    payload = {
        "network": binding.network,
        "asset": binding.asset,
        "action": binding.action,
        "amountSol": binding.amount_sol,
        "lamports": binding.lamports,
        "destination": binding.destination,
        "sha256": binding.sha256(),
        "rpcUrl": safe_rpc,
        "handoffUri": handoff_uri,
        "devnetGenesisHash": DEVNET_GENESIS_HASH,
        "attribution": ATTRIBUTION,
    }
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    if "</script" in blob.lower():
        raise TransactionControlError(
            "desktop handoff payload failed closed",
            reasons=("binding JSON would break the HTML script tag; refuse",),
        )
    dest_h = escape(binding.destination, quote=True)
    amount_h = escape(binding.amount_sol, quote=True)
    hash_h = escape(binding.sha256(), quote=True)
    rpc_h = escape(safe_rpc, quote=True)
    uri_h = escape(handoff_uri, quote=True)
    note_h = escape(ATTRIBUTION, quote=True)
    return _TEMPLATE.format(
        binding_json=blob,
        destination_html=dest_h,
        amount_html=amount_h,
        lamports_html=str(binding.lamports),
        hash_html=hash_h,
        rpc_html=rpc_h,
        uri_html=uri_h,
        attribution_html=note_h,
        web3_cdn=WEB3_CDN,
        genesis=DEVNET_GENESIS_HASH,
    )


def write_desktop_handoff_html(
    path: Path,
    binding: ApprovedBinding,
    *,
    rpc_url: str,
    handoff_uri: str,
) -> Path:
    target = Path(path)
    html = render_desktop_handoff_html(binding, rpc_url=rpc_url, handoff_uri=handoff_uri)
    target.write_text(html, encoding="utf-8")
    return target.resolve()


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AI4 DevNet desktop handoff (Phantom extension)</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; color: #111; }}
    code, pre {{ font-family: ui-monospace, monospace; font-size: 0.85rem; word-break: break-all; }}
    .warn {{ background: #fff3cd; border: 1px solid #ffc107; padding: 0.9rem 1rem; }}
    .box {{ background: #f6f7f9; border: 1px solid #d0d7de; padding: 0.9rem 1rem; margin: 1rem 0; }}
    button {{ font-size: 1rem; padding: 0.6rem 1rem; cursor: pointer; }}
    #sig {{ width: 100%; min-height: 4rem; }}
    .ok {{ color: #0b6e32; }}
    .err {{ color: #a40e26; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>AI4 DevNet desktop handoff</h1>
  <p>{attribution_html}</p>
  <p><strong>Desktop owner path:</strong> Chrome with the Phantom <em>extension</em>,
  this page served at <code>http://127.0.0.1</code>. Phantom injects
  <code>window.phantom.solana</code> on https / localhost / 127.0.0.1 only —
  not on <code>file://</code>, and not via <code>https://phantom.app/ul/browse/...</code>
  (that Universal Link is <strong>MOBILE_ONLY</strong>).</p>
  <div class="warn">
    <strong>Before you click:</strong> in Phantom, set the cluster to
    <strong>Devnet</strong> (Testnet/Devnet). This page cannot lock the extension
    cluster. Confirm destination and lamports match the approved binding.
    AI4 does not hold keys or assets. Never paste a seed or private key here.
  </div>
  <h2>Approved binding (visual confirm)</h2>
  <div class="box">
    <div>network: <code>devnet</code></div>
    <div>asset: <code>SOL</code></div>
    <div>action: <code>transfer</code></div>
    <div>amount: <code>{amount_html}</code> SOL</div>
    <div>lamports: <code>{lamports_html}</code></div>
    <div>destination: <code>{destination_html}</code></div>
    <div>sha256: <code>{hash_html}</code></div>
    <div>rpc: <code>{rpc_html}</code></div>
  </div>
  <h2>Frozen Solana Pay URI (mobile / QR; not the desktop path)</h2>
  <pre>{uri_html}</pre>
  <p><button id="send" type="button">Connect Phantom and send the approved DevNet transfer</button></p>
  <p class="ok" id="status"></p>
  <p>Public transaction signature (paste back to AI4 <code>--signature</code>):</p>
  <textarea id="sig" readonly placeholder="(none yet — AI4 never fills this)"></textarea>
  <p class="err" id="err"></p>
  <script src="{web3_cdn}"></script>
  <script>
  const AI4 = {binding_json};
  const DEVNET_GENESIS = "{genesis}";

  function getProvider() {{
    const phantom = window.phantom && window.phantom.solana;
    if (phantom && phantom.isPhantom) return phantom;
    if (window.solana && window.solana.isPhantom) return window.solana;
    return null;
  }}

  function fail(msg) {{
    document.getElementById("err").textContent = msg;
    document.getElementById("status").textContent = "";
  }}

  async function sendApproved() {{
    document.getElementById("err").textContent = "";
    document.getElementById("sig").value = "";
    if (!window.solanaWeb3) {{
      fail("solanaWeb3 CDN failed to load; refuse.");
      return;
    }}
    if (AI4.network !== "devnet") {{
      fail("Binding network is not devnet; refuse.");
      return;
    }}
    if (typeof AI4.lamports !== "number" || AI4.lamports <= 0 || !Number.isInteger(AI4.lamports)) {{
      fail("Binding lamports are not a positive integer; refuse.");
      return;
    }}
    const provider = getProvider();
    if (!provider) {{
      fail("Phantom extension not detected. Open this page at http://127.0.0.1 (python3 -m http.server --bind 127.0.0.1). Do not use file://. Do not use phantom.app/ul/browse (MOBILE_ONLY). Never paste a private key.");
      return;
    }}
    const connection = new solanaWeb3.Connection(AI4.rpcUrl, "confirmed");
    const genesis = await connection.getGenesisHash();
    if (genesis !== DEVNET_GENESIS) {{
      fail("RPC genesis hash is not Solana DevNet; refuse. Phantom cluster is still a user setting — switch Phantom to Devnet.");
      return;
    }}
    const resp = await provider.connect();
    const from = provider.publicKey || (resp && resp.publicKey);
    if (!from) {{
      fail("Phantom did not return a public key; refuse.");
      return;
    }}
    const to = new solanaWeb3.PublicKey(AI4.destination);
    if (to.toBase58() !== AI4.destination) {{
      fail("Destination pubkey round-trip mismatch; refuse.");
      return;
    }}
    const ix = solanaWeb3.SystemProgram.transfer({{
      fromPubkey: from,
      toPubkey: to,
      lamports: AI4.lamports
    }});
    const tx = new solanaWeb3.Transaction().add(ix);
    tx.feePayer = from;
    const latest = await connection.getLatestBlockhash("finalized");
    tx.recentBlockhash = latest.blockhash;
    const sent = await provider.signAndSendTransaction(tx);
    const signature = sent && sent.signature ? sent.signature : sent;
    if (!signature || typeof signature !== "string") {{
      fail("Phantom did not return a public signature; refuse.");
      return;
    }}
    document.getElementById("sig").value = signature;
    document.getElementById("status").textContent =
      "Broadcast requested. Copy the public signature below and pass it to AI4 --signature. AI4 did not sign.";
  }}

  document.getElementById("send").addEventListener("click", function () {{
    sendApproved().catch(function (err) {{
      fail(String(err && err.message ? err.message : err));
    }});
  }});
  </script>
</body>
</html>
"""
