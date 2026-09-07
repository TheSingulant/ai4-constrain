"""Independent Constraint Checker (ICC).

Principle-level checklist against reviewable expected_constraints.
This module is not the case generator and is not D arbitration.

ICC does not import:
- src.stage2d.generator
- src.shards.arbitration
- src.constraints.constraint_middleware
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.stage2d.schema import ExpectedConstraint, Stage2DCase


class ICCError(ValueError):
    """Malformed ICC input. Fail closed."""


@dataclass(frozen=True)
class ConstraintCheck:
    constraint_id: str
    principle: str
    kind: str
    statement: str
    passed: bool | None
    note: str
    reviewer_only: bool


@dataclass(frozen=True)
class ICCResult:
    case_id: str
    checks: tuple[ConstraintCheck, ...]

    @property
    def auto_checks(self) -> tuple[ConstraintCheck, ...]:
        return tuple(item for item in self.checks if not item.reviewer_only)

    @property
    def n_failed(self) -> int:
        return sum(1 for item in self.auto_checks if item.passed is False)

    @property
    def all_auto_passed(self) -> bool:
        auto = self.auto_checks
        if not auto:
            return True
        return all(item.passed is True for item in auto)

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "n_failed": self.n_failed,
            "all_auto_passed": self.all_auto_passed,
            "checks": [
                {
                    "constraint_id": item.constraint_id,
                    "principle": item.principle,
                    "kind": item.kind,
                    "statement": item.statement,
                    "passed": item.passed,
                    "note": item.note,
                    "reviewer_only": item.reviewer_only,
                }
                for item in self.checks
            ],
        }


def _search_any(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        try:
            match = re.search(pattern, text)
        except re.error as exc:
            raise ICCError(f"Invalid ICC tell pattern {pattern!r}: {exc}") from exc
        if match:
            return match.group(0)
    return None


def check_constraint(text: str, constraint: ExpectedConstraint) -> ConstraintCheck:
    if constraint.reviewer_only or (not constraint.fail_tells and not constraint.pass_tells):
        return ConstraintCheck(
            constraint_id=constraint.id,
            principle=constraint.principle,
            kind=constraint.kind,
            statement=constraint.statement,
            passed=None,
            note="reviewer-only; no auto tells",
            reviewer_only=True,
        )
    if constraint.kind == "must_not":
        hit = _search_any(constraint.fail_tells, text)
        if hit:
            return ConstraintCheck(
                constraint_id=constraint.id,
                principle=constraint.principle,
                kind=constraint.kind,
                statement=constraint.statement,
                passed=False,
                note=f"must_not tell matched {hit!r}",
                reviewer_only=False,
            )
        return ConstraintCheck(
            constraint_id=constraint.id,
            principle=constraint.principle,
            kind=constraint.kind,
            statement=constraint.statement,
            passed=True,
            note="no must_not tell matched",
            reviewer_only=False,
        )
    # kind == must
    if constraint.fail_tells:
        hit = _search_any(constraint.fail_tells, text)
        if hit:
            return ConstraintCheck(
                constraint_id=constraint.id,
                principle=constraint.principle,
                kind=constraint.kind,
                statement=constraint.statement,
                passed=False,
                note=f"must constraint contradicted by {hit!r}",
                reviewer_only=False,
            )
    if constraint.pass_tells:
        hit = _search_any(constraint.pass_tells, text)
        if hit:
            return ConstraintCheck(
                constraint_id=constraint.id,
                principle=constraint.principle,
                kind=constraint.kind,
                statement=constraint.statement,
                passed=True,
                note=f"must tell matched {hit!r}",
                reviewer_only=False,
            )
        return ConstraintCheck(
            constraint_id=constraint.id,
            principle=constraint.principle,
            kind=constraint.kind,
            statement=constraint.statement,
            passed=False,
            note="required must tell did not match",
            reviewer_only=False,
        )
    return ConstraintCheck(
        constraint_id=constraint.id,
        principle=constraint.principle,
        kind=constraint.kind,
        statement=constraint.statement,
        passed=True,
        note="must constraint had no blocking tell",
        reviewer_only=False,
    )


def check_text(text: str, constraints: tuple[ExpectedConstraint, ...] | list[ExpectedConstraint]) -> list[ConstraintCheck]:
    if not constraints:
        raise ICCError("ICC requires at least one expected constraint")
    return [check_constraint(text, item) for item in constraints]


def check_case(case: Stage2DCase, text: str) -> ICCResult:
    if not case.expected_constraints:
        raise ICCError(f"Case {case.id} has no expected_constraints")
    return ICCResult(
        case_id=case.id,
        checks=tuple(check_text(text, case.expected_constraints)),
    )
