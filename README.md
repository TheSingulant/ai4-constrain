# ai4-constrain

**Constrained authority for increasingly capable AI systems.**

AI⁴ (`The Singulant`) ships `ai4.constrain`: a Python runtime that evaluates candidate text under frozen shard rubrics and returns a structured `DecisionReport` (`accept` / `revise` / `refuse` / constrained outcomes). Controls fail closed. Identity is a sibling provenance kernel, not trust and not policy authority.

This repository is the **public product runtime**. It is not a live bot host, not a cloud deploy tree, and does not ship production credentials.

## Problem

Model backends emit text. Without an explicit constraint layer, that text can become policy, trust, or action by accident. `ai4.constrain` keeps proposal, evaluation, and product policy on separate walls and records decisions in an auditable report.

## Architecture (request path)

```
request / prompt
  → proposal provider (candidate text only)
  → evaluator (scores only; does not set packaged policy)
  → frozen condition-D control loop (shards, arbitration, revision bounds)
  → DecisionReport (allow / revise / refuse / constrained)
```

Optional **v0.7 hybrid path**: when a validated `GoverningIntegration` is set on `RuntimeConfig.integration`, `run()` may execute a product-owned semantic observe → findings → packaged fuse path. Default remains **OFF** (absent integration). No environment switch activates governance.

## What v0.7.0 implements

- Everything in public **v0.6.0** (sessions, provider/evaluator policy walls, `ai4.identity`, offline `.ai4` `FileResolver`)
- Packaged semantic taxonomy + findings bind/hash primitives (`semantic_findings`, `semantic_fuse`, `semantic_taxonomy`, `semantic_examiner`)
- Hybrid continuity / budget / provenance primitives (`ai4.constrain._v07_3a`, `_v07_3b`)
- Optional `GoverningIntegration` activation surface for hybrid `run()` (`governing.py`, `_v07_3c`)
- Fail-closed refusal to silently drop hybrid identity fields from legacy 0.1.x report/session documents

**Validation (public-safe):** the v0.7 constrained-authority engineering milestone includes independently reviewed external-authority validation of authority-gate behavior under isolated live validation. Methodology is summarized in [`docs/validation.md`](docs/validation.md). Operational topology, account identifiers, and internal unresolved-decision IDs are not published here.

**Not claimed complete:** dedicated-context lifecycle and expanded authority-control work remain next-phase only.

**Honest Stage 2D status:** Stage 2D did **not** establish D as superior to C. Frozen evidence class remains `null_retained_D_adds_cost`.

Evaluator implementation interchange does not demonstrate alignment persistence or correctness across judges.

## Install / quickstart

```bash
python3 -m pip install -e ".[dev]"
```

```python
from ai4.constrain import ConstrainedSession, run, evaluate

session = ConstrainedSession()  # mock provider, redacted, in-memory
turn = session.complete("Please give a brief, checkable outline of options and limits.")
print(turn.report.decision, session.last_output)

report = run("Please give a brief, checkable outline of options and limits.")
print(report.decision, report.final_output)
```

Default provider is the offline mock. No API key is required for the quickstart or pytest.

Optional hybrid surface (default OFF; requires a caller-built `GoverningIntegration` with distinct examiner pin and allowlisted origins — see tests under `tests/test_hybrid_*`):

```python
from ai4.constrain import GoverningIntegration, GOVERNING_INTEGRATION_VERSION
# Construct only with product-owned config; validate() fails closed on bad pins.
```

## Examples and tests

```bash
python examples/constrain/hello.py
python examples/constrain/session_turns.py
python3 -m pytest
```

CLI:

```bash
ai4-constrain --help
ai4-constrain session complete --prompt "Please give a brief, checkable outline of options and limits."
```

## Docs

| Doc | Topic |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | Layering and walls |
| [`docs/constrain-runtime.md`](docs/constrain-runtime.md) | `run` / `evaluate` |
| [`docs/constrain-session.md`](docs/constrain-session.md) | `ConstrainedSession` |
| [`docs/validation.md`](docs/validation.md) | Public validation methodology |
| [`docs/identity.md`](docs/identity.md) | Sibling identity kernel |
| [`docs/identity-resolution.md`](docs/identity-resolution.md) | Offline `.ai4` discovery |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`ROADMAP.md`](ROADMAP.md) | Done vs next |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev workflow |
| [`SECURITY.md`](SECURITY.md) | Reporting |

## Next

Dedicated-context lifecycle and expanded authority-control work are planned as a separate phase. They are not part of this public 0.7.0 runtime claim.

## Prior releases (short)

- **0.6.0** — offline `.ai4` `FileResolver` discovery adapter
- **0.5.0** — `ai4.identity` provenance kernel
- **0.4.0** — evaluator policy wall
- **0.3.0** — proposal-provider policy wall
- **0.2.0** — `ConstrainedSession`
- **0.1.x** — frozen condition-D product wrapper

Identity is not trust. Resolution is not verification. Naming is not policy authority.

## License

MIT. See [`LICENSE`](LICENSE).
