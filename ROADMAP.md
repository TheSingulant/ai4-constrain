# Roadmap

## Done in public 0.7.0

- Frozen condition-D `ai4.constrain` runtime and `DecisionReport`
- `ConstrainedSession` persistence
- Provider and evaluator policy walls
- Sibling `ai4.identity` + offline `.ai4` `FileResolver`
- Optional hybrid semantic governing integration (default OFF)
- Public CI, contributing, and security docs
- Public-safe validation methodology note

## On main, not in the PyPI 0.7.0 release

- Transaction-control scaffold (`ai4.transaction`) is present on main. It is not a 0.7.0 completeness claim, not a PyPI transaction-feature release, and not a Telegram host. Signing stays in the user wallet. AI4 does not hold private keys. Mainnet is not enabled.
- Solana DevNet E2E proof harness is scaffold and evidence only (tiny SOL amounts, user-wallet signing).

## Next (not claimed complete)

- **Dedicated-context lifecycle and expanded authority-control work** (separate phase; no operational topology in this repo)
- Broader developer examples for hybrid `GoverningIntegration` (still optional / fail-closed)
- Discoverability hygiene (topics, homepage, downstream dataset mapping) as process work outside the library API

## Explicitly out of scope for this public tree

- Live bot hosts and production credentials
- Cloud account topology, IAM, or authority-gate infrastructure as code
- Sealed Stage 2D fixtures / unblind keys
- Claims that Stage 2D proved D superior to C

See also [`docs/roadmap.md`](docs/roadmap.md) for the shorter in-docs pointer.
