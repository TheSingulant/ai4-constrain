# Public constrained runtime (PR-A)

`ai4.constrain` **productizes the frozen condition-D architecture**.

This is an architectural/research decision about which controller the
library exposes. It is **not** a claim that D won Stage 2D.

- Stage 2D did **not** establish D as superior to C.
- The frozen Stage 2D evidence classification remains
  **`null_retained_D_adds_cost`**.
- Do not retune shards, thresholds, or arbitration from that result.

This wrapper is not a new evaluator, not a session/HTTP service, and not
a change to Stage 2 evidence.

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

## Extension points (not implemented here)

Internal hooks live in `ai4.constrain.ext` and are not a stable product
surface. Session/HTTP raise. Only evaluator `v0.1-regex` is shipped.

## Fail-closed rules

The runtime does not skip a required shard, swap in an unknown
evaluator, or fall back to an unconstrained completion when a required
step cannot run. Custom evaluators are preflighted and guarded so an
incomplete score cannot enter the D loop.

## What this does not change

YAML rubrics, `src/shards/*`, arbitration, middleware, the D controller,
Stage 2C/2D fixtures, hashes, reports, and preserved results stay the
frozen v0.1 behavior.
