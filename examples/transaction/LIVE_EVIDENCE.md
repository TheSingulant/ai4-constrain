# Live DevNet E2E evidence (owner-filled)

This template records a **Solana DevNet** proof of:

user intent → validate → `ai4.constrain` firewall → DecisionReport ALLOW →
bound wallet handoff → human signs in a self-custodial wallet → wallet
broadcasts on **devnet** → `status()` observes lifecycle → AI4 receipt.

Do **not** paste seeds, private keys, key files, or RPC credentials.
AI4 never handles those. Signing is off-box only.

Package version remains **0.7.0**. This is scaffold / unreleased feature work,
not a PyPI release of transaction features.

## Run identity

| Field | Value |
| --- | --- |
| PR | |
| Commit SHA | |
| Package version | 0.7.0 |
| Operator | |
| Date (UTC) | |

## Prepare (AI4)

| Field | Value |
| --- | --- |
| Destination | |
| Amount (SOL, ≤ 0.01) | |
| Forced network | `devnet` |
| RPC used (no secrets) | |
| DecisionReport `decision` | |
| Product decision | |
| Approved binding (network, asset, action, amount, destination) | |
| Approved binding `sha256` | |
| Handoff URI | |
| Phantom browse URI (MOBILE_ONLY) | |
| Desktop HTML path (`http://127.0.0.1`) | optional offline fallback only |
| HTTPS live-proof HTML (rawcdn.githack.com, HTML MIME) | |

## Live wallet handoff (owner)

| Field | Value |
| --- | --- |
| LIVE_WALLET_HANDOFF | pending owner |
| Wallet used (Phantom or equivalent) | pending owner |
| Wallet cluster confirmed DevNet? | pending owner |
| Confirmation that AI4 never received keys | pending owner |

## Broadcast observation (owner)

| Field | Value |
| --- | --- |
| LIVE_SIGNATURE | pending owner |
| `status()` progression (`processed` / `confirmed` / `finalized` / failed / fail-closed) | pending owner |
| Slot | pending owner |
| On-chain error | pending owner |
| Explorer URL (DevNet only; do not invent) | pending owner |

## AI4 receipt

Paste the structured receipt JSON (or a pointer to an artifact). The
attribution line must remain:

> Prepared and constrained by AI4; signed and broadcast by the user's wallet.

Never claim AI4 executed the transfer.

```json
```

## Residual risk acknowledged

- `ai4-network=devnet` is a binding marker. Solana Pay has no official cluster
  field. The wallet cluster remains a user setting.
- Public DevNet RPC is rate-limited and may fail closed.
- `status()` observes signature lifecycle. It does not re-decode the on-chain
  instruction against the approved binding.
