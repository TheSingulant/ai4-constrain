# Live DevNet E2E evidence

Dated **Solana DevNet** proof of:

user intent → validate → `ai4.constrain` firewall → DecisionReport ALLOW →
bound wallet handoff → human signs in a self-custodial wallet → wallet
broadcasts on **devnet** → `status()` observes lifecycle → AI4 receipt.

Do **not** paste seeds, private keys, key files, or RPC credentials.
AI4 never handles those. Signing is off-box only.

Package version remains **0.7.0**. This is scaffold / unreleased feature work,
not a PyPI release of transaction features, and not Telegram.

Machine-readable copy: [`live_proof/fe30e76a_devnet_live_evidence.json`](live_proof/fe30e76a_devnet_live_evidence.json).

## Run identity

| Field | Value |
| --- | --- |
| PR | [#10](https://github.com/TheSingulant/ai4-constrain/pull/10) |
| Branch | `cursor/transaction-devnet-e2e-11d2` |
| Prepare harness commit | `c2b5fb20c3e5aaa7e6b54964e4324f8ba9e32778` |
| HTTPS handoff HTML commit | `317a0f6f1b90bc2730e9bb8132d895f88c375046` |
| Observe recorded against | `b5e4da9beaddd169125a3158c890c43ff0d0613d` |
| Package version | 0.7.0 |
| Operator | Owner signed in Phantom; AI4 prepared/constrained and later observed only |
| Date (UTC) | 2026-09-16 |

## Prepare (AI4)

| Field | Value |
| --- | --- |
| Destination | `4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e` |
| Amount (SOL, ≤ 0.01) | `0.001` |
| Forced network | `devnet` |
| RPC used (no secrets) | `https://api.devnet.solana.com` |
| DecisionReport `decision` | `accept` |
| DecisionReport `mode` | `evaluate_only` |
| DecisionReport `decision_reason` | `all shards passed` |
| Product decision | `ALLOW` |
| Approved binding | network=`devnet` asset=`SOL` action=`transfer` amount=`0.001` lamports=`1000000` destination=`4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e` |
| Approved binding `sha256` | `fe30e76ac25e766f37d4f719caaa7efa7b2603afbf388dbca609154258a37da0` |
| Handoff URI | `solana:4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e?amount=0.001&label=AI4+transfer+on+Solana+devnet&message=Unsigned+SOL+transfer+on+Solana+devnet.+Review+and+sign+in+your+wallet.+Wallet+cluster+is+a+user+setting.&ai4-network=devnet` |
| Phantom browse URI | **MOBILE_ONLY** (`phantom.app/ul/browse/...`) |
| Desktop HTML path (`http://127.0.0.1`) | optional offline fallback only |
| GitHub Pages HTTPS (owner click-path, `text/html`) | https://thesingulant.github.io/ai4-constrain/live-proof/fe30e76a/ |
| GitHack HTTPS (same committed HTML, `text/html`) | https://rawcdn.githack.com/TheSingulant/ai4-constrain/b5e4da9beaddd169125a3158c890c43ff0d0613d/examples/transaction/live_proof/fe30e76a_devnet_handoff.html |

Pages body SHA-256 `32b54abc101003fc2c92746617dee7ca0d695aa6446372d26270775fec6d55d1` equals the committed file `examples/transaction/live_proof/fe30e76a_devnet_handoff.html`. The page embeds exact dest/lamports/hash and calls `signAndSendTransaction` with `AI4.destination` + `AI4.lamports` (no unbound mutation).

## Live wallet handoff (owner)

| Field | Value |
| --- | --- |
| LIVE_WALLET_HANDOFF | completed (owner Phantom extension, DevNet, HTTPS Pages / committed HTML) |
| Wallet used (Phantom or equivalent) | Phantom Chrome extension |
| Wallet cluster confirmed DevNet? | yes (independent `getGenesisHash` = `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`) |
| Confirmation that AI4 never received keys | **confirmed**. No seed, private key, or keystore was accepted, stored, or processed. AI4 did not sign. |

## Broadcast observation

| Field | Value |
| --- | --- |
| LIVE_SIGNATURE | `4KAtBNHVJQBkAHoGGJCDDRDr1A9Rha2PSHZ5D8mA8cVKXZiyjXJmoRWUA4Y2HqEY1YKi12LmDRSJMdjRDN4dxX9E` |
| Harness `status()` observation | `finalized` (tx already terminal when polled; `processed`/`confirmed` not separately sampled) |
| Independent `getSignatureStatuses` | `confirmationStatus=finalized`, `err=null`, slot=`499404925` |
| Independent `getTransaction` jsonParsed | SystemProgram transfer dest=`4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e` lamports=`1000000`; **self-transfer** (source == destination); fee `80000` lamports; block time `2026-09-16T17:42:45Z` |
| Slot | `499404925` |
| On-chain error | `null` |
| Explorer URL (DevNet) | https://explorer.solana.com/tx/4KAtBNHVJQBkAHoGGJCDDRDr1A9Rha2PSHZ5D8mA8cVKXZiyjXJmoRWUA4Y2HqEY1YKi12LmDRSJMdjRDN4dxX9E?cluster=devnet |

`status()` does not re-decode the on-chain instruction. Destination and lamports above were checked with `getTransaction` (`jsonParsed`), not inferred from the status poll.

## AI4 receipt

Attribution (unchanged):

> Prepared and constrained by AI4; signed and broadcast by the user's wallet.

Never claim AI4 executed the transfer.

```json
{
  "network": "devnet",
  "asset": "SOL",
  "action": "transfer",
  "amount": "0.001",
  "destination": "4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e",
  "approved_binding_hash": "fe30e76ac25e766f37d4f719caaa7efa7b2603afbf388dbca609154258a37da0",
  "approved_binding": {
    "network": "devnet",
    "asset": "SOL",
    "action": "transfer",
    "amount_sol": "0.001",
    "lamports": 1000000,
    "destination": "4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e",
    "sha256": "fe30e76ac25e766f37d4f719caaa7efa7b2603afbf388dbca609154258a37da0"
  },
  "decision": "ALLOW",
  "decision_report_summary": {
    "product_decision": "ALLOW",
    "constrain_decision": "accept",
    "mode": "evaluate_only",
    "outcome_kind": "constraint",
    "decision_reason": "all shards passed",
    "terminal": null,
    "reasons": [
      "constrain decision is accept"
    ]
  },
  "decision_report_result": "accept",
  "signature": "4KAtBNHVJQBkAHoGGJCDDRDr1A9Rha2PSHZ5D8mA8cVKXZiyjXJmoRWUA4Y2HqEY1YKi12LmDRSJMdjRDN4dxX9E",
  "lifecycle_state": "finalized",
  "confirmation_status": "finalized",
  "slot": 499404925,
  "error": null,
  "timestamp": "2026-09-16T17:47:52.454760Z",
  "explorer_url": "https://explorer.solana.com/tx/4KAtBNHVJQBkAHoGGJCDDRDr1A9Rha2PSHZ5D8mA8cVKXZiyjXJmoRWUA4Y2HqEY1YKi12LmDRSJMdjRDN4dxX9E?cluster=devnet",
  "attribution": "Prepared and constrained by AI4; signed and broadcast by the user's wallet.",
  "fail_closed": false,
  "reasons": [
    "constrain decision is accept"
  ],
  "observed_success": true
}
```

## Residual risk acknowledged

- `ai4-network=devnet` is a binding marker. Solana Pay has no official cluster
  field. The wallet cluster remains a user setting.
- Public DevNet RPC is rate-limited and may fail closed.
- `status()` observes signature lifecycle. It does not re-decode the on-chain
  instruction against the approved binding. This proof's dest/lamports match
  was verified separately via `getTransaction` jsonParsed.
- This transfer is a **self-transfer** (source == destination). It still
  matches the approved destination and amount.
