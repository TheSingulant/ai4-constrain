# Identity resolution / discovery adapter (PR-F)

`ai4.identity.resolve` is a **discovery sibling** of the offline identity
kernel. It is not the kernel. It is not `ai4.constrain`.

**Identity is not trust. Resolution is not verification. Naming is not policy authority.**

> A signed AI⁴ identity record binds claims and provenance to an agent identity; it does not prove the agent is aligned, safe, or correctly governed.

This adapter resolves an external `.ai4` name into hash-bound provenance
inputs for the existing identity kernel. The naming layer does not become
verification, current trust, or constraint-policy authority.

Live lookup is not imported by `run()` / `evaluate()` / session walls.
`python -m ai4` remains the constrain CLI. `python -m ai4.identity` is
this sibling CLI.

## What this is

- Abstract `Resolver` with `resolve(name) -> Mapping[str, str]`
- First slice: `FileResolver` (offline JSON fixtures). `MemoryResolver`
  for tests. No Unstoppable SDK, no web3, no network default.
  Directory lookup stays inside the resolved records directory.
  FileResolver freshness is always `fixture`; local JSON cannot claim
  `live`.
- `DiscoveryRecord` (`ai4.identity.discovery.v1`) outside the kernel
- Fetch of attestation bytes with a size cap, then published SHA-256
  checks, then existing `AgentAttestation.from_dict` / `verify_*`
- Post-integrity `NameRecordSnapshot(source="local_snapshot")` as an
  audit capture. It is **not** written back into the signed identity.
- Sibling CLI with five independent statuses

## What this is not

- Not a redesign of the v0.5 identity kernel
- Not default network access, Unstoppable REST, or an HTTP service
- Not `TrustContext` invented from a name record
- Not policy feedback into rubrics, thresholds, arbitration, evaluators,
  providers, `RuntimeConfig`, or `SessionPolicyIdentity`
- Not a claim that a resolved name is aligned, safe, or correctly governed
- Not `SAFE` / `ALIGNED` / accept / revise / refuse

## DiscoveryRecord (`ai4.identity.discovery.v1`)

Strict object. Extra fields fail closed. Resolver output is untrusted
discovery metadata only.

| Field | Rule |
| --- | --- |
| `schema_id` | `ai4.identity.discovery.v1` |
| `name` | ASCII lowercase, kernel name regex, must end in `.ai4` |
| `identity_id` | empty or kernel `identity_id` grammar (optional until parse) |
| `controller_public_key` | 32-byte Ed25519 public key, lowercase hex |
| `manifest_sha256` | SHA-256 of AgentIdentity JCS bytes |
| `attestation_sha256` | SHA-256 of exact hosted attestation bytes, or empty |
| `attestation_uri` | locative only; never overrides hashes |
| `captured_at` | RFC 3339 UTC |
| `freshness` | `kind` is `live`, `cached`, or `fixture`; `age_s`; `max_age_s` or null. FileResolver always reports `fixture`. JSON `freshness_kind` is ignored and cannot claim live. |
| `resolver_id` | audit (`file`, `memory`, `uns_rest`); not trust |

`freshness.kind` must not be copied into `NameRecordSnapshot.source`.

## Resolver boundary

```python
class Resolver(Protocol):
    def resolve(self, name: str) -> Mapping[str, str]:
        ...
```

`resolve()` returns the raw Unstoppable-style key/value record set. It
does not verify signatures, fetch manifests, construct `TrustContext`, or
talk to `ai4.constrain`.

## Integrity-critical record keys

Required before fetch:

- `ai4.identity.controller_public_key`
- `ai4.identity.manifest_sha256`

Strongly recommended:

- `ai4.identity.identity_id`
- `ai4.identity.attestation_sha256`

Locative only (never override hashes):

- `ai4.identity.attestation_uri`
- `ai4.identity.manifest_uri`

Ignored (never trusted, never forwarded into runtime): `crypto.*`,
`token.*`, `dweb.*`, `whois.*`, `meta.owner`, `meta.tokenId`,
`forwarding.url`, wallet/token fields, and evaluator/provider/policy-shaped
fields.

## Honest pipeline

1. Normalize the `.ai4` name (ASCII, lowercase, `.ai4` TLD, reject
   non-ASCII, reject `xn--`, reject homoglyph/punycode paths).
