"""Frozen Stage 2D constants.

30-60% revision rate is a design difficulty target for case authoring.
It is not a knob for retuning C or D after seeing held-out behavior.
"""

from __future__ import annotations

from pathlib import Path

from src.paths import REPO_ROOT

STAGE2D_PROTOCOL = "stage2d-stress-v0.1"
STAGE2D_HELDOUT_SPLIT = "heldout_stress_v0.1"
STAGE2D_DEV_SPLIT = "stage2d_dev"

# Parallel to v0.1 seed 0xA1401001. 2D marker is intentional.
STAGE2D_HELDOUT_SEED = 0xA1402D01
STAGE2D_HELDOUT_N = 120
STAGE2D_DEV_N = 24

# Future paid Stage 2D hard cap. Fail closed if a live path asks for more.
STAGE2D_MAX_SPEND_USD = 2.0

STAGE2D_CONDITIONS = ("A", "B", "C", "D")
STAGE2D_PRIMARY_CONDITIONS = ("C", "D")

STAGE2D_CATEGORIES = (
    "truth_vs_compassion",
    "autonomy_vs_harm",
    "privacy_vs_safety",
    "truth_vs_privacy",
    "multi_principle",
    "adversarial_evaluator_injection",
    "clarification",
    "benign_controls",
    "overcautious_refusal",
)

# Frozen design quotas. Sum must equal STAGE2D_HELDOUT_N.
STAGE2D_CATEGORY_COUNTS: tuple[tuple[str, int], ...] = (
    ("truth_vs_compassion", 16),
    ("autonomy_vs_harm", 16),
    ("privacy_vs_safety", 16),
    ("truth_vs_privacy", 16),
    ("multi_principle", 16),
    ("adversarial_evaluator_injection", 12),
    ("clarification", 10),
    ("benign_controls", 10),
    ("overcautious_refusal", 8),
)

# Dev quotas. Sum must equal STAGE2D_DEV_N. Independent wording from held-out.
STAGE2D_DEV_CATEGORY_COUNTS: tuple[tuple[str, int], ...] = (
    ("truth_vs_compassion", 3),
    ("autonomy_vs_harm", 3),
    ("privacy_vs_safety", 3),
    ("truth_vs_privacy", 3),
    ("multi_principle", 3),
    ("adversarial_evaluator_injection", 2),
    ("clarification", 2),
    ("benign_controls", 3),
    ("overcautious_refusal", 2),
)

# Principle names used in cases. Mapped to frozen v0.1 shard ids for D / metrics.
STAGE2D_PRINCIPLES = (
    "truth",
    "compassion",
    "autonomy",
    "privacy",
    "harm aversion",
)

PRINCIPLE_TO_SHARD = {
    "truth": "truth",
    "compassion": "compassion",
    "autonomy": "autonomy",
    "privacy": "privacy",
    "harm aversion": "harm_aversion",
    "harm_aversion": "harm_aversion",
}

SHARD_TO_PRINCIPLE = {
    "truth": "truth",
    "compassion": "compassion",
    "autonomy": "autonomy",
    "privacy": "privacy",
    "harm_aversion": "harm aversion",
}

FROZEN_TERMINALS = (
    "accepted",
    "revision_exhausted",
    "refused",
    "timed_out",
    "budget_exhausted",
    "repeated_candidate",
)

FIXTURES_STAGE2D = REPO_ROOT / "fixtures" / "stage2d"
STAGE2D_DEV_SET = FIXTURES_STAGE2D / "dev_set.jsonl"
STAGE2D_HELDOUT = FIXTURES_STAGE2D / "heldout_stress_v0.1.jsonl"
STAGE2D_HELDOUT_SHA256 = FIXTURES_STAGE2D / "heldout_stress_v0.1.sha256"
STAGE2D_HELDOUT_GOLD = FIXTURES_STAGE2D / "heldout_stress_v0.1.gold_notes.jsonl"
STAGE2D_DEV_GOLD = FIXTURES_STAGE2D / "dev_set.gold_notes.jsonl"

ARTIFACTS_PRERUN = REPO_ROOT / "artifacts" / "stage2d-prerun"
ARTIFACTS_HUMAN_REVIEW = REPO_ROOT / "artifacts" / "stage2d-human-review"

# Authoring intent only. Not a live measurement and not a C/D tuning target.
DESIGN_REVISION_RATE_LOW = 0.30
DESIGN_REVISION_RATE_HIGH = 0.60


def principles_to_shards(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    mapped: list[str] = []
    for name in names:
        key = str(name).strip().lower()
        if key not in PRINCIPLE_TO_SHARD:
            raise ValueError(f"Unknown principle {name!r}")
        shard = PRINCIPLE_TO_SHARD[key]
        if shard not in mapped:
            mapped.append(shard)
    return tuple(mapped)


def assert_category_counts() -> None:
    total = sum(count for _, count in STAGE2D_CATEGORY_COUNTS)
    if total != STAGE2D_HELDOUT_N:
        raise ValueError(f"Held-out category counts sum to {total}, expected {STAGE2D_HELDOUT_N}")
    dev_total = sum(count for _, count in STAGE2D_DEV_CATEGORY_COUNTS)
    if dev_total != STAGE2D_DEV_N:
        raise ValueError(f"Dev category counts sum to {dev_total}, expected {STAGE2D_DEV_N}")
    held_cats = tuple(name for name, _ in STAGE2D_CATEGORY_COUNTS)
    if held_cats != STAGE2D_CATEGORIES:
        raise ValueError("Held-out category order must match STAGE2D_CATEGORIES")
