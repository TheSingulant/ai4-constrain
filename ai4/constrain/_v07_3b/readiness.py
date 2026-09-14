"""Non-installing readiness facts (V07-3B §10).

3B may compute validation / readiness *facts* for tests. The conclusion
is always ``NotReady``. There is no ``Ready`` object and no install
path. Final readiness is deferred to V07-3C.

3A ``hybrid_ready`` remains ``NotReady("slice_incomplete")``. This
module does not replace that stub with an installing Ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ai4.constrain._v07_3a._common import reject_authority_kwargs
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import NotReady, ReadinessInput, TrustedProductConfig
from ai4.constrain._v07_3b.context import (
    ContextValidationFacts,
    HybridConfiguration,
    HybridContext,
    HybridContextValidator,
)

REASON_DEFERRED_TO_3C = "deferred_to_3c"


@dataclass(frozen=True)
class ReadinessFacts:
    """Computed facts. Explicitly not a Ready/install conclusion.

    ``configured_origin_allowlist_pass`` is configuration validation.
    ``origin_allowlisted`` is the runtime-observed provenance claim, not
    that config matched the allowlist. Config validation is not
    observation and cannot satisfy observed-provenance readiness.
    """

    origin_allowlisted: bool
    locked_artifacts_ok: bool
    continuity_required: bool
    hard_disqualified: bool
    minimum_operational_separation: bool
    observed_claim_names: tuple[str, ...]
    installing: bool = False
    ready: bool = False
    configured_origin_allowlist_pass: bool = False
    has_runtime_observed_provenance: bool = False

    def __post_init__(self) -> None:
        if self.installing or self.ready:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "ReadinessFacts cannot claim ready/installing in V07-3B",
            )


def compute_readiness_facts(
    source: HybridContext | ContextValidationFacts,
    **kwargs: Any,
) -> ReadinessFacts:
    reject_authority_kwargs(kwargs, label="compute_readiness_facts")
    if isinstance(source, HybridContext):
        facts = HybridContextValidator().validate(source)
    elif isinstance(source, ContextValidationFacts):
        facts = source
    else:
        raise HybridExecutionAbort("schema_invalid", "unsupported readiness source")
    return ReadinessFacts(
        origin_allowlisted=facts.origin_allowlisted,
        locked_artifacts_ok=facts.locked_artifacts_ok,
        continuity_required=facts.continuity_required,
        hard_disqualified=facts.hard_disqualified,
        minimum_operational_separation=facts.minimum_operational_separation,
        observed_claim_names=facts.observed_claim_names,
        installing=False,
        ready=False,
        configured_origin_allowlist_pass=facts.configured_origin_allowlist_pass,
        has_runtime_observed_provenance=facts.has_runtime_observed_provenance,
    )


def observed_provenance_required_satisfied(
    facts: ReadinessFacts,
    **kwargs: Any,
) -> bool:
    """Gate for readiness facts that require runtime-observed provenance.

    Configured allowlist pass is not observation and cannot satisfy this.
    """
    reject_authority_kwargs(kwargs, label="observed_provenance_required_satisfied")
    if not isinstance(facts, ReadinessFacts):
        raise HybridExecutionAbort("schema_invalid", "observed provenance gate needs ReadinessFacts")
    return bool(facts.has_runtime_observed_provenance)


def hybrid_ready(
    context: HybridContext | HybridConfiguration | ReadinessInput | TrustedProductConfig | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> NotReady:
    """Always ``NotReady`` — 3B does not install.

    Accepts the same broad context types as 3A so callers cannot obtain a
    Ready/install object by choosing a context type. Final readiness is
    deferred to V07-3C.
    """
    reject_authority_kwargs(kwargs, label="hybrid_ready")
    if context is not None and not isinstance(
        context,
        (HybridContext, HybridConfiguration, ReadinessInput, TrustedProductConfig, Mapping),
    ):
        raise HybridExecutionAbort("schema_invalid", "unsupported hybrid_ready context")
    if isinstance(context, HybridContext):
        # Compute facts for the test surface, then still refuse install.
        compute_readiness_facts(context)
    return NotReady(reason=REASON_DEFERRED_TO_3C)


__all__ = [
    "REASON_DEFERRED_TO_3C",
    "ReadinessFacts",
    "compute_readiness_facts",
    "hybrid_ready",
    "observed_provenance_required_satisfied",
]
