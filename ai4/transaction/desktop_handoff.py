"""Desktop Phantom extension handoff (injected provider). Not a Universal Link.

Phantom ``https://phantom.app/ul/browse/...`` is a **mobile** deeplink
(iOS/Android in-app browser). The Chrome/desktop extension does not consume
it. Desktop signing uses ``window.phantom.solana`` (or legacy
``window.solana``) on a page served at https, localhost, or 127.0.0.1.

This module renders a self-contained HTML page that asks Phantom to
``signAndSendTransaction`` a ``SystemProgram.transfer`` using the **exact**
approved destination and lamports. AI4 never sees keys. The page does not
sign; the user's extension does.

The owner click-path is an HTTPS URL that serves the committed HTML as
``text/html`` (Phantom injects). jsDelivr currently serves the same GitHub
blob as ``text/plain`` with ``nosniff``, so Chrome will not execute it.
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
GITHUB_REPO = "TheSingulant/ai4-constrain"
LIVE_PROOF_DESTINATION = "4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e"
LIVE_PROOF_AMOUNT_SOL = "0.001"
LIVE_PROOF_LAMPORTS = 1_000_000
LIVE_PROOF_SHA256 = "fe30e76ac25e766f37d4f719caaa7efa7b2603afbf388dbca609154258a37da0"
LIVE_PROOF_RPC_URL = "https://api.devnet.solana.com"
LIVE_PROOF_HTML_REPO_PATH = "examples/transaction/live_proof/fe30e76a_devnet_handoff.html"

PHANTOM_BROWSE_CHANNEL = "mobile_only"
PHANTOM_BROWSE_OWNER_NOTE = (
    "MOBILE_ONLY: https://phantom.app/ul/browse/<url> is a Phantom iOS/Android "
    "in-app browser Universal Link. The Chrome/desktop extension does not consume "
    "it and commonly redirects to phantom.com/download while the extension stays idle. "
    "Desktop owner path: open the committed HTTPS HTML handoff in Chrome with Phantom "
    f"({LIVE_PROOF_HTML_REPO_PATH}, HTML MIME CDN). "
    "http://127.0.0.1 is an optional offline/dev fallback only."
)


def _require_commit_sha(commit_sha: str) -> str:
    sha = str(commit_sha).strip()
    if not sha:
        raise TransactionControlError(
            "commit SHA is required for the HTTPS handoff URL",
            reasons=("commit SHA is required for the HTTPS handoff URL",),
        )
    return sha


def live_proof_https_url(commit_sha: str) -> str:
    """Owner click-path: same GitHub blob served as ``text/html`` over HTTPS.

    Phantom injects only when the document is executed as HTML.
    ``cdn.jsdelivr.net/gh`` currently serves this file as ``text/plain`` with
    ``X-Content-Type-Options: nosniff``, so Chrome will not run it as a page.
    ``rawcdn.githack.com`` serves the commit path as ``text/html``.
    """
    sha = _require_commit_sha(commit_sha)
    return f"https://rawcdn.githack.com/{GITHUB_REPO}/{sha}/{LIVE_PROOF_HTML_REPO_PATH}"


def live_proof_jsdelivr_url(commit_sha: str) -> str:
    sha = _require_commit_sha(commit_sha)
    return f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@{sha}/{LIVE_PROOF_HTML_REPO_PATH}"


def live_proof_github_blob_url(commit_sha: str) -> str:
    sha = _require_commit_sha(commit_sha)
    return f"https://github.com/{GITHUB_REPO}/blob/{sha}/{LIVE_PROOF_HTML_REPO_PATH}"


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
  <p><strong>Desktop owner path:</strong> open this page over <strong>HTTPS</strong>
  in Chrome with the Phantom <em>extension</em>. Phantom injects
  <code>window.phantom.solana</code> on https / localhost / 127.0.0.1 —
  not on <code>file://</code>, and not via <code>https://phantom.app/ul/browse/...</code>
  (that Universal Link is <strong>MOBILE_ONLY</strong>).
  <code>http://127.0.0.1</code> is an optional offline/dev fallback only.</p>
  <div class="warn">
    <strong>Before you click:</strong> in Phantom, set the cluster to
    <strong>Devnet</strong>. This page cannot lock the extension cluster.
    Confirm destination and lamports match the approved binding below.
    Click <em>Approve in Phantom</em> (user gesture) and approve in Phantom's dialog.
    AI4 does not hold keys or assets. This page has no seed or key fields.
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
  <p><button id="send" type="button">Approve in Phantom</button></p>
  <p class="ok" id="status"></p>
  <p>Public transaction signature (shown only after Phantom's dialog returns; paste back to AI4 <code>--signature</code>):</p>
  <textarea id="sig" readonly placeholder="(none yet — waiting for Phantom dialog)"></textarea>
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
      fail("Phantom extension not detected. Open this HTTPS page in Chrome with Phantom installed. Do not use file://. Do not use phantom.app/ul/browse (MOBILE_ONLY). This page never asks for a key.");
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
      "Phantom dialog returned a public signature. AI4 did not sign and does not poll status from this page. Paste the signature into AI4 --signature if you want a receipt.";
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
