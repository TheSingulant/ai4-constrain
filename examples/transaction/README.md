# Transaction examples

Scaffold / unreleased feature work. Package version remains **0.7.0**.

## Solana DevNet E2E proof

`examples/transaction/devnet_e2e.py` prepares a **tiny native SOL transfer on
DevNet only**, prints the DecisionReport, approved binding, and Solana Pay
URI, writes a desktop Phantom-extension HTML page, then (optionally) polls
`status()` after **you** sign and broadcast.

`https://phantom.app/ul/browse/...` is **MOBILE_ONLY**. Desktop owners open the
committed HTTPS page
[`live_proof/fe30e76a_devnet_handoff.html`](live_proof/fe30e76a_devnet_handoff.html)
in Chrome with Phantom (jsDelivr). `http://127.0.0.1` is an optional
offline/dev fallback only.

AI4 does not hold keys or assets. There is no signing automation.

See [`docs/transaction-devnet-e2e.md`](../../docs/transaction-devnet-e2e.md)
for the full runbook, residual wallet-cluster risk, and evidence checklist.

```bash
python examples/transaction/devnet_e2e.py \
  --destination <solana-address> \
  --amount 0.001 \
  --rpc-url https://api.devnet.solana.com \
  --prepare-only
```

After the wallet broadcasts, re-run with `--signature <tx-signature>` (a
public signature, not a private key).

Live-run blanks: [`LIVE_EVIDENCE.md`](LIVE_EVIDENCE.md). Leave
`LIVE_WALLET_HANDOFF` / `LIVE_SIGNATURE` for the owner. Do not invent
explorer links.
