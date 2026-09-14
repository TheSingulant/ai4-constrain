# Architecture

## Layers

1. **Research harness (`src/`)** — offline experiment path and frozen shard machinery. Described in `docs/protocol-v0.1.md`.
2. **Product runtime (`ai4.constrain`)** — callable `run` / `evaluate`, `DecisionReport`, policy walls. See `docs/constrain-runtime.md`.
3. **Sessions (`ConstrainedSession`)** — persistent constrained state across turns. See `docs/constrain-session.md`.
4. **Optional hybrid governing (v0.7)** — packaged semantic observe/findings/fuse primitives plus `_v07_3a`/`_v07_3b`/`_v07_3c` continuity and activation. Default **OFF** unless `RuntimeConfig.integration` carries a validated `GoverningIntegration`.
5. **Sibling identity (`ai4.identity`)** — offline provenance kernel and `.ai4` discovery adapter. Not imported by `run` / `evaluate` / session walls. See `docs/identity.md` and `docs/identity-resolution.md`.

## Control walls

| Role | May do | Must not do |
| --- | --- | --- |
| Proposal provider | Emit candidate text | Set rubrics, thresholds, arbitration, refusal policy |
| Evaluator | Score under frozen contract | Define packaged policy or terminal vocabulary as authority |
| Product policy | Own packaged YAML / semantic artifacts | Be rewritten by model output or session JSON |
| Identity / naming | Bind provenance and resolve names | Become trust proof or constraint-policy authority |

## Request flow

```
prompt (+ optional session history as untrusted context)
  → provider.complete / revise (candidate)
  → evaluator scores (overlay; fail closed on bad shapes)
  → constraint middleware + arbitration (frozen D bounds)
  → DecisionReport
```

When hybrid integration is configured, `run()` may route through the `_v07_3c` entry before the classic path; absent integration preserves v0.6 behavior.

## Evidence honesty

Stage 2D did not establish D as superior to C. Frozen evidence class remains `null_retained_D_adds_cost`.

This document is not a production host design and does not describe live bot deployment.
