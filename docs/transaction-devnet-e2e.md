# Solana DevNet E2E proof (`ai4.transaction`)

Scaffold / unreleased feature work. Package version remains **0.7.0**. This is
not a PyPI release of transaction features, not a Telegram bot, and not a
server wallet.

The harness proves one vertical slice on **Solana DevNet only**:

```
user intent
  → validate
  → ai4.constrain Transaction Firewall
  → DecisionReport ALLOW
  → bound wallet handoff (Solana Pay URI + desktop HTML; browse UL is MOBILE_ONLY)
  → human signs in a self-custodial wallet
  → wallet broadcasts on devnet
  → status() observes lifecycle
  → AI4 receipt
```

AI4 prepares and constrains. The user wallet signs and broadcasts.
Wording on every receipt:

> Prepared and constrained by AI4; signed and broadcast by the user's wallet.

Never claim AI4 executed the transfer.

## Safety locks

| Lock | Behavior |
| --- | --- |
| Network | Live E2E path **forces `network=devnet`**. `mainnet-beta`, `localnet`, and any other cluster are rejected before prepare. |
| Amount | Proof cap **≤ 0.01 SOL**. CLI default **0.001 SOL**. |
| Keys | No seeds, private keys, key files, or signing automation. No CLI flags for secrets. |
| RPC | No hardcoded RPC and no credentialed URLs. Pass `--rpc-url` or set `AI4_SOLANA_RPC_URL`. If both are set and they **differ**, fail closed. Hosts that look like mainnet or localhost are refused. |
| Signing | Desktop: local HTML + Phantom **extension** injected provider (`window.phantom.solana`). Mobile: Solana Pay URI / Phantom browse UL. AI4 never signs. |

Architecture for the broader scaffold (including mainnet-capable `prepare`,
which this E2E path must not use) is in
[`transaction-control.md`](transaction-control.md).

## RPC

There is **no silent public RPC default**. Operators must pass a URL.

Public Solana DevNet JSON-RPC may be used for tests:

```text
https://api.devnet.solana.com
```

Rate limits apply. Transport errors, non-JSON bodies, missing `result`, and
ambiguous status shapes **fail closed**. Do not embed API keys in the URL.

`.env.example` documents empty `AI4_SOLANA_RPC_URL=`. Copy locally; never
commit a live URL with credentials.

## How to run

From a clone, with the package installed editable (`pip install -e ".[dev]"`):

### 1. Prepare only (no signing)

```bash
python examples/transaction/devnet_e2e.py \
  --destination <solana-address> \
  --amount 0.001 \
  --rpc-url https://api.devnet.solana.com \
  --prepare-only
```

`--network` defaults to `devnet`. Any other value is rejected.

Stdout prints:

1. DecisionReport JSON
2. Approved binding (including `sha256`)
3. Solana Pay `handoff_uri` (frozen transfer request)
4. Phantom `phantom_browse_uri` labeled **MOBILE_ONLY**
5. Desktop handoff path + `http://127.0.0.1` serve command
6. Structured AI4 receipt with `lifecycle_state=prepared` (no signature)

### Desktop vs mobile handoff

| Path | What | Who |
| --- | --- | --- |
| Solana Pay `solana:<dest>?amount=...&ai4-network=devnet` | Wallet-agnostic transfer request. Mobile wallets register the scheme or scan a QR. | Mobile / QR |
| `https://phantom.app/ul/browse/<url>` | Phantom **iOS/Android** in-app browser Universal Link. **Not** consumed by the Chrome/desktop extension (often redirects to phantom.com/download). | **MOBILE_ONLY** |
| Generated `ai4_desktop_handoff.html` served at `http://127.0.0.1` | Chrome + Phantom **extension**. Uses `window.phantom.solana` / `window.solana`, `SystemProgram.transfer` with **exact** approved destination + lamports, then `signAndSendTransaction`. Shows the public signature to paste back. | **Desktop owner path** |

Phantom injects the provider on `https://`, `localhost`, and `127.0.0.1` only — **not** `file://`. After prepare-only:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory examples/transaction
# open http://127.0.0.1:8765/ai4_desktop_handoff.html in Chrome with Phantom
```

Switch Phantom to **Devnet** before clicking send. The page cannot lock the extension cluster.

### 2. Sign in your wallet (owner)

**Desktop (Chrome extension) — owner path:**

1. Confirm Phantom's cluster is **Solana Devnet**.
2. Serve and open the generated HTML at `http://127.0.0.1` as printed by the harness.
3. Confirm destination, lamports, and binding `sha256` on the page.
4. Click connect/send. Phantom signs and broadcasts. Copy the **public** signature.

