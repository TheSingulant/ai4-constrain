"""Inert hybrid context types (V07-3A §4).

Trusted product configuration, runtime-observed provenance evidence, and
derived readiness input are distinct types. Caller-supplied labels do
not become observed or authenticated evidence merely by populating a
dataclass. ``hybrid_ready`` always returns ``NotReady("slice_incomplete")``
in this slice. There is no ``Ready`` object and no install method that
can enable governing hybrid evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain.semantic_examiner import EXAMINER_PIN_KIND, EXAMINER_PIN_KIND_CALLER_CONFIG

OBSERVED_KIND_UNOBSERVED = "unobserved"
OBSERVED_KIND_RUNTIME = "runtime_observed"
# Authenticated is named only so it can be rejected. 3A never produces it.
OBSERVED_KIND_AUTHENTICATED = "authenticated"
_OBSERVED_KINDS_ALLOWED = frozenset({OBSERVED_KIND_UNOBSERVED, OBSERVED_KIND_RUNTIME})

ROLE_PROPOSER = "proposer"
ROLE_EXAMINER = "examiner"
_ROLES = frozenset({ROLE_PROPOSER, ROLE_EXAMINER})

BINDING_SOURCE_TRUSTED_CONFIG = "trusted_config"


@dataclass(frozen=True)
class TrustedProductConfig:
    """Product-owned configuration. Not runtime-observed evidence."""

    proposer_provider_id: str
    proposer_model_id: str
    examiner_provider_id: str
    examiner_model_id: str
    examiner_id: str
    examiner_version: str
    observation_prompt_sha256: str
    pin_kind: str = EXAMINER_PIN_KIND_CALLER_CONFIG

    def __post_init__(self) -> None:
        require_str(self.proposer_provider_id, field="proposer_provider_id")
        require_str(self.proposer_model_id, field="proposer_model_id")
        require_str(self.examiner_provider_id, field="examiner_provider_id")
        require_str(self.examiner_model_id, field="examiner_model_id")
        require_str(self.examiner_id, field="examiner_id")
        require_str(self.examiner_version, field="examiner_version")
        require_str(self.observation_prompt_sha256, field="observation_prompt_sha256")
        if self.pin_kind != EXAMINER_PIN_KIND_CALLER_CONFIG:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "TrustedProductConfig.pin_kind must remain caller_config in V07-3A",
            )
        if EXAMINER_PIN_KIND != EXAMINER_PIN_KIND_CALLER_CONFIG:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "EXAMINER_PIN_KIND must remain caller_config in V07-3A",
            )


@dataclass(frozen=True)
class ObservedProvenanceEvidence:
    """Runtime-observed provenance slots.

    Filling these fields with caller-supplied labels does not authenticate
    those labels. ``kind`` cannot be ``authenticated`` in V07-3A.
    """

    kind: str = OBSERVED_KIND_UNOBSERVED
    served_model: str | None = None
    origin: str | None = None
    account_session: str | None = None
    observation_prompt_sha256: str | None = None
    registry_sha256: str | None = None
    policy_map_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.kind == OBSERVED_KIND_AUTHENTICATED:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "ObservedProvenanceEvidence cannot claim authenticated kind in V07-3A",
            )
        if self.kind not in _OBSERVED_KINDS_ALLOWED:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unknown observed provenance kind {self.kind!r}",
            )
        for field in (
            "served_model",
            "origin",
            "account_session",
            "observation_prompt_sha256",
            "registry_sha256",
            "policy_map_sha256",
        ):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value):
                raise HybridExecutionAbort(
                    "schema_invalid",
                    f"{field} must be None or a non-empty string",
                )


@dataclass(frozen=True)
class RoleBinding:
    """Configured proposer/examiner role label. Not authenticated origin."""

    role: str
    provider_id: str
    model_id: str
    pin_kind: str = EXAMINER_PIN_KIND_CALLER_CONFIG
    binding_source: str = BINDING_SOURCE_TRUSTED_CONFIG

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise HybridExecutionAbort("schema_invalid", f"unknown role {self.role!r}")
        require_str(self.provider_id, field="provider_id")
        require_str(self.model_id, field="model_id")
        if self.pin_kind != EXAMINER_PIN_KIND_CALLER_CONFIG:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "RoleBinding.pin_kind must remain caller_config in V07-3A",
            )
        if self.binding_source != BINDING_SOURCE_TRUSTED_CONFIG:
            raise HybridExecutionAbort(
                "schema_invalid",
                "RoleBinding.binding_source must be trusted_config in V07-3A",
            )


@dataclass(frozen=True)
class ContinuitySnapshot:
    """Continuity bits. ``ever_on`` is the canonical durable intent.

    ``ever_required`` is an in-process mirror only. See continuity.py.
    """

    ever_on: bool
    ever_required: bool
    persisted_report_schema_0_2_0: bool
    persisted_semantic: bool

    def __post_init__(self) -> None:
        for field in (
            "ever_on",
            "ever_required",
            "persisted_report_schema_0_2_0",
            "persisted_semantic",
        ):
            if not isinstance(getattr(self, field), bool):
                raise HybridExecutionAbort("schema_invalid", f"{field} must be a bool")


@dataclass(frozen=True)
class ReadinessInput:
    """Derived readiness *input*. Not a readiness conclusion and not installable."""

    trusted_config: TrustedProductConfig
    observed_evidence: ObservedProvenanceEvidence
    role_bindings: tuple[RoleBinding, ...]
    continuity: ContinuitySnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.trusted_config, TrustedProductConfig):
            raise HybridExecutionAbort("schema_invalid", "trusted_config type mismatch")
        if not isinstance(self.observed_evidence, ObservedProvenanceEvidence):
            raise HybridExecutionAbort("schema_invalid", "observed_evidence type mismatch")
        if not isinstance(self.continuity, ContinuitySnapshot):
            raise HybridExecutionAbort("schema_invalid", "continuity type mismatch")
        if not isinstance(self.role_bindings, tuple):
            raise HybridExecutionAbort("schema_invalid", "role_bindings must be a tuple")
        for item in self.role_bindings:
            if not isinstance(item, RoleBinding):
                raise HybridExecutionAbort("schema_invalid", "role_bindings must be RoleBinding values")


@dataclass(frozen=True)
class NotReady:
    """Readiness conclusion for V07-3A: never ready, never installable."""

    reason: str

    def __post_init__(self) -> None:
        require_str(self.reason, field="reason")

    def install(self, *args: Any, **kwargs: Any) -> None:
        raise HybridExecutionAbort(
            "continuity_required_not_ready",
            "NotReady cannot install a hybrid evaluator",
        )


def unobserved_provenance(**kwargs: Any) -> ObservedProvenanceEvidence:
    reject_authority_kwargs(kwargs, label="unobserved_provenance")
    return ObservedProvenanceEvidence(kind=OBSERVED_KIND_UNOBSERVED)


def observed_provenance(
    *,
    served_model: str | None = None,
    origin: str | None = None,
    account_session: str | None = None,
    observation_prompt_sha256: str | None = None,
    registry_sha256: str | None = None,
    policy_map_sha256: str | None = None,
    **kwargs: Any,
) -> ObservedProvenanceEvidence:
    """Mark slots as runtime-observed. Does not authenticate caller labels."""
    reject_authority_kwargs(kwargs, label="observed_provenance")
    return ObservedProvenanceEvidence(
        kind=OBSERVED_KIND_RUNTIME,
        served_model=served_model,
        origin=origin,
        account_session=account_session,
        observation_prompt_sha256=observation_prompt_sha256,
        registry_sha256=registry_sha256,
        policy_map_sha256=policy_map_sha256,
    )


def evidence_is_authenticated(evidence: ObservedProvenanceEvidence) -> bool:
    """3A never treats dataclass population as authenticated evidence."""
    if not isinstance(evidence, ObservedProvenanceEvidence):
        raise HybridExecutionAbort("schema_invalid", "evidence type mismatch")
    return False


def bind_roles(config: TrustedProductConfig, **kwargs: Any) -> tuple[RoleBinding, RoleBinding]:
    reject_authority_kwargs(kwargs, label="bind_roles")
    if not isinstance(config, TrustedProductConfig):
        raise HybridExecutionAbort("schema_invalid", "bind_roles requires TrustedProductConfig")
    return (
        RoleBinding(
            role=ROLE_PROPOSER,
            provider_id=config.proposer_provider_id,
            model_id=config.proposer_model_id,
        ),
        RoleBinding(
            role=ROLE_EXAMINER,
            provider_id=config.examiner_provider_id,
            model_id=config.examiner_model_id,
        ),
    )


def hybrid_ready(
    context: ReadinessInput | TrustedProductConfig | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> NotReady:
    """Always ``NotReady("slice_incomplete")`` for product contexts in 3A.

    Accepts readiness input, trusted config, or an arbitrary mapping so
    callers cannot obtain a Ready/install object by choosing a context
    type. Does not inspect caller labels as authenticated evidence.
    """
    reject_authority_kwargs(kwargs, label="hybrid_ready")
    if context is not None and not isinstance(
        context, (ReadinessInput, TrustedProductConfig, Mapping)
    ):
        raise HybridExecutionAbort("schema_invalid", "unsupported hybrid_ready context")
    return NotReady(reason="slice_incomplete")


__all__ = [
    "BINDING_SOURCE_TRUSTED_CONFIG",
    "ContinuitySnapshot",
    "NotReady",
    "OBSERVED_KIND_AUTHENTICATED",
    "OBSERVED_KIND_RUNTIME",
    "OBSERVED_KIND_UNOBSERVED",
    "ObservedProvenanceEvidence",
    "ROLE_EXAMINER",
    "ROLE_PROPOSER",
    "ReadinessInput",
    "RoleBinding",
    "TrustedProductConfig",
    "bind_roles",
    "evidence_is_authenticated",
    "hybrid_ready",
    "observed_provenance",
    "unobserved_provenance",
]
