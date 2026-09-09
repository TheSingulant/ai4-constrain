# ai4-constrain

Public product runtime for **`ai4.constrain`** (**v0.6.0**): a constrained-generation library that productizes the frozen **condition-D** architecture (five shard rubrics, per-shard scores, arbitration, at most two revision rounds), plus **`ConstrainedSession`** for persistent constrained state across turns, with a **proposal-provider policy wall** so backends emit candidate text and do not govern, an **evaluator policy wall** so judges score and do not set policy, sibling **`ai4.identity`** for offline identity and provenance, and an offline **`.ai4` discovery adapter** (`FileResolver` only).

This repository is **not** the live Telegram bot (`@AI4DemoBot`) and is **not** a Vultr or other host deploy tree. It does not ship production credentials, bot tokens, or deployment wiring.

## Honest Stage 2D status

**Stage 2D did not establish D as superior to C.** Productizing condition-D is an architectural/research choice, not an experimental win. The frozen evidence classification remains **`null_retained_D_adds_cost`** (D adds cost without retained superiority over C). Sealed Stage 2D fixtures, gold notes, unblind keys, and held-out packs remain private and are **not** included in this export.

## What is new in v0.6.0

- **Offline `.ai4` discovery/resolution adapter (`ai4.identity.resolve`):** `DiscoveryRecord`, `Resolver`, `FileResolver`, local fetch pipeline, `.ai4` name normalization, hash-bound attestation discovery, and signed `name_records` cross-name protection
- Sibling CLI: `python -m ai4.identity resolve` / `verify` (not the constrain CLI)
- Five independent verification statuses: NAME RESOLVED, MANIFEST INTEGRITY VERIFIED, SIGNATURE VALID, CURRENT TRUST MATCHED, REPORT BINDING MATCHED
- Filesystem containment for directory lookup; FileResolver freshness is always `fixture` (local JSON cannot claim live)
- Docs: [`docs/identity-resolution.md`](docs/identity-resolution.md)

**Release claim:** Resolve an external `.ai4` identity into hash-bound provenance inputs for the existing identity kernel, without allowing the naming layer to become verification, current trust, or constraint-policy authority.

This slice ships `FileResolver` and offline fixtures only. It does not enable live Unstoppable REST, an Unstoppable SDK, web3, or default network lookup.

Identity is not trust. Resolution is not verification. Naming is not policy authority. `ai4.identity.resolve` remains a discovery sibling. `ai4.constrain` does **not** import identity or resolve. The identity kernel does not import resolve.

A signed AI⁴ identity record binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.

See [`docs/identity-resolution.md`](docs/identity-resolution.md). Frozen Stage 2D evidence remains **`null_retained_D_adds_cost`**. Public v0.5 identity-kernel verification contracts are unchanged.

## What was new in v0.5.0

- **Sibling identity/provenance kernel (`ai4.identity`):** `AgentIdentity`, `AgentAttestation`, `NameRecordSnapshot`, `TrustContext`
- Report binding/provenance (`bind_report` / `verify_report_binding`)
- Ed25519 signing and verification; SHA-256 digests
- Locked **`rfc8785==0.1.4`** canonicalization profile (`rfc8785-jcs`)
- Rotation as privately reviewed: single controller; optional rotation attestation signed by the previous key; monotonic manifest versions; skip-version rotations abandon skipped versions
- Current-trust vs historical-signature semantics (`verify_attestation` vs `verify_attestation_signature`)
- Binding verdicts are provenance-only (`matched` / `unbound` / `mismatch` / `expired` / `untrusted_signer`) — never `accept` / `revise` / `refuse`

`ai4.identity` remains a sibling kernel. `ai4.constrain` does **not** import `ai4.identity`. Identity does not enter `run()` / `evaluate()` / sessions and is not a provider, evaluator, or policy authority.

Identity is not trust. Identity makes trust systems possible.

A signed AI⁴ identity record binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.

See [`docs/identity.md`](docs/identity.md). Frozen Stage 2D evidence remains **`null_retained_D_adds_cost`**. Public v0.4 policy-wall behavior is unchanged.

## What was new in v0.4.0