2. `Resolver.resolve` -> untrusted records -> `DiscoveryRecord`.
3. Fetch attestation bytes from `attestation_uri` only. Do not fetch
   `identity.manifest_uri`. Do not follow `forwarding.url`.
4. If `attestation_sha256` is present, require SHA-256 of the exact
   hosted bytes.
5. Parse `AgentAttestation`. Recompute identity JCS SHA-256. Check
   published controller key and optional published `identity_id`.
6. Require the queried name already in signed `AgentIdentity.name_records`.
   Empty `name_records` remains valid for local kernel verify. It is
   fail-closed for live `.ai4` discovery.
7. Construct `NameRecordSnapshot(source="local_snapshot")`. Do not merge
   it into identity bytes.
8. Existing kernel `verify_attestation_signature` /
   `verify_attestation(trust=...)` / optional `verify_report_binding`.

Operators supply current trust with `--trust FILE` only. There is no
`--trust-from-resolved`.

## Name normalization

- ASCII only; lowercase
- Must match kernel name regex `^[A-Za-z0-9._:-]{1,253}$`
- Must end in `.ai4`
- Reject non-ASCII
- Reject punycode `xn--`
- Reject other Unstoppable TLDs in this slice

## CLI

```bash
python -m ai4.identity resolve researcher.ai4 --resolver file --records fixtures/identity/researcher.ai4.json
python -m ai4.identity verify researcher.ai4 --resolver file --records fixtures/identity/researcher.ai4.json \
    --trust fixtures/identity/researcher.ai4.trust.json --report fixtures/identity/researcher.ai4.report.json
```

Human output always includes the governing principle and these five
independent lines:

```
NAME RESOLVED: yes | no
MANIFEST INTEGRITY VERIFIED: yes | no
SIGNATURE VALID: yes | no | not_requested
CURRENT TRUST MATCHED: yes | no | not_requested
REPORT BINDING MATCHED: yes | no | unbound | mismatch | expired | untrusted_signer | not_requested
```

Omitted `--trust` yields `CURRENT TRUST MATCHED: not_requested`, not
matched. JSON stdout uses the same five statuses and must not carry
`safe`, `aligned`, `accept`, `revise`, `refuse`, or `decision` keys.

Identity CLI exit codes (not constrain codes):

| Code | Meaning |
| --- | --- |
| 0 | All requested checks passed |
| 1 | Fail-closed discovery/config |
| 5 | Signature invalid |
| 6 | Current trust not matched when `--trust` was supplied |
| 7 | Report binding not `matched` when `--report` was supplied |

Never reuse 2/3 as revise/refuse. A matched name must never resolve to
accept.

## Failure semantics

Fail closed: missing/unresolved `.ai4`; malformed records; oversized
records or fetch; stale past max-age; raw attestation hash mismatch;
manifest hash mismatch; controller-key mismatch; identity_id mismatch;
queried name absent from signed `name_records`; multiple gateway digest
disagreement (no majority vote); non-`.ai4` TLD; non-ASCII/punycode;
unknown algorithm; unknown resolver kind.

Use existing kernel verdicts for report binding: `unbound`, `mismatch`,
`expired`, `untrusted_signer`, `matched`.

URI change without hash change is metadata, not a new identity, if the
bytes still match. A controller-key change on the name cannot rotate
`TrustContext`. Only `verify_rotation` against a pinned previous context
can.

## Isolation

- `ai4.constrain` does not import identity or resolve
- Kernel modules do not import `resolve`, `urllib`, or `http`
- `ai4.identity.__init__` does not export resolver types
- `python -m ai4 run` remains constrain
- Discovery objects cannot be providers or evaluators
- Resolver data cannot enter `RuntimeConfig` or `SessionPolicyIdentity`
- `EVIDENCE_CLASS` remains `null_retained_D_adds_cost`

## Residual risks

- Compromised current controller key without a prior rotation
- Operator who pins a malicious `TrustContext` out of band
- Unstoppable custom records are not validated on-chain (when REST is
  added later)
- Name-to-identity binding is weaker than verification; currentness
  still requires an operator `TrustContext` pin
- No CRL; skip-version rotations abandon skipped versions
