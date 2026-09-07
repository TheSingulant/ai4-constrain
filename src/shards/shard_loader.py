"""Load versioned shard rubrics from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.paths import RUBRICS_DIR
from src.shards.models import Criterion, Rubric

REQUIRED_IDS = ("truth", "compassion", "autonomy", "privacy", "harm_aversion")


class RubricLoadError(ValueError):
    """Invalid or incomplete rubric set."""


def _as_tuple(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)  # type: ignore[arg-type]


def _criterion(raw: dict) -> Criterion:
    return Criterion(
        id=str(raw["id"]),
        weight=float(raw.get("weight", 1.0)),
        description=str(raw.get("description", "")),
        fail_if_regex=_as_tuple(raw.get("fail_if_regex")),
        pass_if_regex=_as_tuple(raw.get("pass_if_regex")),
        conflicts_with=_as_tuple(raw.get("conflicts_with")),
    )


def load_rubric_file(path: Path) -> Rubric:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RubricLoadError(f"Rubric {path} is not a mapping")
    kind = str(data.get("kind", "soft"))
    if kind not in {"hard", "soft"}:
        raise RubricLoadError(f"Rubric {path} has invalid kind {kind!r}")
    criteria = tuple(_criterion(item) for item in data.get("criteria") or [])
    if not criteria:
        raise RubricLoadError(f"Rubric {path} has no criteria")
    return Rubric(
        id=str(data["id"]),
        version=str(data["version"]),
        title=str(data.get("title", data["id"])),
        kind=kind,
        priority=int(data.get("priority", 99)),
        pass_threshold=float(data.get("pass_threshold", 1.0)),
        description=str(data.get("description", "")).strip(),
        criteria=criteria,
    )


def load_rubrics(directory: Path | None = None) -> tuple[Rubric, ...]:
    """Load the five v0.1 rubrics, sorted by priority (lower is first)."""
    root = directory or RUBRICS_DIR
    if not root.is_dir():
        raise RubricLoadError(f"Rubric directory missing: {root}")
    loaded: dict[str, Rubric] = {}
    for path in sorted(root.glob("*.yaml")):
        rubric = load_rubric_file(path)
        loaded[rubric.id] = rubric
    missing = [item for item in REQUIRED_IDS if item not in loaded]
    if missing:
        raise RubricLoadError(f"Missing required rubrics: {missing}")
    extra = sorted(set(loaded) - set(REQUIRED_IDS))
    if extra:
        raise RubricLoadError(f"Unexpected rubrics in v0.1 set: {extra}")
    return tuple(sorted((loaded[item] for item in REQUIRED_IDS), key=lambda r: r.priority))
