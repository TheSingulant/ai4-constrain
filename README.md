# ai4-constrain

Public product runtime for **`ai4.constrain`** (**v0.2.0**): a constrained-generation library that productizes the frozen **condition-D** architecture (five shard rubrics, per-shard scores, arbitration, at most two revision rounds), plus **`ConstrainedSession`** for persistent constrained state across turns.

This repository is **not** the live Telegram bot (`@AI4DemoBot`) and is **not** a Vultr or other host deploy tree. It does not ship production credentials, bot tokens, or deployment wiring.

## Honest Stage 2D status

**Stage 2D did not establish D as superior to C.** Productizing condition-D is an architectural/research choice, not an experimental win. The frozen evidence classification remains **`null_retained_D_adds_cost`** (D adds cost without retained superiority over C). Sealed Stage 2D fixtures, gold notes, unblind keys, and held-out packs remain private and are **not** included in this export.

## What is new in v0.2.0

- **`ConstrainedSession`**: multi-turn wrapper around frozen `run` / `evaluate`
- Local persistence: in-memory store and JSON `FileSessionStore`
- Trusted-output semantics: only accepted (or safe-refusal) terminal text enters trusted assistant history
- Snapshot / restore with schema + policy/runtime identity validation (fail-closed)
- History composition (`include_history`, default **off**) is **untrusted context**, not configuration
- Model / session content **cannot** rewrite frozen constraint policy (shards, thresholds, arbitration)
- Session CLI: `ai4-constrain session …`
- Optional local JSONL diagnostics and shard-card explainability (derived presentation only)

**Not included:** HTTP / SSE / FastAPI serving (out of scope for this public milestone).

See [`docs/constrain-session.md`](docs/constrain-session.md) and [`docs/constrain-runtime.md`](docs/constrain-runtime.md).

## Quickstart

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

CLI:

```bash
ai4-constrain --help
ai4-constrain session complete --prompt "Please give a brief, checkable outline of options and limits."
ai4-constrain session demo --explain
python examples/constrain/session_turns.py
```

Default provider is the offline mock. No API key is required for the quickstart or pytest.

## Persistence / privacy notes

`FileSessionStore` writes JSON snapshots under a local directory (prompts, reports, derived trusted output, policy identity metadata). Default redaction substitutes common personal-data patterns; it does **not** mean “no sensitive text is ever written.” Treat the store directory as trusted local storage, not a policy oracle. Tampering with snapshot JSON cannot weaken constructor `redact` / `include_history` or change frozen policy identity on restore.

## Tests (offline)

```bash
python3 -m pytest
```

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
