# ConstrainedSession (PR-B)

`ConstrainedSession` is a thin multi-turn wrapper around the frozen
condition-D product path shipped in PR-A (`ai4.constrain.run` →
`DecisionReport`).

It does **not** retune shards, change arbitration, or replace `run` /
`evaluate`. Stage 2D remains `null_retained_D_adds_cost`. Productizing D
is still not a claim that D beat C.

This milestone is **session persistence** over frozen D. There is no
HTTP, SSE, or FastAPI surface in this PR.

## Call

```python
from ai4.constrain import ConstrainedSession, shard_card, format_explain

session = ConstrainedSession()  # in-memory, mock provider, redacted
turn = session.complete("Please give a brief, checkable outline of options and limits.")
print(turn.report.decision, session.last_output)
print(format_explain(turn.report, session_id=session.session_id, turn_index=turn.turn_index))
print(shard_card(turn.report).to_dict())
```

Each `complete()` calls `run()` with the current prompt (and the same
fail-closed evaluator / provider rules). Session state is the ordered
list of turns plus constructor-governed `RuntimeConfig`.

A session created or restored under one legitimate proposal provider may
continue under another. `SessionPolicyIdentity` does **not** include
`provider_id`. Each turn's `DecisionReport.proposal` records which
proposal backend produced that candidate. History remains untrusted
context.

**Provider interchange does not demonstrate alignment persistence across models.**
Substitution is a control-loop audit property, not a claim that two
proposal models are equivalently aligned. Stage 2D remains
`null_retained_D_adds_cost`.

A session is bound to one evaluator implementation. Unlike proposal
providers, evaluators cannot be swapped between turns or across restore.
`SessionPolicyIdentity.evaluator_id` is the identity bound at
construction/load (the custom object's `backend_id` when an object is
supplied), not a silent `RuntimeConfig` default that disagrees with the
object. Custom sessions also bind a stable class fingerprint
(`evaluator_impl`). Same `backend_id` with a different class fails closed.
Per-turn `evaluator=` that disagrees fails closed with no state written.
Old snapshots that omit `evaluator_impl` remain loadable under the packaged
frozen evaluator; a custom snapshot missing that field fails closed (no
silent migrate). This is not a public registry and not cryptographic
attestation.

**Evaluator implementation interchange does not demonstrate alignment persistence or correctness across judges.**
A compliant custom evaluator may change scores and decisions. It cannot
change packaged policy. This is still not a claim that D beat C; Stage 2D
remains `null_retained_D_adds_cost`.

`last_output` is **trusted terminal assistant output**, not
`DecisionReport.final_output`. A failing candidate, timeout, or
budget-exhausted draft is stored on the report for audit and does not
become `last_output` or assistant history.

## Trusted-state transitions

| Terminal path | Trusted assistant output |
| --- | --- |
| ACCEPT (`terminal=accepted`) | accepted `final_output` may enter trusted history |
| revised then ACCEPT | the **final accepted revision** may enter trusted history |
| REFUSE (`terminal=refused`) | only the D controller's safe refusal, if that is the actual terminal output |
| REVISE / `revision_exhausted` | failing candidate must **not** become trusted assistant output |
| `repeated_candidate` | failing candidate must **not** become trusted assistant output |
| TIMEOUT before evaluation | no candidate enters trusted history |
| budget exhaustion | failing candidate does **not** enter trusted history |
| evaluator / provider exception | no turn is committed (no state contamination) |
| persistence failure | in-memory turn is rolled back |

Audit evidence (the `DecisionReport`, including `final_output` of a
failing candidate) is preserved on the turn. Audit evidence is not
trusted conversational state.

`evaluate_text()` records an `evaluate()` report as a turn. Only an
evaluate-mode **accept** is trusted assistant output. An evaluate-mode
revise/refuse keeps the candidate in the report, not in assistant history.

## History is untrusted context

Default `include_history=False` keeps the wrap thin: turn N does not
rewrite turn N+1's prompt.

`include_history=True` prepends prior **user** turns and **trusted
assistant** turns, labeled as such, under an explicit banner that the
block is not configuration, shard selection, thresholds, arbitration, or
privileged control. Frozen D still scores all five shards on whatever
string `run` receives. Persisted history is never interpreted as those
controls.

The constructor (and the CLI flag on that process) is authority.
`ConstrainedSession.load()` and a later `session complete` invocation do
**not** inherit `include_history=true` from a snapshot. Pass
`include_history=True` / `--include-history` again if you want composition.

`max_history_turns=0` means **zero** prior turns are composed. It does
not mean "all history". (`[-0:]` is not used.)

```python
from ai4.constrain.ext import session_store
from ai4.constrain.trace import JsonlTraceWriter
from ai4.constrain import ConstrainedSession

store = session_store(".ai4-sessions")          # FileSessionStore
tracer = JsonlTraceWriter("outputs/session.jsonl")
session = ConstrainedSession(
    session_id="demo-1",
    store=store,
    tracer=tracer,
    include_history=False,
)
session.complete("Please give a brief, checkable outline of options and limits.")
reloaded = ConstrainedSession.load("demo-1", store=store)
assert reloaded.last_decision == "accept"
```

