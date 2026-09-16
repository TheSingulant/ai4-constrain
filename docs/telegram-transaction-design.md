# Telegram handler design (not deployed)

Design only. **No bot code is added or deployed in this PR.** Class 042 hosted
Telegram is a later host. This repository remains the Class 009 downloadable
library that the host would import.

Do not put tokens, chat ids, or host credentials in this tree.

## Feature flag and allowlist

A future host should keep the transfer UI dark unless **both** are true:

1. A host-side feature flag is on (suggested name `AI4_TELEGRAM_TX_ENABLED`,
   default off, owned by the host env, not this package).
2. The chat and user are on an explicit allowlist owned by the host.

If either check fails, the host replies that transfer is not available and
does not call `prepare_transfer`.

The host does not become a signer. The host does not broadcast from a server
key.

## Handler map (same module)

| User step | Host handler (future) | This repo |
| --- | --- | --- |
| Start a transfer | Collect network, asset, amount, destination | Build `TransferIntent` |
| Review | Show confirmation copy below | Call `prepare_transfer(...)` |
| Prepare | "Prepare" control | Same call; show `summary` |
| Sign | "Sign in your wallet" control | Open `handoff_uri` or `phantom_browse_uri` |
| Later status | Paste / forward a signature | `status(signature, rpc_url=..., network=...)` |
| Receipt | Show confirmation plus explorer | `Receipt` fields |

The host must not score text with a second evaluator and must not skip the
firewall on ALLOW-looking input.

## Confirmation screen copy

The host must show **Network** from `PrepareResult.approved_binding` (same
cluster recorded as `ai4-network` on the URI). Solana Pay has no official
cluster field; the wallet cluster remains a user setting. Tell the user to
confirm the wallet is on that Solana cluster before signing.

Use ordinary product language. Fill fields from `PrepareResult` after a
successful prepare, or from the draft intent before prepare.

```
Review this transfer

Network: Solana mainnet-beta
Asset: SOL
Action: transfer
Amount: 0.10 SOL
Destination: <address>
Estimated fee: your wallet will show the fee before you sign
  (or the RPC fee hint when an RPC URL was provided)

AI4 does not hold keys or assets.

[Prepare]
[Sign in your wallet]
[Later: check status]
```

After ALLOW:

```
Prepared. Open your wallet to review and sign.
You can check status later with the signature and an explorer link.
```

After DENY:

```
This transfer was not prepared.
<short reason from the report, in ordinary language>
No wallet handoff was created.
```

Do not show private keys, seeds, or raw RPC credentials. Do not claim the
software is a custodian or a hosted exchange.

## What the host must not do

- Deploy this design as live bot code from this PR
- Store user seeds or sign on a server
- Call a public RPC by hardcoding a URL in this package
- Treat identity resolution or a `.ai4` name as a payment destination in v1
- Enable buy / sell / swap / fiat from this confirmation path
