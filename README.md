# ai4-constrain

Public product runtime for **`ai4.constrain`** (v0.1.0): a constrained-generation library that productizes the frozen **condition-D** architecture (five shard rubrics, per-shard scores, arbitration, at most two revision rounds).

This repository is **not** the live Telegram bot (`@AI4DemoBot`) and is **not** a Vultr or other host deploy tree. It does not ship production credentials, bot tokens, or deployment wiring.

## Honest Stage 2D status

**Stage 2D did not establish D as superior to C.** Productizing condition-D is an architectural/research choice, not an experimental win. The frozen evidence classification remains **`null_retained_D_adds_cost`** (D adds cost without retained superiority over C). Sealed Stage 2D fixtures, gold notes, unblind keys, and held-out packs remain private and are **not** included in this export.

See [`docs/constrain-runtime.md`](docs/constrain-runtime.md).

## Quickstart

```bash
python3 -m pip install -e ".[dev]"
```

```python
from ai4.constrain import run, evaluate

report = run("Please give a brief, checkable outline of options and limits.")
print(report.decision, report.final_output)

scored = evaluate("Here is a brief, checkable answer about options.")
print(scored.decision)
```

CLI (entry point `ai4-constrain`, or module form):

```bash
ai4-constrain --help
python -m ai4.constrain --help
python -m ai4.constrain run --prompt "Please give a brief, checkable outline of options and limits."
python -m ai4.constrain evaluate --text "Here is a brief, checkable answer about options."
python examples/constrain/hello.py
```

Default provider is the offline mock. No API key is required for the quickstart or pytest.

CLI exits: 0 accept, 1 config/runtime failure, 2 revise, 3 refuse, 4 timeout/execution. Reports redact common personal-data patterns by default.

## What ships in v0.1

- Product package: `ai4.constrain` (`run`, `evaluate`, `DecisionReport`, CLI)
- Packaged rubrics: `ai4/data/rubrics/v0.1/` (also mirrored under `rubrics/v0.1/`)
- Offline experiment harness under `src/` (conditions A/B/C/D) for local pilot work
- Dev fixtures only: `fixtures/dev_set.jsonl`, `fixtures/pilot_prompts.jsonl`

Out of scope for this public tree: Docker/Telegram production wiring, sealed held-out fixtures, Stage 2D authoring scripts, on-chain listeners, governance claims.

## Tests (offline)

```bash
python3 -m pytest
```

Pytest uses the mock provider and must pass without network.

## Live models (optional)

Disabled by default. Paid runs need a hard spending cap first:

```bash
export AI4_ENABLE_LIVE_LLM=1
export AI4_MAX_SPEND_USD=5
export AI4_API_KEY=...
python3 -m src.main experiment --condition D --provider live
```

Do not point this at production bot tokens or hosts.

## License

MIT. See [`LICENSE`](LICENSE).