- **Evaluator policy wall:** evaluator implementations may be substituted behind one frozen v0.1 scoring/control contract; they cannot set packaged rubrics, `REQUIRED_IDS`, kinds, priorities, thresholds, conflicts, pass/fail derivation, arbitration, D bounds, or refusal semantics
- Packaged-policy authority: product-owned policy is loaded from packaged v0.1 YAML; middleware and arbitration never read `evaluator.rubrics`
- Score overlay: every evaluation is overlaid before middleware; scores must be finite `[0, 1]` reals; missing or extra shards fail closed
- Evaluator provenance on `DecisionReport` (`evaluator_id`, `evaluator_version`, `resolved_as`) is auditable and **not** governing policy
- Session impl binding: a session is bound to one evaluator implementation (`backend_id` plus a stable class fingerprint for custom objects); per-turn swap fails closed
- Reserved evaluator-id protections: `backend_id="v0.1-regex"` is reserved for the packaged frozen implementation; policy/control vocabulary ids fail closed
- Notes and criterion evidence are untrusted revision feedback and report text, not policy authority
- Report provenance consistency for old reports without an `evaluator` block (loadable from `versions`)

**Evaluator implementation interchange does not demonstrate alignment persistence or correctness across judges.** A compliant custom evaluator may change scores and the resulting accept/revise/refuse outcome. It must not change packaged policy. Frozen Stage 2D evidence remains **`null_retained_D_adds_cost`**.

## What was new in v0.3.0

- **Proposal-provider policy wall:** proposal backends emit candidate text; they do not set evaluator identity, rubric set, thresholds, arbitration, enforced shards, refusal semantics, or `SessionPolicyIdentity`
- Auditable `DecisionReport.proposal` block (`provider_id`, `model`, `resolved_as`) is **not** governing policy and is **not** on `SessionPolicyIdentity` or `versions` policy stamps
- Provider substitution (A persist → restore → B) is a control-loop audit property. **It does not demonstrate alignment persistence across models**
- Strict empty allowlist for provider `completion.metadata`; call `kind` is determined by AI⁴'s execution path, not provider metadata
- Governing evaluator is bound and preflighted on `run()` **before** any `complete()` / `revise()`
- Every session `complete()` / `evaluate_text()` revalidates the evaluator object about to be used against the identity bound at construction/load
- Same-object dual-role provider+evaluator fails closed; unknown provider/evaluator strings fail closed; `evaluate()` remains proposal-model-free

**Not a claim:** changing the proposal provider or model may change candidate text and resulting decisions. Frozen Stage 2D evidence remains **`null_retained_D_adds_cost`**.

## What was new in v0.2.0

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

Identity / provenance (sibling kernel; not on the constrain execution path):

```python
from datetime import datetime, timedelta, timezone

from ai4.constrain import evaluate
from ai4.identity import (
    AgentIdentity,
    FixedClock,
    TrustContext,
    bind_report,
    generate_ed25519_keypair,
    sign_attestation,
    verify_attestation,
    verify_report_binding,
)

seed, public = generate_ed25519_keypair()
now = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
identity = AgentIdentity.create(
    identity_id="agent-alpha",
    controller_public_key=public,
    manifest_version=1,
    issued_at=now,
    expires_at=now + timedelta(hours=1),
)
report = evaluate("Here is a brief, checkable answer: I can outline options and limits.")
attestation = sign_attestation(
    identity,
    seed,
    issued_at=now,
    expires_at=now + timedelta(minutes=30),
    binding=bind_report(report),
)
verify_attestation(attestation, trust=TrustContext.from_identity(identity), clock=FixedClock(now))
result = verify_report_binding(
    attestation, report, trust=TrustContext.from_identity(identity), clock=FixedClock(now)
)
assert result.verdict == "matched"
```

Offline `.ai4` discovery (FileResolver fixtures; not live Unstoppable):

```bash
python -m ai4.identity resolve researcher.ai4 --resolver file --records fixtures/identity/researcher.ai4.json
python -m ai4.identity verify researcher.ai4 --resolver file --records fixtures/identity/researcher.ai4.json \
    --trust fixtures/identity/researcher.ai4.trust.json --report fixtures/identity/researcher.ai4.report.json
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