**Mobile:** open the Solana Pay URI or the MOBILE_ONLY browse UL in Phantom's iOS/Android app. Do not use the browse UL as the desktop path.

AI4 must never see a seed, private key, or keystore file. Do not "type Send" in Phantom as a substitute for the injected-provider page.

### 3. Observe lifecycle

```bash
python examples/transaction/devnet_e2e.py \
  --destination <same-address> \
  --amount 0.001 \
  --rpc-url https://api.devnet.solana.com \
  --signature <user-supplied-signature>
```

The harness polls `status(signature, rpc_url=..., network="devnet")` until
`processed`, `confirmed`, `finalized`, on-chain error (`failed`), fail-closed,
or timeout. `processed` keeps polling toward confirmed/finalized while time
remains.

An interactive TTY without `--signature` prompts for the public signature
after prepare. Non-TTY sessions must pass `--signature` or `--prepare-only`.

Equivalent library entry: `ai4.transaction.devnet_e2e.run_devnet_e2e`.

## Receipt fields

`ai4.transaction.receipt.AI4Receipt` includes at least:

| Field | Role |
| --- | --- |
| `network` | Always `devnet` for this receipt type |
| `asset` | `SOL` |
| `action` | `transfer` |
| `amount` | Approved SOL amount |
| `destination` | Approved address |
| `approved_binding_hash` | SHA-256 of the canonical approved binding |
| `decision_report_summary` / `decision_report_result` | Compact constrain outcome |
| `signature` | User-supplied public signature, or null on prepare-only |
| `lifecycle_state` | `prepared` / `awaiting_broadcast` / `processed` / `confirmed` / `finalized` / `failed` / `fail_closed` / `timeout` |
| `confirmation_status` | RPC `confirmationStatus` when observed |
| `slot` | RPC slot when observed |
| `error` | On-chain error object, if any |
| `timestamp` | UTC |
| `explorer_url` | `https://explorer.solana.com/tx/<sig>?cluster=devnet` only when a signature exists |

A failed on-chain transaction is **not** represented as a successful
confirmation (`lifecycle_state=failed`, `observed_success=false`).
Finalized observations require `confirmation_status=finalized`.

## Residual risk (`ai4-network` / wallet cluster)

Solana Pay has **no official cluster field**. This scaffold adds
non-standard `ai4-network=devnet` so the URI can be parsed back to the
approved cluster (binding integrity / audit). Wallets ignore that query
parameter. **The wallet cluster remains a user setting.** A user can still
sign on the wrong cluster.

`status()` observes signature lifecycle on the RPC you supplied. It does not
re-decode the on-chain instruction against the approved binding. A custom RPC
that is not obviously mainnet/localhost can still point at another cluster.

These are disclosed residual risks, not solved chain locks.

## Evidence checklist (first live proof)

Fill [`examples/transaction/LIVE_EVIDENCE.md`](../examples/transaction/LIVE_EVIDENCE.md).
Do not invent a live signature or explorer link.

- [ ] PR URL and commit SHA
- [ ] Package version **0.7.0** (unchanged)
- [ ] DecisionReport (`accept` / product `ALLOW`)
- [ ] Approved binding fields + `sha256`
- [ ] Handoff URI (`solana:...`, `ai4-network=devnet`) and binding `sha256`
- [ ] Desktop HTML path served at `http://127.0.0.1` (or MOBILE_ONLY browse UL on a phone)
- [ ] `LIVE_WALLET_HANDOFF` (owner): wallet cluster confirmed DevNet
- [ ] `LIVE_SIGNATURE` (owner): public signature only
- [ ] `status()` progression
- [ ] Structured AI4 receipt (attribution line intact)
- [ ] DevNet explorer URL for that signature
- [ ] Confirmation that AI4 never handled keys

Agent-run prepare-only dry runs may capture stdout. Wallet signing is
**pending owner**.

## Narrow product claims

This proof shows that `ai4.transaction` can constrain a tiny DevNet SOL
transfer intent and observe a user-broadcast signature. It does **not**
claim: custody, server signing, mainnet readiness, Telegram hosting, PyPI
transaction features, buy/sell/swap, or that AI4 executed a transfer.

## Tests (no live chain)

```bash
python3 -m pytest tests/test_transaction_devnet_e2e.py tests/test_transaction_receipt.py
python3 -m pytest
python scripts/secret_scan.py
```

CI must not need DevNet. RPC is mocked.
