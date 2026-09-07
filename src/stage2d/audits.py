"""Helpers for Stage 2D contamination and fairness audits.

Written audits live in docs/. These functions back offline tests.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path

from src.paths import REPO_ROOT
from src.stage2d.constants import STAGE2D_DEV_SET, STAGE2D_HELDOUT
from src.stage2d.schema import Stage2DCase, load_cases

BANNED_SECRET_CUES = (
    "telegram",
    "vultr",
    "@ai4",
    "client transcript",
    "production log",
    "ai4_api_key",
    "sk-proj-",
    "sk-live-",
    "begin rsa private key",
    "bearer ",
)

V01_HELDOUT = REPO_ROOT / "fixtures" / "heldout_v0.1.jsonl"
V01_DEV = REPO_ROOT / "fixtures" / "dev_set.jsonl"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def prompt_set(cases: Iterable[Stage2DCase]) -> set[str]:
    return {_normalize(case.prompt) for case in cases}


def jsonl_prompts(path: Path) -> set[str]:
    prompts: set[str] = set()
    if not path.is_file():
        return prompts
    import json

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if isinstance(raw, dict) and "prompt" in raw:
            prompts.add(_normalize(str(raw["prompt"])))
    return prompts


def overlapping_prompts(left: Iterable[str], right: Iterable[str]) -> set[str]:
    return set(left) & set(right)


def scan_text_for_secrets(text: str) -> list[str]:
    lowered = text.lower()
    return [cue for cue in BANNED_SECRET_CUES if cue in lowered]


def scan_paths_for_secrets(paths: Iterable[Path]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in paths:
        found = scan_text_for_secrets(path.read_text(encoding="utf-8"))
        if found:
            hits[str(path)] = found
    return hits


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def contamination_report() -> dict:
    stage2d_dev = load_cases(STAGE2D_DEV_SET)
    stage2d_held = load_cases(STAGE2D_HELDOUT)
    overlap_dev_held = overlapping_prompts(prompt_set(stage2d_dev), prompt_set(stage2d_held))
    overlap_v01 = overlapping_prompts(
        prompt_set(stage2d_held),
        jsonl_prompts(V01_HELDOUT) | jsonl_prompts(V01_DEV),
    )
    fixture_paths = [
        STAGE2D_DEV_SET,
        STAGE2D_HELDOUT,
        REPO_ROOT / "fixtures" / "stage2d" / "heldout_stress_v0.1.gold_notes.jsonl",
        REPO_ROOT / "fixtures" / "stage2d" / "dev_set.gold_notes.jsonl",
    ]
    return {
        "stage2d_dev_n": len(stage2d_dev),
        "stage2d_heldout_n": len(stage2d_held),
        "exact_prompt_overlap_dev_heldout": sorted(overlap_dev_held),
        "exact_prompt_overlap_with_v01": sorted(overlap_v01),
        "secret_hits": scan_paths_for_secrets(fixture_paths),
    }
