# Identity / provenance kernel (PR-E)

`ai4.identity` is a **sibling** of `ai4.constrain`. It is an offline
identity and provenance kernel. It is not on the governing execution
path.

**Identity is not trust. Identity makes trust systems possible.**

> A signed AI⁴ identity record binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.

This milestone does **not** change `run()` / `evaluate()` signatures,
DecisionReport schema, packaged rubrics, `REQUIRED_IDS`, arbitration,
the D controller, revision/refusal semantics, the provider policy wall,
the evaluator policy wall, Stage 2C/2D artifacts, the protocol, or the
whitepaper. `EVIDENCE_CLASS` remains `null_retained_D_adds_cost`.

There is no session binding to `.ai4` names, controller keys, manifest
hashes, or manifest versions. Identity fields cannot enter
`SessionPolicyIdentity`. Token, wallet, and name fields cannot enter
`RuntimeConfig`. An identity object is not a proposal provider and not
an evaluator.

## What this is

- Frozen, strict `AgentIdentity` and `AgentAttestation`
- Local `NameRecordSnapshot` (not a live name-system lookup)
- RFC 8785 JCS canonicalization (`rfc8785==0.1.4`, profile id `rfc8785-jcs`)
- SHA-256 manifest and report digests
- Ed25519 sign / verify (`cryptography`), dependency-inverted
- `sign_attestation` / `verify_attestation` (current trust) /
  `verify_attestation_signature` (historical / cryptographic only)
- `bind_report` / `verify_report_binding`

## What this is not

- Not default network access, Unstoppable SDK, on-chain writes, wallets
  as identity, tokenomics, TEEs, or an HTTP service
- Not a claim that a signed agent is aligned, safe, or correctly governed
- Not policy feedback into thresholds, rubrics, arbitration, or evidence
  class
- Not a novel CRL. Single controller only. Optional rotation attestation
  signed by the previous key. Manifest versions are monotonic. Expiry is
  required.
- Compromised-key recovery remains a documented residual risk

## Identity schema (`ai4.identity.agent.v1`)

Strict object. Extra fields fail closed.

| Field | Rule |
| --- | --- |
| `schema_id` | `ai4.identity.agent.v1` |
| `identity_id` | opaque `[A-Za-z0-9._:-]{1,128}`; not a wallet/token/NFT/chain address |
| `controller_public_key` | 32-byte Ed25519 public key, lowercase hex |
| `manifest_version` | integer in `[1, 2^53-1]` (JCS-safe); monotonic under rotation |
| `issued_at` / `expires_at` | RFC 3339 UTC `YYYY-MM-DDTHH:MM:SSZ`; `expires_at > issued_at` required |
| `name_records` | array of `NameRecordSnapshot` |
| `manifest_uri` | informational string only; **never fetched**; **cannot override** the SHA-256 of local canonical bytes |

The identity **manifest** is the RFC 8785 JCS encoding of that object.
`manifest_hash` is SHA-256 of those bytes and is stored on the
attestation, not as a self-referential field on the identity.

### NameRecordSnapshot (`ai4.identity.name_record.v1`)

| Field | Rule |
| --- | --- |
| `name` | local label, may look like `agent.example.ai4` |
| `subject_id` | must match `identity_id` |
| `controller_public_key` | must match the identity |
| `captured_at` | RFC 3339 UTC |
| `source` | `local_snapshot` only |

On-chain, Unstoppable, HTTP, wallet, and TEE sources fail closed.

## Attestation schema (`ai4.identity.attestation.v1`)

Strict object. Extra fields fail closed. To-be-signed bytes are the JCS
encoding of the object with `signature` set to `""`.

| Field | Rule |
| --- | --- |
| `identity` | embedded `AgentIdentity` |
| `manifest_hash` | SHA-256 of canonical identity bytes |
| `signature_algorithm` | `ed25519` only; unknown algorithms fail closed |
| `signature` | 64-byte Ed25519 signature, lowercase hex |
| `issued_at` / `expires_at` | required window, `expires_at > issued_at` |
| `report_hash` | empty if unbound; else SHA-256 of canonical DecisionReport bytes |
| `claimed_profile` | `null` if unbound; else VersionInfo claims captured at bind time |
| `rotation` | `null` or a rotation attestation signed by the previous key |

`report_hash` and `claimed_profile` must both be present or both be
absent.

### Claimed profile (`ai4.identity.claimed_profile.v1`)

