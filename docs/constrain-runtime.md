# Public constrained runtime (PR-A)

`ai4.constrain` **productizes the frozen condition-D architecture**.

This is an architectural/research decision about which controller the
library exposes. It is **not** a claim that D won Stage 2D.

- Stage 2D did **not** establish D as superior to C.
- The frozen Stage 2D evidence classification remains
  **`null_retained_D_adds_cost`**.
- Do not retune shards, thresholds, or arbitration from that result.

This wrapper is not a new evaluator and not a change to Stage 2 evidence.
Multi-turn state, JSONL traces, and shard cards are documented in
`docs/constrain-session.md`.

## Call

```python
from ai4.constrain import run, evaluate, DecisionReport

report = run("Please give a brief, checkable outline of options and limits.")
assert isinstance(report, DecisionReport)
print(report.decision, report.final_output)

scored = evaluate("Here is a brief, checkable answer about options.")
```

`run` wraps `ConstrainedAgent` condition D (per-shard scores, at most two
revision rounds, hard-fail refuse). `evaluate` scores existing text with
the same rubrics and first-round middleware action; it does not call a
model.

## DecisionReport

Stable JSON document (`schema_version` `0.1.0`) with:

- `outcome_kind`: `constraint` or `execution`
- `decision`: `accept` / `revise` / `refuse`, or `null` on execution failure
- `terminal`: a frozen loop label, or `null` when the loop did not run
  (`evaluate` mode). Frozen labels are `accepted`, `revision_exhausted`,
  `refused`, `timed_out`, `budget_exhausted`, `repeated_candidate` only.
- `initial_proposal`
- per-shard scores, `passed`, applicability projection, reasons
- arbitration, or `null` if no candidate was evaluated
- `revision_trace` captured from the live loop (not replayed)
- `final_output`
- telemetry and evaluator/runtime versions, including `evidence_class`
- `proposal`: `{provider_id, model, resolved_as}` — auditable proposal-backend
  identity, **not** governing policy. `resolved_as` is `config`,
  `explicit_argument`, `custom_object`, `evaluate_only`, or
  `legacy_telemetry` (schema 0.1.0 reports that only recorded provider/model
  on telemetry). Old reports without this block remain loadable.

Timeout or zero-budget before any candidate is **execution**, not a
constraint refuse. In that case `decision` is `null` and
`shard_evaluations` / `arbitration` are `null`. Empty-string scores from
the frozen agent must not appear as “all shards passed.”

On a constraint refuse, shard evaluations are the last failing candidate,
not a re-score of the safe refusal text.

### `prompt_specified_shards`

This argument is a **prompt annotation**, the same role `specified_shards`
has in the frozen experiment fixture. It does **not** select a subset of
shards that govern the decision.

Frozen D **always evaluates and enforces all five required shards**.
`shard_control_scope` is `all_required_v0.1`. `enforced` is true on every
scored shard. When the annotation is non-empty, unspecified shards are
still scored and still participate in arbitration; their projected
`verdict` is `not_applicable` only as the frozen applicability
projection, not as a control skip.

`candidate_evaluated` is false when the loop never scored a candidate
(timeout or zero budget before the first completion).

## Privacy

Default product reports **redact** SSN-like numbers, emails, phone
numbers, address-like PII already recognized by the frozen privacy
rubric (`lives at` / `home address is` plus the following address
material), and actual password assignments in textual fields.

Address spans follow an explicit street / unit / city-state-ZIP rule.
Quotes, parentheses, abbreviation periods, parenthesized units, and
newline/CRLF continuation stay inside the span. A completed street that
is not followed by a unit or city-state-ZIP is a sentence boundary —
capitalized or ALL-CAPS prose after that period is not consumed.

Password assignment is parsed from clause context (`password is:`,
`password is :`, `password:`, `password is <value>`). A single assigned
value — including letters-only credentials such as `secret` — is
removed. A multi-word complement in the same clause is predicate prose
(“a password is required to continue”, “the password is case sensitive”,
“your password is safe”).

