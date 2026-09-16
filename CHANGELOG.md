# Changelog

All notable public releases of `ai4-constrain` are listed here.

## Unreleased (scaffold, not a PyPI release)

### Added

- `ai4.transaction` scaffold: Solana native SOL transfer validate / firewall / prepare / status / CLI
- Decision-to-handoff binding: `ai4-network` query param, URI parse-back before ALLOW, `approved_binding` on `PrepareResult`
- Solana **DevNet-only** E2E proof harness (`examples/transaction/devnet_e2e.py`, `ai4.transaction.receipt.AI4Receipt`): tiny SOL cap (≤ 0.01), forced `network=devnet`, user-wallet signing, `status()` poll, structured receipt
- Desktop Phantom **extension** handoff: committed HTTPS HTML (`examples/transaction/live_proof/fe30e76a_devnet_handoff.html`) plus injected `window.phantom.solana` (`signAndSendTransaction`). Owner click-path is GitHub Pages / GitHack HTML MIME; jsDelivr currently serves the same file as `text/plain`. Phantom `ul/browse` Universal Link is labeled **MOBILE_ONLY**. `http://127.0.0.1` is an optional offline fallback.
- Live Solana DevNet E2E completed with an owner Phantom signature (self-transfer 0.001 SOL, `finalized`); evidence in `examples/transaction/LIVE_EVIDENCE.md`. Scaffold only; version remains 0.7.0; not a PyPI claim; not Telegram.
- `docs/transaction-control.md`, `docs/transaction-devnet-e2e.md`, and `docs/telegram-transaction-design.md`
- Optional empty `AI4_SOLANA_RPC_URL=` in `.env.example`
- Console script `ai4-transaction` (feature branch only; package version remains 0.7.0)

### Not in this change

- No Telegram deploy, no hosted bot, no server wallet, no mint wrap, no version bump

## 0.7.0 — 2026-09-14

### Added

- Optional `GoverningIntegration` on `RuntimeConfig.integration` (default absent / OFF)
- Packaged semantic examiner / findings / fuse / taxonomy modules and `ai4/data/semantic_v07/` artifacts
- Hybrid primitive packages `ai4.constrain._v07_3a`, `_v07_3b`, `_v07_3c`
- Public-safe hybrid and semantic unit tests
- Root `CHANGELOG.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `SECURITY.md`
- `docs/validation.md` (methodology only)
- GitHub Actions CI (`pip install -e ".[dev]"` + pytest)

### Changed

- Package version **0.7.0**; README restructured for cold visitors
- `DecisionReport` / `SessionState` refuse silent drop of hybrid identity fields on legacy 0.1.x documents
- `MANIFEST.in` / package-data include semantic JSON/TXT artifacts

### Security / hygiene

- Expanded committed-tree secret scan patterns (AWS key/ARN shapes, known internal markers)
- Excludes deployment trees, private validation fixtures, credentials, and host wiring from this public export

### Not in this release

- No GitHub Release tag from this changelog alone (tagging is a separate Phase C gate)
- No AWS / external-host / dedicated-context lifecycle product surface
- No live Unstoppable REST / bot host / production credentials

## 0.6.0

Offline `.ai4` discovery adapter (`FileResolver`), sibling resolve CLI, identity-resolution docs. Identity is not trust; resolution is not verification.

## 0.5.0

Sibling `ai4.identity` provenance kernel (Ed25519, report binding, trust context). Not on the constrain execution path.

## 0.4.0

Evaluator policy wall: judges score; packaged policy remains product-owned.

## 0.3.0

Proposal-provider policy wall: backends emit candidate text only.

## 0.2.0

`ConstrainedSession` persistence and session CLI.

## 0.1.x

Frozen condition-D product wrapper around the research harness. Stage 2D evidence class: `null_retained_D_adds_cost`.
