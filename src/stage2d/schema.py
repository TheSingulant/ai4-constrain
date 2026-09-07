"""Stage 2D case schema and fail-closed loaders.

Gold notes for reviewers live in a sealed side file. The runner must not
load that file onto the model path.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.stage2d.constants import (
    FROZEN_TERMINALS,
    STAGE2D_CATEGORIES,
    STAGE2D_PRINCIPLES,
    principles_to_shards,
)

REQUIRED_CASE_FIELDS = (
    "id",
    "category",
    "prompt",
    "specified_principles",
    "conflict_brief",
    "expected_constraints",
    "plausible_first_draft_failure_modes",
    "acceptable_terminals",
    "favors",
)

REQUIRED_CONSTRAINT_FIELDS = ("id", "principle", "kind", "statement")


class Stage2DCaseError(ValueError):
    """Invalid Stage 2D fixture. Fail closed."""


@dataclass(frozen=True)
class ExpectedConstraint:
    id: str
    principle: str
    kind: str
    statement: str
    fail_tells: tuple[str, ...] = ()
    pass_tells: tuple[str, ...] = ()
    reviewer_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "principle": self.principle,
            "kind": self.kind,
            "statement": self.statement,
            "fail_tells": list(self.fail_tells),
            "pass_tells": list(self.pass_tells),
            "reviewer_only": self.reviewer_only,
        }


@dataclass(frozen=True)
class Stage2DCase:
    id: str
    category: str
    prompt: str
    specified_principles: tuple[str, ...]
    conflict_brief: str
    expected_constraints: tuple[ExpectedConstraint, ...]
    plausible_first_draft_failure_modes: tuple[str, ...]
    acceptable_terminals: tuple[str, ...]
    favors: dict[str, Any]
    synthetic: bool = True
    split: str = ""
    seed: int = 0
    variant: int = 0

    @property
    def specified_shards(self) -> tuple[str, ...]:
        return principles_to_shards(self.specified_principles)

    def as_public_dict(self) -> dict[str, Any]:
        """Model-facing / committed case row. No gold notes."""
        return {
            "id": self.id,
            "category": self.category,
            "prompt": self.prompt,
            "specified_principles": list(self.specified_principles),
            "conflict_brief": self.conflict_brief,
            "expected_constraints": [item.as_dict() for item in self.expected_constraints],
            "plausible_first_draft_failure_modes": list(self.plausible_first_draft_failure_modes),
            "acceptable_terminals": list(self.acceptable_terminals),
            "favors": dict(self.favors),
            "synthetic": self.synthetic,
            "split": self.split,
            "seed": self.seed,
            "variant": self.variant,
        }


def _require_mapping(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise Stage2DCaseError(f"{where} must be a JSON object")
    return raw


def _as_str_tuple(raw: Any, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise Stage2DCaseError(f"{where} must be a non-empty list of strings")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise Stage2DCaseError(f"{where} must contain non-empty strings")
        out.append(item)
    return tuple(out)


def parse_expected_constraint(raw: Any, *, case_id: str) -> ExpectedConstraint:
    payload = _require_mapping(raw, f"expected_constraints item in {case_id}")
    missing = [key for key in REQUIRED_CONSTRAINT_FIELDS if key not in payload]
    if missing:
        raise Stage2DCaseError(f"Constraint in {case_id} missing {missing}")
    principle = str(payload["principle"]).strip().lower()
    if principle not in STAGE2D_PRINCIPLES and principle != "harm_aversion":
        raise Stage2DCaseError(f"Unknown constraint principle {principle!r} in {case_id}")
    if principle == "harm_aversion":
        principle = "harm aversion"
    kind = str(payload["kind"]).strip().lower()
    if kind not in {"must", "must_not"}:
        raise Stage2DCaseError(f"Constraint kind must be must or must_not in {case_id}")
    fail_tells = tuple(str(item) for item in (payload.get("fail_tells") or []))
    pass_tells = tuple(str(item) for item in (payload.get("pass_tells") or []))
    reviewer_only = bool(payload.get("reviewer_only", False))
    return ExpectedConstraint(
        id=str(payload["id"]),
        principle=principle,
        kind=kind,
        statement=str(payload["statement"]),
        fail_tells=fail_tells,
        pass_tells=pass_tells,
        reviewer_only=reviewer_only,
    )


def parse_case(raw: Any, *, line_no: int | None = None) -> Stage2DCase:
    where = f"line {line_no}" if line_no is not None else "case"
    payload = _require_mapping(raw, where)
    missing = [key for key in REQUIRED_CASE_FIELDS if key not in payload]
    if missing:
        raise Stage2DCaseError(f"{where} missing fields {missing}")
    if "gold_notes_for_reviewers" in payload:
        raise Stage2DCaseError(
            f"{where} must not embed gold_notes_for_reviewers; use the sealed side file"
        )
    category = str(payload["category"])
    if category not in STAGE2D_CATEGORIES:
        raise Stage2DCaseError(f"Unknown category {category!r} in {payload.get('id')}")
    principles = _as_str_tuple(payload["specified_principles"], "specified_principles")
    unknown = [item for item in principles if item.lower() not in STAGE2D_PRINCIPLES]
    if unknown:
        raise Stage2DCaseError(f"Unknown specified_principles {unknown} in {payload.get('id')}")
    terminals = _as_str_tuple(payload["acceptable_terminals"], "acceptable_terminals")
    bad_term = [item for item in terminals if item not in FROZEN_TERMINALS]
    if bad_term:
        raise Stage2DCaseError(f"Unknown acceptable_terminals {bad_term} in {payload.get('id')}")
    constraints_raw = payload["expected_constraints"]
    if not isinstance(constraints_raw, list) or not constraints_raw:
        raise Stage2DCaseError(f"expected_constraints must be a non-empty list in {payload.get('id')}")
    constraints = tuple(
        parse_expected_constraint(item, case_id=str(payload["id"])) for item in constraints_raw
    )
    favors = payload["favors"]
    if not isinstance(favors, dict) or not favors:
        raise Stage2DCaseError(f"favors must be a non-empty object in {payload.get('id')}")
    modes = _as_str_tuple(
        payload["plausible_first_draft_failure_modes"],
        "plausible_first_draft_failure_modes",
    )
    # Mapping check: fail closed if a principle cannot become a shard id.
    principles_to_shards(principles)
    return Stage2DCase(
        id=str(payload["id"]),
        category=category,
        prompt=str(payload["prompt"]),
        specified_principles=tuple(item.lower() for item in principles),
        conflict_brief=str(payload["conflict_brief"]),
        expected_constraints=constraints,
        plausible_first_draft_failure_modes=modes,
        acceptable_terminals=terminals,
        favors=dict(favors),
        synthetic=bool(payload.get("synthetic", True)),
        split=str(payload.get("split") or ""),
        seed=int(payload.get("seed") or 0),
        variant=int(payload.get("variant") or 0),
    )


def load_cases(path: Path) -> list[Stage2DCase]:
    if not path.is_file():
        raise Stage2DCaseError(f"Fixture not found: {path}")
    cases: list[Stage2DCase] = []
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Stage2DCaseError(f"Malformed fixture JSON at line {line_no}: {exc}") from exc
        case = parse_case(raw, line_no=line_no)
        if case.id in seen:
            raise Stage2DCaseError(f"Duplicate case id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
    if not cases:
        raise Stage2DCaseError(f"Fixture is empty: {path}")
    return cases


def load_gold_notes(path: Path) -> dict[str, str]:
    """Load sealed reviewer notes. Not used by the model runner."""
    if not path.is_file():
        raise Stage2DCaseError(f"Gold notes not found: {path}")
    notes: dict[str, str] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Stage2DCaseError(f"Malformed gold notes JSON at line {line_no}: {exc}") from exc
        if not isinstance(raw, dict) or "id" not in raw or "gold_notes_for_reviewers" not in raw:
            raise Stage2DCaseError(f"Gold notes line {line_no} needs id and gold_notes_for_reviewers")
        notes[str(raw["id"])] = str(raw["gold_notes_for_reviewers"])
    return notes


def render_jsonl(rows: Sequence[dict[str, Any]]) -> str:
    lines = [
        json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True) for row in rows
    ]
    return "\n".join(lines) + "\n"
