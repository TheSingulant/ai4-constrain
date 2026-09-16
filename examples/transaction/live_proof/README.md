# Frozen DevNet live-proof desktop handoff

Committed static HTML for the owner **HTTPS** Phantom-extension path.

Frozen binding (do not edit fields):

- network=`devnet`
- asset=`SOL`
- action=`transfer`
- amount=`0.001` SOL
- lamports=`1000000`
- destination=`4WDYrTNTit9m7kU5y2LWCfvf35pQo9vbjPTDyiDHEq9e`
- sha256=`fe30e76ac25e766f37d4f719caaa7efa7b2603afbf388dbca609154258a37da0`

Open over **HTTPS** in Chrome with Phantom. Owner click-path is
`https://rawcdn.githack.com/TheSingulant/ai4-constrain/<COMMIT_SHA>/examples/transaction/live_proof/fe30e76a_devnet_handoff.html`
(HTML MIME). jsDelivr hosts the same bytes but currently serves `text/plain`
with `nosniff`, so Chrome will not run it as a page. Phantom injects
`window.phantom.solana` on https. `file://` does not work.
`http://127.0.0.1` is an optional offline/dev fallback only.

Set Phantom to **Devnet**, click **Approve in Phantom**, approve in the
dialog. Paste the public signature back to AI4. This page does not poll
status and does not handle keys.

See [`docs/transaction-devnet-e2e.md`](../../../docs/transaction-devnet-e2e.md).