Scores are unchanged. Pass `redact=False` only for trusted local
analysis. CLI default is redacted; `--no-redact` writes raw content.

Metadata-key filtering is not a substitute for this policy.

## CLI

```bash
python -m ai4.constrain run --prompt "Please give a brief, checkable outline of options."
python -m ai4.constrain evaluate --text "Here is a brief, checkable answer."
ai4-constrain run --prompt-file prompt.txt --output report.json
```

CLI exit codes:

| Code | Meaning |
| --- | --- |
| 0 | constraint accept |
| 1 | configuration / runtime failure (no usable report) |
| 2 | constraint revise |
| 3 | constraint refuse |
| 4 | timeout / budget / execution failure |

A report is still written for 0/2/3/4. Default stdout/JSON is redacted.

Default provider is the offline mock. Live uses the existing fail-closed
spend gates; do not pass secrets on the command line.

This CLI is separate from `python -m src.main`.

## Configuration

`RuntimeConfig.evaluator_id` and `provider_id` are resolved. Unknown ids
fail closed. There is no decorative unused config.

`provider_id` selects the proposal backend only. It is recorded on
`DecisionReport.proposal` / telemetry for audit. It is **not** part of
`SessionPolicyIdentity` and is **not** a policy stamp on `versions`.

## Proposal provider policy wall

Proposal backends emit candidate text. They do not govern.

Changing the proposal provider or model may change candidate text and the
resulting accept/revise/refuse outcome. It must **not** change:

- evaluator identity
- rubric set
- thresholds
- arbitration
- enforced shard set
- shard-control semantics
- revision bounds
- refusal semantics
- `RuntimeConfig` security settings
- `SessionPolicyIdentity`

**Provider interchange does not demonstrate alignment persistence across models.**
This is a software/control invariant: the same frozen evaluator, rubrics,
thresholds, and D controller still run. It is not evidence that two models
are equivalently aligned.

Custom proposal objects must expose a non-empty `name` or `provider_id`.
Identities that collide with evaluator ids (for example `v0.1-regex`) or
with policy/control field names fail closed. Provider `completion.metadata`
is untrusted telemetry: only an explicit allowlist of fields is accepted
(currently empty; frozen mock/live completions carry no metadata). Nested
objects, secret-shaped keys, policy-shaped keys, and unknown keys fail
closed. Call `kind` (`complete` / `revise` / `supplied`) is determined by
AI⁴'s execution path, not by provider metadata. Dual-role objects that
implement both proposal and evaluation cannot cross the call-site
boundary: passing the same object as both `provider` and `evaluator`
fails closed, and a provider is never used as the evaluator.

Governing evaluator identity is established and preflighted on every
`run()` path **before** any `complete()` / `revise()`. A missing, empty,
malformed, or unknown evaluator identity fails closed without proposal
generation, network, or spend.

`evaluate()` does not call a proposal backend. Its proposal identity is
`provider_id=none`, `resolved_as=evaluate_only`.

## Extension points

Internal constructors live in `ai4.constrain.ext` and are not a substitute
for `run` / `evaluate`.

- `session_store()` — in-memory by default; a directory path selects JSON
  snapshots used by `ConstrainedSession`. Constructor/runtime config is
  authority on restore; persisted `redact` / `include_history` are
  validation metadata, not governing settings.

Only evaluator `v0.1-regex` is shipped. Unknown evaluator ids still fail
closed.

## Fail-closed rules

The runtime does not skip a required shard, swap in an unknown
evaluator, or fall back to an unconstrained completion when a required
step cannot run. Custom evaluators are preflighted and guarded so an
incomplete score cannot enter the D loop. Governing evaluator identity
is validated on `run()` before any proposal `complete()` / `revise()`.
Unknown proposal-provider strings fail closed. A session revalidates the
evaluator object about to be used against the identity bound at
construction/load and fails closed without writing state. Evaluator
interchange is not part of this runtime.

## What this does not change

YAML rubrics, `src/shards/*`, arbitration, middleware, the D controller,
Stage 2C/2D fixtures, hashes, reports, and preserved results stay the
frozen v0.1 behavior.