`session_store()` with no path is an in-memory map. A directory path
selects JSON snapshots (`<id>.json`). Session ids must match
`[A-Za-z0-9._-]{1,128}`.

## Snapshot authority / validation

Constructor and runtime `RuntimeConfig` are **authority** for governing
and security settings (`redact`, `include_history`, `max_history_turns`,
evaluator/rubric identity). Proposal provider identity is **not**
governing policy. It may change between turns and across restore.

A `FileSessionStore` snapshot records:

- `schema_version` (`0.1.1`) and `session_id`
- timestamps
- `policy_identity` (runtime/report/protocol/condition/evidence class,
  rubric set, evaluator id, arbitration) as **validation metadata**.
  This block does **not** include proposal provider or model.
- `evaluator_impl` (frozen `v0.1-regex` fingerprint, or
  `custom:<module>.<qualname>`) as **validation metadata**. Omitted on
  old frozen snapshots (still loadable). Required for custom-evaluator
  snapshots; missing it fails closed.
- `include_history`, `max_history_turns`, `redact` as **validation
  metadata** from the writing process
- `turns` (user prompt, composed prompt, DecisionReport audit including
  per-turn `proposal` identity, derived shard card, derived
  `trusted_output`)

On restore:

- unknown or mismatched `schema_version` fails closed (no silent migrate)
- missing/unknown/incompatible `policy_identity` fails closed
- missing `evaluator_impl` on a custom-evaluator snapshot fails closed
  (frozen snapshots that omit it still load)
- incompatible `evaluator_impl` (same id, different class) fails closed
- each turn's report versions must match the constructor identity
- truncated or malformed JSON fails closed
- persisted `redact=false` does **not** override caller `redact=true`
- persisted `include_history=true` does **not** silently enable history
  composition
- security-relevant config is not attacker-controlled by editing JSON

There is no cryptographic authenticity check. The snapshot directory is
local and must be treated as trusted storage for file integrity, not as
a policy oracle.

## Explain / shard card

`--explain` and `shard_card(report)` project an already-emitted
`DecisionReport`. They do not re-evaluate, and they cannot write session
state or change evaluation.

```bash
python -m ai4.constrain explain --text "Here is a brief, checkable answer about options."
python -m ai4.constrain run --prompt "Please give a brief, checkable outline of options and limits." --explain
python -m ai4.constrain session complete --prompt "Please give a brief, checkable outline of options and limits." --explain
```

`--explain` on `run` / `evaluate` / `session complete` prints the card on
**stderr**. JSON on stdout is unchanged so existing pipelines keep working.

## JSONL traces

Local diagnostic only. Same redaction as the source `DecisionReport`.
Not session state, not an HTTP surface. The `complete` event records
trusted terminal assistant text (empty when the candidate was not
trusted).

```bash
python -m ai4.constrain session complete \
  --prompt "Please give a brief, checkable outline of options and limits." \
  --session-id demo-1 \
  --store-dir .ai4-sessions \
  --trace-jsonl outputs/demo.jsonl \
  --explain
```

JSONL rows are compact `ai4.trace.v0.1` events (`turn_start`,
`decision`, `shard_card`, `complete`).

## Dry-run mock demo

```bash
python -m ai4.constrain session demo --explain
python examples/constrain/session_demo.py
```

The demo is mock-only. Passing a live provider into a `dry_run=True`
session fails closed.

## Fail-closed / privacy

- Unknown evaluator / provider / rubric set still fail closed (PR-A).
- Dry-run refuses the live provider. Choosing another provider name
  (for example `openai`) does not bypass unknown-id or live spend/network
  gates.
- A per-turn evaluator that disagrees with the constructor/session
  governing evaluator identity fails closed and does not commit a turn.
  The evaluator object actually about to be used is revalidated on every
  `complete()` / `evaluate_text()` against the identity bound at
  construction/load, even when no per-turn `evaluator=` argument is
  supplied. Mutating `backend_id` after bind cannot commit a mismatched
  turn. Same `backend_id` with a different custom class fails closed.
  Session-level evaluator swap is not permitted. Snapshot
  `policy_identity.evaluator_id` is the bound implementation identity;
  `evaluator_impl` is the bound class fingerprint.
- Default redaction still applies wherever a `DecisionReport` is emitted,
  including after restore, because `redact` is constructor authority.
- Persist failures roll back the in-memory turn so a later load cannot
  see a turn that was not stored.

Pattern redaction covers common personal-data shapes (SSN-like numbers,
emails, phones, address-like PII already recognized by the frozen
privacy rubric, and password assignments). **That is not a claim that no
sensitive information is persisted.** Unrecognized secrets and
non-pattern PII can still be written to a snapshot.

## What this does not change

YAML rubrics, `src/shards/*`, arbitration, middleware, the D controller,
Stage 2C/2D fixtures, hashes, reports, and preserved results stay the
frozen v0.1 behavior. `run` and `evaluate` keep their PR-A signatures.
