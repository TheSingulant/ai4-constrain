"""Filesystem anchors for rubrics and fixtures."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUBRICS_DIR = REPO_ROOT / "rubrics" / "v0.1"
FIXTURES_DIR = REPO_ROOT / "fixtures"
DEFAULT_FIXTURE = FIXTURES_DIR / "pilot_prompts.jsonl"
DEV_SET = FIXTURES_DIR / "dev_set.jsonl"
HELDOUT_V01 = FIXTURES_DIR / "heldout_v0.1.jsonl"
