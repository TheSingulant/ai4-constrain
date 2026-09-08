"""Internal backends and reserved hooks.

The public ``ai4.constrain`` package does not re-export experiment test
doubles or mutable evaluator registries. Session persistence is
constructed here so ``run`` / ``evaluate`` stay the frozen condition-D
product API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.providers.base import Completion, LLMProvider
from src.providers.live import LiveSpendError
from src.providers.mock import HeuristicMockProvider
from src.shards.models import Evaluation
from src.shards.shard_evaluator import ShardEvaluator
from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.evaluator_wall import (
    assert_evaluator_rubrics,
    assert_rubrics_match_packaged,
    overlay_packaged_policy,
    packaged_policy_rubrics,
)
from ai4.constrain.rubrics import load_packaged_rubrics

FROZEN_EVALUATOR_ID = "v0.1-regex"
FROZEN_RUBRIC_SET = "v0.1"
FROZEN_EVALUATOR_VERSION = "0.1.0"
REQUIRED_SHARD_IDS = REQUIRED_IDS
KNOWN_PROVIDER_IDS = ("mock", "live")
KNOWN_EVALUATOR_IDS = (FROZEN_EVALUATOR_ID,)
PREFLIGHT_PROBE = "[[ai4.constrain.preflight]]"
EVALUATE_ONLY_PROVIDER_ID = "none"
PROPOSAL_RESOLVED_AS_CONFIG = "config"
PROPOSAL_RESOLVED_AS_ARGUMENT = "explicit_argument"
PROPOSAL_RESOLVED_AS_CUSTOM = "custom_object"
PROPOSAL_RESOLVED_AS_EVALUATE = "evaluate_only"
EVALUATOR_RESOLVED_AS_CONFIG = "config"
EVALUATOR_RESOLVED_AS_ARGUMENT = "explicit_argument"
EVALUATOR_RESOLVED_AS_CUSTOM = "custom_object"
EVALUATOR_RESOLVED_AS_LEGACY = "legacy_versions"

SECRET_METADATA_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "token",
        "password",
        "secret",
        "bearer",
    }
)
# Frozen mock/live completions do not require provider metadata. Anything
# present is untrusted telemetry and fails closed unless explicitly listed.
ALLOWED_COMPLETION_METADATA_KEYS = frozenset()
POLICY_METADATA_KEYS = frozenset(
    {
        "arbitration",
        "condition",
        "config",
        "enforced_shards",
        "evaluator",
        "evaluator_id",
        "evaluator_version",
        "evidence_class",
        "include_history",
        "max_completions",
        "max_history_turns",
        "max_revision_rounds",
        "pass_threshold",
        "policy",
        "policy_identity",
        "prompt_specified_shards",
        "protocol",
        "redact",
        "refusal",
        "refusal_text",
        "report_schema_version",
        "rubric",
        "rubric_set",
        "rubric_versions",
        "runtime_config",
        "runtime_version",
        "safe_refusal",
        "session_policy",
        "session_policy_identity",
        "shard_control",
        "shard_control_scope",
        "specified_shards",
        "threshold",
        "thresholds",
        "timeout_s",
        "versions",
    }
)
RESERVED_PROVIDER_IDENTITIES = frozenset(
    {
        FROZEN_EVALUATOR_ID,
        *KNOWN_EVALUATOR_IDS,
        EVALUATE_ONLY_PROVIDER_ID,
        *POLICY_METADATA_KEYS,
        "backend_id",
        "constraint",
        "decision",
        "decision_report",
        "frozen",
        "governing",
        "middleware",
        "provider",
        "provider_id",
        "sessionpolicyidentity",
        "shard_evaluator",
        "v0.1",
    }
)
# Custom evaluator backend_id values that collide with policy/control
# vocabulary. The packaged frozen impl may still use FROZEN_EVALUATOR_ID.
RESERVED_EVALUATOR_IDENTITIES = frozenset(
    {
        *RESERVED_PROVIDER_IDENTITIES,
        *KNOWN_PROVIDER_IDS,
        "evaluator_impl",
        "implementation",
        "proposal",
    }
)
FROZEN_EVALUATOR_IMPL = f"frozen:{FROZEN_EVALUATOR_ID}"

ProviderBackend = LLMProvider


class EvaluatorBackend(Protocol):
    """Score text against the frozen v0.1 contract.

    Implementations must fail closed, not skip shards. They do not own
    rubrics, thresholds, kinds, priorities, conflicts, or pass/fail.
    ``rubrics`` is optional; if present it must match packaged policy.
    """

    backend_id: str
    version: str

    def evaluate(self, text: str) -> Evaluation:
        """Return a complete per-shard evaluation or raise."""


class SessionStore(Protocol):
    """Persist ConstrainedSession snapshots. Implementations fail closed."""

    def load(self, session_id: str) -> object | None:
        """Return a prior SessionState, or None if the id is new."""

    def save(self, session_id: str, state: object) -> None:
        """Persist a SessionState snapshot."""


def assert_complete_evaluation(evaluation: Evaluation | None) -> Evaluation:
    """Fail closed unless exactly the required v0.1 shards were scored."""
    if evaluation is None:
        raise ConstraintExecutionError("Required evaluator returned no evaluation")
    present = [item.shard_id for item in evaluation.shard_scores]
    unique = set(present)
    extra = sorted(unique - set(REQUIRED_SHARD_IDS))
    missing = [item for item in REQUIRED_SHARD_IDS if item not in unique]
    if missing or extra or len(present) != len(REQUIRED_SHARD_IDS) or len(unique) != len(REQUIRED_SHARD_IDS):
        raise ConstraintExecutionError(
            f"Required constraint evaluator(s) did not execute: missing={missing}, extra={extra}"
        )
    return evaluation


class FrozenV01RegexEvaluator:
    """Thin wrapper around the frozen ``ShardEvaluator``. Not a new backend."""

    backend_id = FROZEN_EVALUATOR_ID
    version = FROZEN_EVALUATOR_VERSION

    def __init__(self, rubrics=None) -> None:
        try:
            packaged = load_packaged_rubrics()
            if rubrics is not None:
                assert_rubrics_match_packaged(tuple(rubrics), packaged)
            self._inner = ShardEvaluator(packaged)
        except ConstraintExecutionError:
            raise
        except Exception as exc:
            raise ConstraintExecutionError(
                f"Failed to construct frozen {FROZEN_EVALUATOR_ID} evaluator: {exc}"
            ) from exc
        self.rubrics = packaged
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
    """Reject incomplete or policy-mutating evaluations before the D loop.

    Middleware always sees packaged v0.1 rubrics. Evaluator-supplied
    version/kind/priority/threshold/passed are overwritten. ``.rubrics`` on
    this wrapper is the packaged set, never the inner backend's.
    """

    def __init__(
        self,
        inner: EvaluatorBackend,
        *,
        resolved_as: str = EVALUATOR_RESOLVED_AS_CUSTOM,
    ) -> None:
        self._inner = inner
        self.backend_id = evaluator_identity(inner)
        self.version = str(getattr(inner, "version", "") or "")
        self.resolved_as = resolved_as
        self.rubrics = packaged_policy_rubrics()
        assert_reserved_evaluator_identity(inner)
        assert_evaluator_rubrics(inner, self.rubrics)
        self.calls: list[Evaluation] = []

    def evaluate(self, text: str) -> Evaluation:
        try:
            evaluation = self._inner.evaluate(text)
        except ConstraintExecutionError:
            raise
        except Exception as exc:
            raise ConstraintExecutionError(f"Required evaluator failed to execute: {exc}") from exc
        assert_evaluator_rubrics(self._inner, self.rubrics)
        complete = assert_complete_evaluation(evaluation)
        overlaid = overlay_packaged_policy(complete, self.rubrics)
        self.calls.append(overlaid)
        return overlaid


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


def evaluator_identity(evaluator: str | EvaluatorBackend | None) -> str:
    """Governing evaluator identity. Never inferred from a proposal provider."""
    if evaluator is None:
        return FROZEN_EVALUATOR_ID
    if isinstance(evaluator, str):
        ident = evaluator.strip()
        if not ident:
            raise ConstraintExecutionError("Evaluator identity must be non-empty")
        return ident
    ident = str(getattr(evaluator, "backend_id", "") or "").strip()
    if not ident:
        raise ConstraintExecutionError("Evaluator backend must expose a non-empty backend_id")
    return ident


def unwrap_evaluator(evaluator: object) -> object:
    """Return the innermost evaluator backend, skipping GuardedEvaluator wraps."""
    current = evaluator
    seen: set[int] = set()
    while isinstance(current, GuardedEvaluator):
        ident = id(current)
        if ident in seen:
            raise ConstraintExecutionError("Cyclic evaluator wrapper; refusing")
        seen.add(ident)
        current = current._inner
    return current


def assert_reserved_evaluator_identity(evaluator: object) -> None:
    """Reject spoofed frozen ids and policy/control vocabulary as custom ids."""
    ident = evaluator_identity(evaluator)
    inner = unwrap_evaluator(evaluator)
    if ident == FROZEN_EVALUATOR_ID:
        if type(inner) is not FrozenV01RegexEvaluator:
            raise ConstraintExecutionError(
                f"Reserved evaluator identity {FROZEN_EVALUATOR_ID!r} is only valid "
                "for the packaged frozen implementation; refusing spoofed backend_id"
            )
        return
    folded = ident.strip().lower()
    reserved = {item.lower() for item in RESERVED_EVALUATOR_IDENTITIES}
    if folded in reserved:
        raise ConstraintExecutionError(
            f"Evaluator identity {ident!r} collides with evaluator or "
            "policy/control identity; refusing custom backend_id that is not "
            "an implementation name"
        )


def evaluator_impl_fingerprint(evaluator: str | EvaluatorBackend | None) -> str:
    """Stable implementation fingerprint. Not a cryptographic attestation.

    The packaged frozen evaluator is always ``frozen:v0.1-regex``. Custom
    objects are ``custom:<module>.<qualname>`` of the unwrapped class so
    same-id / different-class swaps fail closed. This is not a public
    registry.
    """
    if evaluator is None or isinstance(evaluator, str):
        ident = evaluator_identity(evaluator)
        if ident != FROZEN_EVALUATOR_ID:
            raise ConstraintExecutionError(
                f"Unknown evaluator {ident!r}. Registered: {KNOWN_EVALUATOR_IDS}"
            )
        return FROZEN_EVALUATOR_IMPL
    inner = unwrap_evaluator(evaluator)
    if type(inner) is FrozenV01RegexEvaluator:
        return FROZEN_EVALUATOR_IMPL
    cls = type(inner)
    module = str(getattr(cls, "__module__", "") or "").strip()
    qual = str(getattr(cls, "__qualname__", "") or getattr(cls, "__name__", "") or "").strip()
    if not module or not qual:
        raise ConstraintExecutionError(
            "Custom evaluator must expose a class module and qualname for "
            "session implementation binding"
        )
    return f"custom:{module}.{qual}"


def evaluator_resolved_as(evaluator: str | EvaluatorBackend | None) -> str:
    if evaluator is None:
        return EVALUATOR_RESOLVED_AS_CONFIG
    if isinstance(evaluator, str):
        return EVALUATOR_RESOLVED_AS_ARGUMENT
    return EVALUATOR_RESOLVED_AS_CUSTOM


def bind_evaluator(
    evaluator: str | EvaluatorBackend | None = None,
    *,
    rubric_set: str = FROZEN_RUBRIC_SET,
    resolved_as: str | None = None,
) -> GuardedEvaluator:
    """Resolve, identity-check, reserved-id-check, and preflight before proposals."""
    ident = evaluator_identity(evaluator)
    source = resolved_as if resolved_as is not None else evaluator_resolved_as(evaluator)
    if isinstance(evaluator, str) or evaluator is None:
        if ident not in KNOWN_EVALUATOR_IDS:
            raise ConstraintExecutionError(
                f"Unknown evaluator {ident!r}. Registered: {KNOWN_EVALUATOR_IDS}"
            )
    resolved = resolve_evaluator(evaluator, rubric_set=rubric_set)
    assert_reserved_evaluator_identity(resolved)
    backend = GuardedEvaluator(resolved, resolved_as=source)
    bound = evaluator_identity(backend)
    if bound != ident:
        raise ConstraintExecutionError(
            f"Evaluator identity {bound!r} does not match resolved identity {ident!r}"
        )
    if ident == FROZEN_EVALUATOR_ID:
        assert_reserved_evaluator_identity(backend)
    preflight_evaluator(backend)
    return backend


def reject_completion_metadata(metadata: object) -> None:
    """Fail closed unless metadata is empty or uses only the explicit allowlist.

    Nested objects/arrays are never permitted. Provider-controlled keys such as
    ``kind`` are not authority for call classification.
    """
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise ConstraintExecutionError(
            "Provider metadata must be an object; refusing non-object metadata"
        )
    if not metadata:
        return
    extra = sorted({str(key) for key in metadata} - set(ALLOWED_COMPLETION_METADATA_KEYS))
    if extra:
        raise ConstraintExecutionError(
            f"Provider metadata included unpermitted key(s) {extra}; "
            "proposal metadata is untrusted telemetry and only explicitly "
            "permitted fields are accepted"
        )
    for key, value in metadata.items():
        if isinstance(value, (dict, list, tuple)):
            raise ConstraintExecutionError(
                f"Provider metadata field {key!r} must be a scalar; "
                "nested metadata is not permitted"
            )


def is_live_provider(provider: object) -> bool:
    """True for the gated live HTTP backend. Names like 'openai' are not live."""
    if provider is None:
        return False
    if provider == "live":
        return True
    if isinstance(provider, str):
        return False
    try:
        from src.providers.live import LiveProvider
    except Exception:
        LiveProvider = None  # type: ignore[misc, assignment]
    if LiveProvider is not None and isinstance(provider, LiveProvider):
        return True
    name = str(getattr(provider, "name", "") or getattr(provider, "provider_id", "") or "")
    return name.strip().lower() == "live"


def _normalize_provider_identity(raw: str) -> str:
    ident = raw.strip()
    if not ident:
        raise ConstraintExecutionError(
            "Custom proposal provider must expose a non-empty name or provider_id"
        )
    return ident


def _assert_provider_identity_allowed(ident: str) -> str:
    folded = ident.strip().lower()
    if not folded:
        raise ConstraintExecutionError(
            "Custom proposal provider must expose a non-empty name or provider_id"
        )
    reserved = {item.lower() for item in RESERVED_PROVIDER_IDENTITIES}
    if folded in reserved:
        raise ConstraintExecutionError(
            f"Proposal provider identity {ident!r} collides with evaluator or "
            "policy/control identity; refusing to infer governing policy from "
            "a provider-controlled string"
        )
    return ident.strip()


def _custom_provider_identity(provider: ProviderBackend) -> str:
    for attr in ("provider_id", "name"):
        value = getattr(provider, attr, None)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return _assert_provider_identity_allowed(text)
    raise ConstraintExecutionError(
        "Custom proposal provider must expose a non-empty name or provider_id"
    )


def checked_completion(completion: object) -> Completion:
    """Accept a Completion after allowlisting metadata. Never keep provider metadata."""
    if not isinstance(completion, Completion):
        raise ConstraintExecutionError("Proposal provider must return a Completion")
    reject_completion_metadata(completion.metadata)
    if not completion.metadata:
        return completion
    return Completion(
        text=completion.text,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        estimated_usd=completion.estimated_usd,
        model=completion.model,
        metadata={},
    )


@dataclass(frozen=True)
class ProposalResolution:
    """Resolved proposal backend plus auditable identity. Not policy."""

    backend: ProviderBackend
    provider_id: str
    model: str
    resolved_as: str

    def identity_payload(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "resolved_as": self.resolved_as,
        }


class GuardedProposalProvider:
    """Proposal backends emit candidate text. They do not govern.

    ``evaluate``, rubrics, thresholds, and policy attributes on a dual-role
    object are not exposed at this call site.
    """

    def __init__(
        self,
        inner: ProviderBackend,
        *,
        provider_id: str,
        model: str,
        resolved_as: str,
    ) -> None:
        self._inner = inner
        self.name = provider_id
        self.model = model
        self.provider_id = provider_id
        self.resolved_as = resolved_as

    @property
    def resolution(self) -> ProposalResolution:
        return ProposalResolution(
            backend=self,
            provider_id=self.provider_id,
            model=self.model,
            resolved_as=self.resolved_as,
        )

    def complete(self, *, system: str, user: str) -> Completion:
        try:
            completion = self._inner.complete(system=system, user=user)
        except (ConstraintExecutionError, LiveSpendError):
            raise
        except Exception as exc:
            raise ConstraintExecutionError(f"Proposal provider failed closed: {exc}") from exc
        return checked_completion(completion)

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        try:
            completion = self._inner.revise(
                system=system, user=user, draft=draft, feedback=feedback
            )
        except (ConstraintExecutionError, LiveSpendError):
            raise
        except Exception as exc:
            raise ConstraintExecutionError(f"Proposal provider failed closed: {exc}") from exc
        return checked_completion(completion)


def _instantiate_known_provider(provider_id: str) -> ProviderBackend:
    if provider_id == "mock":
        return HeuristicMockProvider()
    if provider_id == "live":
        from src.providers.live import LiveProvider

        return LiveProvider()
    raise ConstraintExecutionError(
        f"Unknown provider {provider_id!r}. Registered: {KNOWN_PROVIDER_IDS}"
    )


def _guard(
    inner: ProviderBackend, *, provider_id: str, model: str, resolved_as: str
) -> ProposalResolution:
    guarded = GuardedProposalProvider(
        inner, provider_id=provider_id, model=model, resolved_as=resolved_as
    )
    return guarded.resolution


def resolve_proposal(
    provider: str | ProviderBackend | None = "mock",
    *,
    resolved_as: str = PROPOSAL_RESOLVED_AS_CONFIG,
) -> ProposalResolution:
    """Resolve a proposal backend. Provider output cannot set governing policy."""
    if provider is None:
        provider = "mock"
        resolved_as = PROPOSAL_RESOLVED_AS_CONFIG
    if isinstance(provider, str):
        ident = _normalize_provider_identity(provider)
        if ident not in KNOWN_PROVIDER_IDS:
            raise ConstraintExecutionError(
                f"Unknown provider {ident!r}. Registered: {KNOWN_PROVIDER_IDS}"
            )
        backend = _instantiate_known_provider(ident)
        model = str(getattr(backend, "model", "") or "")
        return _guard(backend, provider_id=ident, model=model, resolved_as=resolved_as)
    if not hasattr(provider, "complete") or not hasattr(provider, "revise"):
        raise ConstraintExecutionError("Provider backend must implement complete() and revise()")
    if isinstance(provider, GuardedProposalProvider):
        return provider.resolution
    ident = _custom_provider_identity(provider)
    model = str(getattr(provider, "model", "") or "")
    source = (
        PROPOSAL_RESOLVED_AS_CUSTOM
        if resolved_as == PROPOSAL_RESOLVED_AS_CONFIG
        else resolved_as
    )
    return _guard(provider, provider_id=ident, model=model, resolved_as=source)


def resolve_provider(provider: str | ProviderBackend | None = "mock") -> ProviderBackend:
    return resolve_proposal(provider).backend


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
    "ALLOWED_COMPLETION_METADATA_KEYS",
    "Completion",
    "EVALUATE_ONLY_PROVIDER_ID",
    "EVALUATOR_RESOLVED_AS_ARGUMENT",
    "EVALUATOR_RESOLVED_AS_CONFIG",
    "EVALUATOR_RESOLVED_AS_CUSTOM",
    "EVALUATOR_RESOLVED_AS_LEGACY",
    "EvaluatorBackend",
    "FROZEN_EVALUATOR_ID",
    "FROZEN_EVALUATOR_IMPL",
    "FROZEN_EVALUATOR_VERSION",
    "FROZEN_RUBRIC_SET",
    "FrozenV01RegexEvaluator",
    "GuardedEvaluator",
    "GuardedProposalProvider",
    "KNOWN_EVALUATOR_IDS",
    "KNOWN_PROVIDER_IDS",
    "POLICY_METADATA_KEYS",
    "PREFLIGHT_PROBE",
    "PROPOSAL_RESOLVED_AS_ARGUMENT",
    "PROPOSAL_RESOLVED_AS_CONFIG",
    "PROPOSAL_RESOLVED_AS_CUSTOM",
    "PROPOSAL_RESOLVED_AS_EVALUATE",
    "ProposalResolution",
    "ProviderBackend",
    "REQUIRED_SHARD_IDS",
    "RESERVED_EVALUATOR_IDENTITIES",
    "RESERVED_PROVIDER_IDENTITIES",
    "SECRET_METADATA_KEYS",
    "SessionStore",
    "assert_complete_evaluation",
    "assert_reserved_evaluator_identity",
    "bind_evaluator",
    "checked_completion",
    "evaluator_identity",
    "evaluator_impl_fingerprint",
    "evaluator_resolved_as",
    "is_live_provider",
    "preflight_evaluator",
    "reject_completion_metadata",
    "resolve_evaluator",
    "resolve_proposal",
    "resolve_provider",
    "session_store",
    "unwrap_evaluator",
]
