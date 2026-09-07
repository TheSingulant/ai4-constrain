"""Runtime version stamps and operative configuration."""

from __future__ import annotations

from dataclasses import dataclass

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.ext import (
    FROZEN_EVALUATOR_ID,
    FROZEN_EVALUATOR_VERSION,
    FROZEN_RUBRIC_SET,
    KNOWN_EVALUATOR_IDS,
    KNOWN_PROVIDER_IDS,
)

RUNTIME_VERSION = "0.1.0"
REPORT_SCHEMA_VERSION = "0.1.0"
PROTOCOL_VERSION = "v0.1"
ARBITRATION_VERSION = "v0.1"
CONDITION = "D"
EVIDENCE_CLASS = "null_retained_D_adds_cost"


@dataclass(frozen=True)
class RuntimeConfig:
    """Caller-visible knobs. Every id field is resolved and unknown ids fail closed."""

    rubric_set: str = FROZEN_RUBRIC_SET
    evaluator_id: str = FROZEN_EVALUATOR_ID
    provider_id: str = "mock"
    max_revision_rounds: int = 2
    timeout_s: float = 30.0
    max_completions: int = 3
    redact: bool = True

    def validate(self) -> RuntimeConfig:
        if self.rubric_set != FROZEN_RUBRIC_SET:
            raise ConstraintExecutionError(
                f"Unknown rubric set {self.rubric_set!r}. Frozen set is {FROZEN_RUBRIC_SET}."
            )
        if self.evaluator_id not in KNOWN_EVALUATOR_IDS:
            raise ConstraintExecutionError(
                f"Unknown evaluator {self.evaluator_id!r}. Registered: {KNOWN_EVALUATOR_IDS}"
            )
        if self.provider_id not in KNOWN_PROVIDER_IDS:
            raise ConstraintExecutionError(
                f"Unknown provider {self.provider_id!r}. Registered: {KNOWN_PROVIDER_IDS}"
            )
        if self.max_revision_rounds < 0 or self.max_completions < 0 or self.timeout_s < 0:
            raise ConstraintExecutionError("Runtime bounds must be >= 0")
        return self


def default_config() -> RuntimeConfig:
    return RuntimeConfig().validate()


def version_payload(*, evaluator_id: str, evaluator_version: str, rubric_versions: dict[str, str]) -> dict[str, object]:
    return {
        "runtime_version": RUNTIME_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "protocol": PROTOCOL_VERSION,
        "condition": CONDITION,
        "evidence_class": EVIDENCE_CLASS,
        "rubric_set": FROZEN_RUBRIC_SET,
        "evaluator_id": evaluator_id,
        "evaluator_version": evaluator_version or FROZEN_EVALUATOR_VERSION,
        "arbitration": ARBITRATION_VERSION,
        "rubric_versions": dict(rubric_versions),
    }
