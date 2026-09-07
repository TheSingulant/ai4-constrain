"""Frozen evaluator output schema and fail-closed JSON validation.

v0.1 runtime scoring is regex-deterministic (``ShardEvaluator``). There is
no LLM judge path in this tree. This module is scaffolding for the frozen
benchmark schema (per-shard applicability + verdict) so malformed
LLM-shaped JSON can be rejected before any later judge is wired in.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from src.shards.models import Evaluation
from src.shards.shard_loader import REQUIRED_IDS

SCHEMA_VERSION = "0.1.0"
FROZEN_SHARD_IDS = REQUIRED_IDS
FROZEN_VERDICTS = ("pass", "fail", "not_applicable")


class EvaluatorSchemaError(ValueError):
    """Malformed or incomplete evaluator document. Fail closed."""


def frozen_evaluator_schema() -> dict[str, Any]:
    """Return a JSON-Schema-shaped description of the frozen output."""
    return {
        "title": "AI4 v0.1 frozen evaluator output",
        "type": "object",
        "required": ["schema_version", "text", "shards"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "text": {"type": "string"},
            "shards": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "required": ["shard_id", "applicable", "verdict", "score", "notes"],
                    "additionalProperties": False,
                    "properties": {
                        "shard_id": {"enum": list(FROZEN_SHARD_IDS)},
                        "applicable": {"type": "boolean"},
                        "verdict": {"enum": list(FROZEN_VERDICTS)},
                        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "notes": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        "description": (
            "Applicability is a prompt-level claim (does this shard apply). "
            "Verdict is pass, fail, or not_applicable. v0.1 runtime does not "
            "emit this JSON; it scores all five rubrics with regex and maps "
            "passed/failed onto verdict after the fact."
        ),
    }


def parse_evaluator_document(raw: str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Parse and validate an evaluator document. Fail closed on any error."""
    if isinstance(raw, (str, bytes)):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvaluatorSchemaError(f"Malformed evaluator JSON: {exc}") from exc
    else:
        payload = raw
    errors = validate_evaluator_document(payload)
    if errors:
        raise EvaluatorSchemaError("Invalid evaluator document: " + "; ".join(errors))
    return payload


def validate_evaluator_document(payload: object) -> list[str]:
    """Return schema errors. Empty list means the document is valid."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["evaluator document must be a JSON object"]
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if "text" not in payload or not isinstance(payload.get("text"), str):
        errors.append("text must be a string")
    shards = payload.get("shards")
    if not isinstance(shards, list):
        errors.append("shards must be an array")
        return errors
    if len(shards) != len(FROZEN_SHARD_IDS):
        errors.append(f"shards must contain exactly {len(FROZEN_SHARD_IDS)} entries")
    seen: list[str] = []
    for index, item in enumerate(shards):
        if not isinstance(item, dict):
            errors.append(f"shards[{index}] must be an object")
            continue
        shard_id = item.get("shard_id")
        if shard_id not in FROZEN_SHARD_IDS:
            errors.append(f"shards[{index}].shard_id is unknown: {shard_id!r}")
        elif shard_id in seen:
            errors.append(f"duplicate shard_id {shard_id!r}")
        else:
            seen.append(str(shard_id))
        if not isinstance(item.get("applicable"), bool):
            errors.append(f"shards[{index}].applicable must be a boolean")
        verdict = item.get("verdict")
        if verdict not in FROZEN_VERDICTS:
            errors.append(f"shards[{index}].verdict must be one of {FROZEN_VERDICTS}")
        score = item.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            errors.append(f"shards[{index}].score must be a number")
        elif not 0.0 <= float(score) <= 1.0:
            errors.append(f"shards[{index}].score must be in [0, 1]")
        notes = item.get("notes")
        if not isinstance(notes, list) or any(not isinstance(n, str) for n in notes):
            errors.append(f"shards[{index}].notes must be an array of strings")
        applicable = item.get("applicable")
        if applicable is False and verdict not in {None, "not_applicable"}:
            errors.append(f"shards[{index}] is not applicable but verdict is {verdict!r}")
        if applicable is True and verdict == "not_applicable":
            errors.append(f"shards[{index}] is applicable but verdict is not_applicable")
    missing = [item for item in FROZEN_SHARD_IDS if item not in seen]
    if missing:
        errors.append(f"missing shards: {missing}")
    extra_keys = set(payload) - {"schema_version", "text", "shards"}
    if extra_keys:
        errors.append(f"unexpected keys: {sorted(extra_keys)}")
    return errors


def evaluation_to_frozen_document(
    evaluation: Evaluation,
    specified_shards: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Project a regex Evaluation onto the frozen applicability+verdict schema.

    v0.1 always scores all five rubrics. specified_shards, when provided,
    mark applicability. Unspecified shards are scored but marked
    not_applicable. This is a projection, not a change to D control flow.
    """
    specified = tuple(specified_shards or ())
    apply_filter = bool(specified)
    shards = []
    by_id = evaluation.by_id()
    for shard_id in FROZEN_SHARD_IDS:
        score = by_id.get(shard_id)
        applicable = (not apply_filter) or (shard_id in specified)
        if score is None:
            shards.append(
                {
                    "shard_id": shard_id,
                    "applicable": False,
                    "verdict": "not_applicable",
                    "score": 0.0,
                    "notes": ["shard missing from regex evaluation"],
                }
            )
            continue
        if applicable:
            verdict = "pass" if score.passed else "fail"
        else:
            verdict = "not_applicable"
        shards.append(
            {
                "shard_id": shard_id,
                "applicable": applicable,
                "verdict": verdict,
                "score": float(score.score),
                "notes": list(score.notes),
            }
        )
    document = {
        "schema_version": SCHEMA_VERSION,
        "text": evaluation.text,
        "shards": shards,
    }
    errors = validate_evaluator_document(document)
    if errors:
        raise EvaluatorSchemaError("Projection failed schema checks: " + "; ".join(errors))
    return document


def assert_specified_shards_invoked(
    evaluation: Evaluation,
    specified_shards: Iterable[str],
) -> None:
    """Fail closed if D did not produce a score for a specified shard."""
    present = set(evaluation.by_id())
    missing = [item for item in specified_shards if item not in present]
    if missing:
        raise EvaluatorSchemaError(f"Evaluation missing specified shards: {missing}")
