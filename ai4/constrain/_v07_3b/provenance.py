"""Provenance evidence model (V07-3B §1).

Non-cryptographic vocabulary only:

    configured
    transport_bound
    origin_allowlisted
    provider_session_bound
    served_model_observed
    account_observed

Invariants
----------
- ``configured`` ≠ ``observed`` ≠ ``attested``.
- No cryptographic model attestation claim exists in this slice.
- Caller-config labels cannot mint runtime-observed provenance.
- Production-grade evidence is produced only by product-owned collectors.
  Arbitrary dataclass population is caller-populated labeling, not
  runtime-observed evidence.

3A ``ObservedProvenanceEvidence`` remains. This module adds sealed claim
slots and collectors on top of that vocabulary.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import (
    OBSERVED_KIND_RUNTIME,
    OBSERVED_KIND_UNOBSERVED,
    ObservedProvenanceEvidence,
)

CLAIM_CONFIGURED = "configured"
CLAIM_TRANSPORT_BOUND = "transport_bound"
CLAIM_ORIGIN_ALLOWLISTED = "origin_allowlisted"
CLAIM_PROVIDER_SESSION_BOUND = "provider_session_bound"
CLAIM_SERVED_MODEL_OBSERVED = "served_model_observed"
CLAIM_ACCOUNT_OBSERVED = "account_observed"

PROVENANCE_CLAIMS = (
    CLAIM_CONFIGURED,
    CLAIM_TRANSPORT_BOUND,
    CLAIM_ORIGIN_ALLOWLISTED,
    CLAIM_PROVIDER_SESSION_BOUND,
    CLAIM_SERVED_MODEL_OBSERVED,
    CLAIM_ACCOUNT_OBSERVED,
)

MINT_CALLER_POPULATED = "caller_populated"
MINT_CONFIGURED = "configured_collector"
MINT_TRANSPORT = "transport_collector"
MINT_ALLOWLIST = "allowlist_collector"
MINT_SESSION = "session_collector"
MINT_SERVED_MODEL = "served_model_collector"
MINT_ACCOUNT = "account_collector"

_OBSERVED_MINTERS = frozenset(
    {
        MINT_TRANSPORT,
        MINT_ALLOWLIST,
        MINT_SESSION,
        MINT_SERVED_MODEL,
        MINT_ACCOUNT,
    }
)
_CLAIM_TO_MINTER = {
    CLAIM_CONFIGURED: MINT_CONFIGURED,
    CLAIM_TRANSPORT_BOUND: MINT_TRANSPORT,
    CLAIM_ORIGIN_ALLOWLISTED: MINT_ALLOWLIST,
    CLAIM_PROVIDER_SESSION_BOUND: MINT_SESSION,
    CLAIM_SERVED_MODEL_OBSERVED: MINT_SERVED_MODEL,
    CLAIM_ACCOUNT_OBSERVED: MINT_ACCOUNT,
}
_SEAL = threading.local()


def _minting(name: str):
    class _Ctx:
        def __enter__(self) -> None:
            _SEAL.name = name

        def __exit__(self, *_exc: object) -> None:
            _SEAL.name = None

    return _Ctx()


@dataclass(frozen=True)
class ProvenanceClaim:
    """One sealed provenance slot.

    ``minted_by`` records which collector produced the claim. Caller
    population cannot select an observed minter. ``attested`` is not a
    constructible state.
    """

    claim: str
    value: str | None
    minted_by: str

    def __post_init__(self) -> None:
        if self.claim not in PROVENANCE_CLAIMS:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unknown provenance claim {self.claim!r}",
            )
        if self.value is not None:
            require_str(self.value, field="value")
        expected = _CLAIM_TO_MINTER[self.claim]
        if self.minted_by == MINT_CALLER_POPULATED:
            if self.claim != CLAIM_CONFIGURED:
                # Caller labels may only sit on the configured slot.
                raise HybridExecutionAbort(
                    "caller_config_pin_forbidden",
                    "caller-populated labels cannot mint runtime-observed provenance",
                )
            return
        if self.minted_by != expected:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                f"claim {self.claim!r} cannot be minted by {self.minted_by!r}",
            )
        if self.minted_by in _OBSERVED_MINTERS | {MINT_CONFIGURED}:
            if getattr(_SEAL, "name", None) != self.minted_by:
                raise HybridExecutionAbort(
                    "caller_config_pin_forbidden",
                    "caller-populated labels cannot mint runtime-observed provenance",
                )

    def is_runtime_observed(self) -> bool:
        return self.minted_by in _OBSERVED_MINTERS

    def is_configured_only(self) -> bool:
        return self.claim == CLAIM_CONFIGURED or self.minted_by in {
            MINT_CONFIGURED,
            MINT_CALLER_POPULATED,
        }

    def is_attested(self) -> bool:
        return False


@dataclass(frozen=True)
class ProvenanceEvidenceBundle:
    """Closed set of provenance claims. Never attested."""

    claims: tuple[ProvenanceClaim, ...]
    kind: str = OBSERVED_KIND_UNOBSERVED

    def __post_init__(self) -> None:
        if self.kind not in {OBSERVED_KIND_UNOBSERVED, OBSERVED_KIND_RUNTIME}:
            raise HybridExecutionAbort(
                "caller_config_pin_forbidden",
                "ProvenanceEvidenceBundle cannot claim authenticated/attested kind",
            )
        if not isinstance(self.claims, tuple):
            raise HybridExecutionAbort("schema_invalid", "claims must be a tuple")
        seen: set[str] = set()
        observed = False
        for item in self.claims:
            if not isinstance(item, ProvenanceClaim):
                raise HybridExecutionAbort("schema_invalid", "claims must be ProvenanceClaim values")
            if item.claim in seen:
                raise HybridExecutionAbort("schema_invalid", f"duplicate claim {item.claim!r}")
            seen.add(item.claim)
            if item.is_runtime_observed():
                observed = True
        if self.kind == OBSERVED_KIND_RUNTIME and not observed:
            raise HybridExecutionAbort(
                "provenance_mismatch",
                "runtime_observed kind requires at least one collector-minted observed claim",
            )
        if self.kind == OBSERVED_KIND_UNOBSERVED and observed:
            raise HybridExecutionAbort(
                "provenance_mismatch",
                "unobserved kind cannot carry collector-minted observed claims",
            )

    def claim(self, name: str) -> ProvenanceClaim | None:
        for item in self.claims:
            if item.claim == name:
                return item
        return None

    def observed_value(self, name: str) -> str | None:
        item = self.claim(name)
        if item is None or not item.is_runtime_observed():
            return None
        return item.value


def _collect(claim: str, value: str | None, minted_by: str) -> ProvenanceClaim:
    with _minting(minted_by):
        return ProvenanceClaim(claim=claim, value=value, minted_by=minted_by)


def collect_configured(value: str, **kwargs: Any) -> ProvenanceClaim:
    """Caller/product configuration label. Not observed, not attested."""
    reject_authority_kwargs(kwargs, label="collect_configured")
    return _collect(CLAIM_CONFIGURED, require_str(value, field="value"), MINT_CONFIGURED)


def collect_transport_bound(peer_origin: str, **kwargs: Any) -> ProvenanceClaim:
    """Record the connected peer origin. Not a TLS attestation."""
    reject_authority_kwargs(kwargs, label="collect_transport_bound")
    return _collect(
        CLAIM_TRANSPORT_BOUND,
        require_str(peer_origin, field="peer_origin"),
        MINT_TRANSPORT,
    )


def collect_origin_allowlisted(canonical_origin: str, **kwargs: Any) -> ProvenanceClaim:
    """Record that a canonical origin passed the product allowlist."""
    reject_authority_kwargs(kwargs, label="collect_origin_allowlisted")
    return _collect(
        CLAIM_ORIGIN_ALLOWLISTED,
        require_str(canonical_origin, field="canonical_origin"),
        MINT_ALLOWLIST,
    )


def collect_provider_session_bound(session_token: str, **kwargs: Any) -> ProvenanceClaim:
    """Bind to a process-local provider session token. Not a secret."""
    reject_authority_kwargs(kwargs, label="collect_provider_session_bound")
    return _collect(
        CLAIM_PROVIDER_SESSION_BOUND,
        require_str(session_token, field="session_token"),
        MINT_SESSION,
    )


def collect_served_model_observed(served_model: str, **kwargs: Any) -> ProvenanceClaim:
    """Runtime-observed served-model string from a response body field."""
    reject_authority_kwargs(kwargs, label="collect_served_model_observed")
    return _collect(
        CLAIM_SERVED_MODEL_OBSERVED,
        require_str(served_model, field="served_model"),
        MINT_SERVED_MODEL,
    )


def collect_account_observed(account_id: str, **kwargs: Any) -> ProvenanceClaim:
    """Runtime-observed account identifier from a response body field."""
    reject_authority_kwargs(kwargs, label="collect_account_observed")
    return _collect(
        CLAIM_ACCOUNT_OBSERVED,
        require_str(account_id, field="account_id"),
        MINT_ACCOUNT,
    )


def bundle_claims(
    claims: Iterable[ProvenanceClaim],
    **kwargs: Any,
) -> ProvenanceEvidenceBundle:
    reject_authority_kwargs(kwargs, label="bundle_claims")
    items = tuple(claims)
    observed = any(item.is_runtime_observed() for item in items)
    return ProvenanceEvidenceBundle(
        claims=items,
        kind=OBSERVED_KIND_RUNTIME if observed else OBSERVED_KIND_UNOBSERVED,
    )


def evidence_is_attested(evidence: object) -> bool:
    """3B never treats collector output or dataclass population as attestation."""
    if isinstance(evidence, ProvenanceClaim):
        return False
    if isinstance(evidence, ProvenanceEvidenceBundle):
        return False
    if isinstance(evidence, ObservedProvenanceEvidence):
        return False
    raise HybridExecutionAbort("schema_invalid", "evidence type mismatch")


def evidence_is_authenticated(evidence: object) -> bool:
    """Alias retained for 3A wording. Authentication is not claimed in 3B."""
    return evidence_is_attested(evidence)


__all__ = [
    "CLAIM_ACCOUNT_OBSERVED",
    "CLAIM_CONFIGURED",
    "CLAIM_ORIGIN_ALLOWLISTED",
    "CLAIM_PROVIDER_SESSION_BOUND",
    "CLAIM_SERVED_MODEL_OBSERVED",
    "CLAIM_TRANSPORT_BOUND",
    "MINT_ACCOUNT",
    "MINT_ALLOWLIST",
    "MINT_CALLER_POPULATED",
    "MINT_CONFIGURED",
    "MINT_SERVED_MODEL",
    "MINT_SESSION",
    "MINT_TRANSPORT",
    "PROVENANCE_CLAIMS",
    "ProvenanceClaim",
    "ProvenanceEvidenceBundle",
    "bundle_claims",
    "collect_account_observed",
    "collect_configured",
    "collect_origin_allowlisted",
    "collect_provider_session_bound",
    "collect_served_model_observed",
    "collect_transport_bound",
    "evidence_is_attested",
    "evidence_is_authenticated",
]
