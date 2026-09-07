# Cost estimate stub (v0.1)

Status: placeholder for a later spending-capped live run. This file does not enable paid calls. Offline pytest and mock experiments cost $0.00.

Do not start a live run from this document. Live calls still require `AI4_ENABLE_LIVE_LLM=1` and `AI4_MAX_SPEND_USD > 0`.

## Price table used

Model assumed: `gpt-4o-mini` (the default in `src/providers/live.py` and `.env.example`).

List prices used (OpenAI public list, checked 2026-09-06; mark as assumptions):

| Token class | USD per 1M tokens | Source assumption |
| --- | --- | --- |
| Input | 0.15 | OpenAI list for `gpt-4o-mini` |
| Cached input | 0.075 | OpenAI list; **not used** in this estimate |
| Output | 0.60 | OpenAI list for `gpt-4o-mini` |

Assumptions:

- Prices are list prices, not committed invoices, not Azure regional premiums, not batch discount.
- No prompt caching credit is applied.
- No vision, tools, or fine-tuning.
- Token counts below are planning guesses, not measured live usage.
- The live provider's current `USD_PER_TOKEN_PLACEHOLDER = 0.000002` is a conservative hook (`$2.00` per 1M tokens blended). It is **not** the table above. Do not treat `estimated_usd` from a live call as this stub until the provider is wired to the table.

## Workload assumed (not executed)

| Knob | Value | Why |
| --- | --- | --- |
| Split | held-out, N = 100 | Frozen file; not scored yet |
| Conditions | A, B, C, D | Full protocol |
| Max completions / item / condition | 3 | 1 first + 2 revises. C and D share this cap. |
| Mean input tokens / call | 800 | Prompt + system + prior draft/feedback guess |
| Mean output tokens / call | 250 | Short answers |
| Calls if every item uses the full budget | 100 * 4 * 3 = 1,200 | Worst case |
| Calls if A/B stay one-shot and C/D use 3 | 100 * (1 + 1 + 3 + 3) = 800 | More likely upper bound |
| Calls if A/B one-shot, C 3, D 2 | 100 * (1 + 1 + 3 + 2) = 700 | Mid case |

## Dollar math (gpt-4o-mini list)

Cost per call (assumed 800 in / 250 out):

- Input: `800 / 1e6 * 0.15 = $0.000120`
- Output: `250 / 1e6 * 0.60 = $0.000150`
- Per call: **$0.000270**

| Scenario | Calls | Estimated USD |
| --- | --- | --- |
| Mid (700 calls) | 700 | 0.19 |
| Likely upper (800 calls) | 800 | 0.22 |
| Worst (1,200 calls) | 1,200 | 0.32 |
| 2x token lengths (safety) | 1,200 | 0.65 |
| Dev set only (18 * 4 * 3) | 216 | 0.06 |

C versus D call budget is identical (max 1 first completion + 2 revises). Both can now accept after the first draft when no revision is warranted, so realized calls can fall below the cap. Worst case is still every item using the full budget: **1,200 calls / $0.32** (or $0.65 at 2x token lengths). C's draft-specific critique can be longer than a short D scorecard or shorter than a long one; that moves tokens inside the 800-token guess, not the call-count worst case. Item rows record `model_calls` and tokens so the difference is visible.

Rounded up for a first cap discussion: **$1.00** covers the held-out four-condition pass with a large token-length buffer. **$5.00** matches the README example cap and leaves room for a retry or a larger sample.

Evaluator JSON is not a live cost today. If a later LLM judge is added (one judge call per item per condition, 400 extra calls at the same token guess), add about **$0.11**. That judge is not in v0.1.

## What this stub is not

- Not a commitment to run paid jobs.
- Not a measurement from `LiveProvider`.
- Not a token-market or mint claim.
- Not an estimate for Telegram or Vultr hosting.