Copied from the bound report's `VersionInfo`: `runtime_version`,
`report_schema_version`, `protocol`, `condition`, `evidence_class`,
`rubric_set`, `evaluator_id`, `evaluator_version`, `arbitration`,
`rubric_versions`. These are provenance claims. They cannot retune
policy.

## Canonicalization model

- Profile id: `rfc8785-jcs`
- Locked library: **`rfc8785==0.1.4`** (RFC 8785 JSON Canonicalization Scheme)
- Identity records additionally reject floats, bytes, sets, and
  non-string keys before JCS
- Report binding uses JCS over `DecisionReport.to_dict()` so existing
  finite floats remain representable
- `rfc8785==0.1.4` follows RFC 8785 ES6 numbers: IEEE `+0.0` and `-0.0`
  both serialize as JSON `0`. Digests are this locked profile, not an
  unbounded “any rfc8785 version” portable hash
- UTF-8 bytes; no insignificant whitespace; object keys sorted per JCS
- Tests lock `+0.0` / `-0.0`, representative telemetry floats, and
  stable cross-call report digests

## Signing and verification model

- Algorithm: Ed25519 only (RFC 8032 via `cryptography`)
- Hash: SHA-256 only
- Signer / verifier / clock are injected (`LocalEd25519`, `SystemClock`
  or `FixedClock`). No network time, no remote KMS.
- `sign_attestation(identity, private_key, issued_at=..., expires_at=..., binding=..., rotation=...)`
- `verify_attestation_signature(attestation, clock=...)` is **historical /
  cryptographic** verification only. Success means the record is
  well-formed and the Ed25519 signature is valid for the embedded key.
  It does **not** mean the identity is current.
- `verify_attestation(attestation, trust, clock=...)` requires an
  explicit `TrustContext` and is the only current-trust verifier. It
  fails closed on malformed/extra fields, unknown algorithm, bad
  controller key, wrong manifest hash, expired records,
  `expires_at <= issued_at`, identity-id mismatch, and replay of a
  superseded manifest version.
- `TrustContext` is the caller's single current controller
  (`identity_id` + key + version + hash). Identity does not invent
  that trust. Signature validity is not current identity.

## Report-binding model

1. `bind_report(report)` → `{report_hash, claimed_profile}` from the
   **same** canonical `to_dict()` payload. A forged duck-typed
   `.versions` attribute cannot influence the binding.
2. `sign_attestation(..., binding=that)`
3. `verify_report_binding(attestation, report, trust=...)`

The report is hashed as canonical JCS bytes. Claimed profile fields are
compared to `payload["versions"]` from that same object. The report
schema is not extended with signature fields.

Verdicts (and only these):

| Verdict | Meaning |
| --- | --- |
| `matched` | explicit `TrustContext` accepts the attestation as **current**, and report hash and profile match |
| `unbound` | no attestation or no report hash |
| `mismatch` | wrong report hash or VersionInfo claim mismatch |
| `expired` | attestation or identity past `expires_at` |
| `untrusted_signer` | bad signature, missing/wrong/superseded TrustContext, failed rotation |

`matched` is never returned from signature validity alone. A
crypto-valid historical attestation without a current `TrustContext` is
`untrusted_signer`, not `matched`.

Never `accept` / `revise` / `refuse`. Never a score.

## Rotation and revocation (this PR)

- Single controller only
- Rotation binds `identity_id`, new controller public key, new
  manifest version, and new manifest hash. A rotation for `agent-alpha`
  cannot authorize another identity.
- `verify_rotation()` returns a **complete** successor `TrustContext`
  (no empty manifest hash)
- `manifest_version` strictly monotonic (`new > old`). **Skip-version
  rotations are allowed** (for example v1→v3) and abandon skipped
  versions. Abandoned versions are not current and are not listed on a
  CRL.
- Expiry required on identity, attestation, and rotation
- Optional rotation attestation signed by the **old** key
- No CRL, no gossip, no threshold recovery
- Forged, expired, future, same-version, and rollback rotations fail closed

**Residual risk:** if the current controller key is compromised and no
valid rotation was issued beforehand, there is no recovery path in this
kernel. Operators must treat that as loss of signing authority and
re-establish trust out of band.

## Isolation

`ai4.constrain` must not import `ai4.identity`. Passing an identity
object into `run(..., provider=...)` or `run(..., evaluator=...)` fails
the existing provider/evaluator walls. A `.ai4` name snapshot cannot
bind a session. A manifest URI cannot replace the local hash.

## Usage

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
result = verify_report_binding(attestation, report, trust=TrustContext.from_identity(identity), clock=FixedClock(now))
assert result.verdict == "matched"
```
