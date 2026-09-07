"""Shared shard data types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Criterion:
    id: str
    weight: float
    description: str
    fail_if_regex: tuple[str, ...] = ()
    pass_if_regex: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rubric:
    id: str
    version: str
    title: str
    kind: str
    priority: int
    pass_threshold: float
    description: str
    criteria: tuple[Criterion, ...]


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    passed: bool
    score: float
    evidence: str


@dataclass(frozen=True)
class ShardScore:
    shard_id: str
    version: str
    kind: str
    priority: int
    score: float
    passed: bool
    threshold: float
    results: tuple[CriterionResult, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evaluation:
    text: str
    shard_scores: tuple[ShardScore, ...]
    rubric_set_version: str = "0.1.0"

    def by_id(self) -> dict[str, ShardScore]:
        return {item.shard_id: item for item in self.shard_scores}

    def failing(self) -> list[ShardScore]:
        return [item for item in self.shard_scores if not item.passed]


@dataclass(frozen=True)
class ArbitrationResult:
    verdict: str
    veto: bool
    irreconcilable: bool
    revision_targets: tuple[str, ...]
    notes: tuple[str, ...] = ()
    scores: tuple[ShardScore, ...] = field(default_factory=tuple)
