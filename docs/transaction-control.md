# Transaction Control (scaffold)

Software for managing a single class of cryptocurrency transfer, with a real
use of `ai4.constrain` on that consequential action. This note is the v1
architecture lock. It is a library scaffold on a feature branch. It is not a
released PyPI version claim, not a Telegram deploy, and not a server wallet.

Existing constrain-only docs (`DecisionReport`, sessions, identity) do not by
themselves satisfy a cryptocurrency-transaction goods surface. This module is
the start of that surface.

## Canonical flow

```
Telegram UI (future, feature-flagged host)
  → Transaction Manager (prepare / validate / review)
  → ai4.constrain Transaction Firewall
  → DecisionReport  +  product decision ALLOW | DENY
  → unsigned tx stub / wallet handoff URI
  → user self-custodial wallet
  → chain
  → lifecycle monitor (status)
  → AI4 receipt
```

This repository implements the manager, firewall, unsigned handoff, and
status poll. The Telegram host is out of this repository. See
[`telegram-transaction-design.md`](telegram-transaction-design.md).

## v1 locked picks

| Pick | Choice | Why |
| --- | --- | --- |
| Chain | **Solana** (`mainnet-beta`; `devnet` / `localnet` for tests) | Phantom deep-link handoff fits a Solana transfer slice. |
| Action | **transfer only** | No buy, sell, swap, fiat, discretionary routing, or fees-as-business. |
| Asset | **native SOL only** | No SPL tokens, no wrapped SOL as a distinct asset, no cross-chain. |
| Signing | **user off-box only** | Never broadcast from a server key. No seeds, no hosted wallet. |

**Why not the `.ai4` mint chain.** Unstoppable Domains `.ai4` name
registration / mint is Polygon / UNS, not Solana. This slice is a Solana
native transfer with Phantom handoff. A later evidentiary wrap of a Polygon
mint is documented below and is not implemented here.

## Module boundaries

**Lives in this repo (`ai4.transaction`):**

- Deterministic validators (network allowlist, Solana address shape, amount
  cap, SOL-only, reject custody / server-sign / server-broadcast flags)
- Transaction Firewall: structured proposal → `ai4.constrain.evaluate` →
  map `accept` to ALLOW; `refuse` / `revise` / timeout / config error to DENY
- `prepare_transfer`: validate → firewall → on ALLOW, bind handoff from the same
  `NormalizedIntent` (URI must parse back to destination, amount, cluster)
  then emit unsigned stub plus Solana Pay / Phantom browse URI
- `status`: JSON-RPC poll only when an RPC URL is supplied
- CLI `ai4-transaction`
- Audit-log **stub interface only** (`AuditLogService` / `AuditLogSink`)

**Lives in a future Telegram host (not this PR):**

- Bot process, chat transport, feature flag, user/chat allowlist
- Confirmation screen rendering
- Calling `prepare_transfer` / `status` with the same Python module
- Any later hosted audit-log SaaS implementation

The host must import this package. It must not reimplement validation or
invent a second policy path.

## Fail-closed rules

Deny (or refuse to emit a handoff) when any of the following hold:

- Network is outside `{mainnet-beta, devnet, localnet}`
- Asset is not native SOL
- Amount is not finite, not greater than 0, has more than 9 decimals, or
  exceeds the configured cap (default 1 SOL)
- Destination is not a 32-byte Solana public key in base58
- Custody, server-sign, or server-broadcast flags are set
- `ai4.constrain` returns `refuse`, `revise`, `null`, or raises
- An RPC URL is supplied and chain state, fee hint, or status is unreachable
  or ambiguous
- `status` is called without an RPC URL

If no RPC URL is supplied, `prepare_transfer` does **not** claim a verified
fee. The summary says the wallet will show the fee before sign. That is not
a silent default to a public RPC.

## How constrain is used

After deterministic validation, the firewall builds a structured proposal
and scores it with `ai4.constrain.evaluate` (evaluate-only: frozen shards,
no model calls, no live LLM spend). The `DecisionReport` is attached to the
prepare result.

Unit tests may inject an evaluate fixture. Live LLM evaluator spend through
`run()` needs owner approval and is not enabled in the CLI.

Map:

| Constrain `decision` | Product |
| --- | --- |
| `accept` | ALLOW |
| `refuse` | DENY |
| `revise` | DENY |
| `null` (timeout / execution) | DENY |
| missing report / exception | DENY |

ALLOW emits an unsigned stub and handoff URIs only after URI binding
verification. DENY returns the report (when one exists) and reasons only.
DENY never sets `handoff_uri`, `phantom_browse_uri`, or `unsigned_payload`.

## How Telegram will call the same module later

A future host, behind a feature flag and an allowlist, should call:

```python
from ai4.transaction import TransferIntent, TransferConfig, prepare_transfer, status

result = prepare_transfer(
    TransferIntent(network="mainnet-beta", asset="SOL", amount="0.1", destination=dest),
    config=TransferConfig(max_amount_sol="1"),
)
if result.allowed:
    # show result.summary and result.approved_binding.network
    # offer result.handoff_uri / result.phantom_browse_uri
    # remind the user to confirm the wallet cluster matches approved_binding.network
    pass
# later
receipt = status(signature, rpc_url=rpc, network="mainnet-beta")
```

