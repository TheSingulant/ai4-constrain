"""Locate frozen v0.1 YAML without depending on a git checkout.

The experimental loader reads ``src.paths.RUBRICS_DIR`` (repo-relative).
A wheel install does not ship that layout, so the product runtime loads
the packaged copies under ``ai4.data`` and hands each file to the frozen
``load_rubric_file``. Those copies must stay byte-identical to
``rubrics/v0.1``.
"""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path

from src.shards.shard_loader import REQUIRED_IDS, Rubric, load_rubric_file

from ai4.constrain.errors import ConstraintExecutionError

_PACKAGE = "ai4.data"
_RELATIVE = ("rubrics", "v0.1")


def packaged_rubric_bytes() -> dict[str, bytes]:
    """Read packaged YAML bytes keyed by shard id. Fail closed."""
    root = files(_PACKAGE).joinpath(*_RELATIVE)
    payload: dict[str, bytes] = {}
    for shard_id in REQUIRED_IDS:
        traversable = root.joinpath(f"{shard_id}.yaml")
        try:
            payload[shard_id] = traversable.read_bytes()
        except Exception as exc:
            raise ConstraintExecutionError(
                f"Packaged rubric {shard_id!r} is missing or unreadable: {exc}"
            ) from exc
        if not payload[shard_id].strip():
            raise ConstraintExecutionError(f"Packaged rubric {shard_id!r} is empty")
    return payload


def load_packaged_rubrics() -> tuple[Rubric, ...]:
    """Load the five frozen rubrics from package data. Fail closed."""
    root = files(_PACKAGE).joinpath(*_RELATIVE)
    loaded: dict[str, Rubric] = {}
    for shard_id in REQUIRED_IDS:
        traversable = root.joinpath(f"{shard_id}.yaml")
        try:
            with as_file(traversable) as path:
                loaded[shard_id] = load_rubric_file(Path(path))
        except ConstraintExecutionError:
            raise
        except Exception as exc:
            raise ConstraintExecutionError(
                f"Failed to load packaged rubric {shard_id!r}: {exc}"
            ) from exc
    missing = [item for item in REQUIRED_IDS if item not in loaded]
    if missing:
        raise ConstraintExecutionError(f"Packaged rubric set incomplete: {missing}")
    return tuple(sorted((loaded[item] for item in REQUIRED_IDS), key=lambda r: r.priority))
