"""Internal backends and reserved hooks.

The public ``ai4.constrain`` package does not re-export experiment test
doubles or mutable evaluator registries. Session persistence is
constructed here so ``run`` / ``evaluate`` stay the frozen condition-D
product API.
"""

from __future__ import annotations

from typing import Protocol

from src.providers.base import Completion, LLMProvider
from src.providers.mock import HeuristicMockProvider
from src.shards.models import Evaluation
from src.shards.shard_evaluator import ShardEvaluator
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.rubrics import load_packaged_rubrics

FROZEN_EVALUATOR_ID = "v0.1-regex"
FROZEN_RUBRIC_SET = "v0.1"
FROZEN_EVALUATOR_VERSION = "0.1.0"
REQUIRED_SHARD_IDS = REQUIRED_IDS
KNOWN_PROVIDER_IDS = ("mock", "live")
KNOWN_EVALUATOR_IDS = (FROZEN_EVALUATOR_ID,)
PREFLIGHT_PROBE = "[[ai4.constrain.preflight]]"

ProviderBackend = LLMProvider


class EvaluatorBackend(Protocol):
    """Score text. Implementations must fail closed, not skip shards."""

    backend_id: str
    version: str
    rubrics: tuple

    def evaluate(self, text: str) -> Evaluation:
        """Return a complete per-shard evaluation or raise."""


class SessionStore(Protocol):
    """Persist ConstrainedSession snapshots. Implementations fail closed."""

    def load(self, session_id: str) -> object | None:
        """Return a prior SessionState, or None if the id is new."""

    def save(self, session_id: str, state: object) -> None:
        """Persist a SessionState snapshot."""


def assert_complete_evaluation(evaluation: Evaluation | None) -> Evaluation:
    """Fail closed if a required v0.1 shard was not scored."""
    if evaluation is None:
        raise ConstraintExecutionError("Required evaluator returned no evaluation")
    present = set(evaluation.by_id())
    missing = [item for item in REQUIRED_SHARD_IDS if item not in present]
    if missing:
        raise ConstraintExecutionError(
            f"Required constraint evaluator(s) did not execute: {missing}"
        )
    return evaluation


class FrozenV01RegexEvaluator:
    """Thin wrapper around the frozen ``ShardEvaluator``. Not a new backend."""

    backend_id = FROZEN_EVALUATOR_ID
    version = FROZEN_EVALUATOR_VERSION

    def __init__(self, rubrics=None) -> None:
        try:
            loaded = tuple(rubrics) if rubrics is not None else load_packaged_rubrics()
            self._inner = ShardEvaluator(loaded)
        except ConstraintExecutionError:
            raise
        except Exception as exc:
            raise ConstraintExecutionError(
                f"Failed to construct frozen {FROZEN_EVALUATOR_ID} evaluator: {exc}"
            ) from exc
        self.rubrics = self._inner.rubrics
        loaded_ids = {item.id for item in self.rubrics}
        missing = [item for item in REQUIRED_SHARD_IDS if item not in loaded_ids]
        if missing:
            raise ConstraintExecutionError(
                f"Frozen rubric set is incomplete; missing {missing}"
            )

    def evaluate(self, text: str) -> Evaluation:
        try:
            evaluation = self._inner.evaluate(text)
        except ConstraintExecutionError:
            raise
        except Exception as exc:
            raise ConstraintExecutionError(
                f"Required {FROZEN_EVALUATOR_ID} evaluator failed to execute: {exc}"
            ) from exc
        return assert_complete_evaluation(evaluation)


class GuardedEvaluator:
    """Reject incomplete custom evaluations before they reach the D loop."""

    def __init__(self, inner: EvaluatorBackend) -> None:
        self._inner = inner
        self.backend_id = str(getattr(inner, "backend_id", "custom"))
        self.version = str(getattr(inner, "version", ""))
        self.rubrics = getattr(inner, "rubrics", ()) or ()
        self.calls: list[Evaluation] = []

    def evaluate(self, text: str) -> Evaluation:
        try:
            evaluation = self._inner.evaluate(text)
        except ConstraintExecutionError:
            raise
        except Exception as exc:
            raise ConstraintExecutionError(f"Required evaluator failed to execute: {exc}") from exc
        complete = assert_complete_evaluation(evaluation)
        self.calls.append(complete)
        return complete


def preflight_evaluator(backend: EvaluatorBackend) -> None:
    """Fail closed on an incomplete backend before ``ConstrainedAgent.run``."""
    try:
        evaluation = backend.evaluate(PREFLIGHT_PROBE)
    except ConstraintExecutionError:
        raise
    except Exception as exc:
        raise ConstraintExecutionError(
            f"Evaluator preflight failed closed: {exc}"
        ) from exc
    assert_complete_evaluation(evaluation)


def resolve_evaluator(
    evaluator: str | EvaluatorBackend | None = None,
    *,
    rubric_set: str = FROZEN_RUBRIC_SET,
) -> EvaluatorBackend:
    if rubric_set != FROZEN_RUBRIC_SET:
        raise ConstraintExecutionError(
            f"Unknown rubric set {rubric_set!r}. Frozen set is {FROZEN_RUBRIC_SET}."
        )
    if evaluator is None:
        evaluator = FROZEN_EVALUATOR_ID
    if isinstance(evaluator, str):
        if evaluator != FROZEN_EVALUATOR_ID:
            raise ConstraintExecutionError(
                f"Unknown evaluator {evaluator!r}. Registered: {KNOWN_EVALUATOR_IDS}"
            )
        return FrozenV01RegexEvaluator()
    if not hasattr(evaluator, "evaluate"):
        raise ConstraintExecutionError("Evaluator backend must implement evaluate()")
    return evaluator


def resolve_provider(provider: str | ProviderBackend | None = "mock") -> ProviderBackend:
    if provider is None or provider == "mock":
        return HeuristicMockProvider()
    if isinstance(provider, str):
        if provider == "live":
            from src.providers.live import LiveProvider

            return LiveProvider()
        raise ConstraintExecutionError(
            f"Unknown provider {provider!r}. Registered: {KNOWN_PROVIDER_IDS}"
        )
    if not hasattr(provider, "complete") or not hasattr(provider, "revise"):
        raise ConstraintExecutionError("Provider backend must implement complete() and revise()")
    return provider


def session_store(path: str | None = None, *args, **kwargs) -> SessionStore:
    """Memory store by default; directory path selects FileSessionStore."""
    from ai4.constrain.session import FileSessionStore, MemorySessionStore

    if args:
        raise ConstraintExecutionError("session_store() takes an optional path only")
    extra = dict(kwargs)
    if extra:
        raise ConstraintExecutionError(
            f"Unknown session_store() argument(s): {sorted(extra)}"
        )
    if path is None:
        return MemorySessionStore()
    return FileSessionStore(path)


__all__ = [
    "Completion",
    "EvaluatorBackend",
    "FROZEN_EVALUATOR_ID",
    "FROZEN_EVALUATOR_VERSION",
    "FROZEN_RUBRIC_SET",
    "FrozenV01RegexEvaluator",
    "GuardedEvaluator",
    "KNOWN_EVALUATOR_IDS",
    "KNOWN_PROVIDER_IDS",
    "PREFLIGHT_PROBE",
    "ProviderBackend",
    "REQUIRED_SHARD_IDS",
    "SessionStore",
    "assert_complete_evaluation",
    "preflight_evaluator",
    "resolve_evaluator",
    "resolve_provider",
    "session_store",
]