No second firewall. No server key. Screen copy lives in
[`telegram-transaction-design.md`](telegram-transaction-design.md).

## Wallet handoff URL scheme

This scaffold does **not** implement Phantom `/ul/v1/signAndSendTransaction`
(encrypted payload plus dapp key). It emits:

1. **Solana Pay transfer request** (wallet-agnostic; Phantom handles it):

   `solana:<destination>?amount=<SOL>&label=...&message=...&ai4-network=<cluster>`

   See https://docs.solanapay.com/spec . Amount is SOL, not lamports. No
   `spl-token` field. `label` and `message` include the approved cluster
   (for example `AI4 transfer on Solana mainnet-beta`).

2. **Phantom browse Universal Link** wrapping that URI:

   `https://phantom.app/ul/browse/<url-encoded-solana-pay>?ref=<url-encoded-ref>`

   See https://docs.phantom.com/phantom-deeplinks/deeplinks-ios-and-android

The user reviews and signs in their wallet. AI4 does not hold keys or assets.
`UnsignedPayload` remains an honest stub (`solana_system_transfer_stub`), not
a serialized unsigned Solana transaction.

## Decision-to-handoff binding

`ai4.constrain.evaluate` scores proposal **prose**. `DecisionReport` fields are
not structured transfer parameters. Binding is enforced in `ai4.transaction`
after firewall ALLOW:

1. Handoff URIs are built only from the same frozen `NormalizedIntent` that
   was proposed (network, asset, action=transfer, amount, destination).
2. The Solana Pay URI is parsed back before ALLOW is returned. Verification
   requires scheme `solana`, recipient == destination, amount Decimal and
   lamports match, no `spl-token`, and `ai4-network=<approved cluster>`.
   Label and message must include that cluster. Mismatch is DENY, no handoff.
3. `PrepareResult.approved_binding` stores those structured fields plus a
   sha256 of the canonical payload. Telegram/CLI must display network from
   this binding (and the human summary), not from wallet state.

**What is structurally bound:** destination, amount (SOL and lamports), asset
SOL, action transfer, and the `ai4-network` cluster marker on the URI.

**What is not cryptographically locked:** Solana Pay has no official cluster
field. Wallets ignore `ai4-network`. The **wallet cluster remains a user
setting**. A user can still sign on the wrong cluster. Residual risk is
disclosed in the summary. This parameter is for binding integrity and audit,
not a chain lock.

If URI verification fails, the product decision is DENY and no URI is
returned.

## Status / receipt

`status(signature)` calls `getSignatureStatuses` via stdlib urllib JSON-RPC
when `rpc_url` or `AI4_SOLANA_RPC_URL` is set. `.env.example` documents the
name as an empty optional. No hardcoded RPC and no credentials.

Known confirmation values: `processed` (pending-like, not yet confirmed),
`confirmed`, `finalized`. Null status, transport failure, or unknown shape is
fail closed. A found on-chain `err` is a real result, not an ambiguous miss.
CLI never labels a fail-closed receipt as confirmed.

Explorer links are optional and only when `--network` is supplied.

## Audit-log SaaS stub

`ai4.transaction.audit_stub` defines `AuditLogSink` (Protocol) and
`AuditLogService` (ABC). There is no implementation, no HTTP client, and no
default writer. A later product can implement the interface without changing
the prepare/firewall signatures.

## Mint flow findings (out of scope)

Public `ai4.identity` `FileResolver` is offline fixture resolution for
Unstoppable-shaped `.ai4` JSON. It does **not** prepare or track on-chain
mint transactions. It does not talk to Polygon, UNS REST, or a wallet.

This public tree has no Solana / Phantom / mint transfer pipeline for wrapping
a live `.ai4` name-registration or mint. As of this work, a private
singularity tree is also not treated as an in-repo mint wrap source.

**Therefore:** wrap of live `.ai4` name-registration / mint is out of scope
for this PR. Do not change mainnet mint code in this turn.

**Future wrap (not implemented):** a later Polygon evidentiary path can take
an already-built mint summary (name, network, asset, action, amount or fee,
destination or registry) and pass that same structured text through
`run_firewall` / `prepare_transfer`-shaped review so a `DecisionReport` and
ALLOW/DENY attach without editing Unstoppable mint internals. Mint wrap stays
a separate change.

## RPC and secrets

- Optional env: `AI4_SOLANA_RPC_URL=` (empty). Argument `--rpc-url` overrides.
- No seeds, private keys, bot tokens, or server wallets in this package.
- RPC URLs that embed credentials are refused.

## CLI

```bash
ai4-transaction prepare --network mainnet-beta --asset SOL --amount 0.1 --destination <addr>
ai4-transaction status <signature> --rpc-url "$AI4_SOLANA_RPC_URL"
```

Stdout is JSON (prepare result including `decision_report` when present).
Stderr is the human summary. Exit 1 on DENY or fail-closed.
