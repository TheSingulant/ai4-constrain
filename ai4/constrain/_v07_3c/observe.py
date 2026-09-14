"""Bind 3B collectors to actual product observation points (V07-3C).

Collectors themselves are syntax-level. This module reads live provider
and examiner connection machinery and only then mints claims. Config
labels never become runtime-observed provenance. Missing required
dimensions fail Ready; they are not degraded to configured-only.

Honest non-claims: this is not TLS attestation, cryptographic model
proof, or authentication.
"""

from __future__ import annotations

from typing import Any

from ai4.constrain._v07_3a._common import reject_authority_kwargs
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3b.origin import TransportBinding, allowlist_origin, bind_transport
from ai4.constrain._v07_3b.provenance import (
    ProvenanceEvidenceBundle,
    bundle_claims,
    collect_account_observed,
    collect_configured,
    collect_origin_allowlisted,
    collect_provider_session_bound,
    collect_served_model_observed,
    collect_transport_bound,
)

_REQUIRED_ATTRS = (
    "observed_peer_origin",
    "observed_account_id",
    "observed_session_token",
    "observed_served_model",
)


def read_connection_observation(obj: object, *, role: str, **kwargs: Any) -> dict[str, str]:
    """Read runtime observation slots from a live bound object.

    Attributes must exist on the connected provider/examiner. Caller
    config is not consulted and cannot mint these values.
    """
    reject_authority_kwargs(kwargs, label="read_connection_observation")
    if obj is None:
        raise HybridExecutionAbort(
            "provenance_mismatch",
            f"{role} connection is not bound; required runtime provenance cannot be observed",
        )
    missing = [name for name in _REQUIRED_ATTRS if not str(getattr(obj, name, "") or "")]
    if missing:
        raise HybridExecutionAbort(
            "provenance_mismatch",
            f"{role} connection is missing runtime observation point(s) {missing}",
        )
    return {
        "peer_origin": str(getattr(obj, "observed_peer_origin")),
        "account_id": str(getattr(obj, "observed_account_id")),
        "session_token": str(getattr(obj, "observed_session_token")),
        "served_model": str(getattr(obj, "observed_served_model")),
    }


def bind_observed_transport(
    *,
    requested_origin: str,
    peer_origin: str,
    allowlist: tuple[str, ...],
    **kwargs: Any,
) -> TransportBinding:
    reject_authority_kwargs(kwargs, label="bind_observed_transport")
    binding = bind_transport(
        requested_origin=requested_origin,
        peer_origin=peer_origin,
        allowlist=allowlist,
    )
    allowlist_origin(binding.peer_origin, allowlist)
    return binding


def _bundle_for_role(
    *,
    configured_label: str,
    obs: dict[str, str],
    transport: TransportBinding,
    origin_allowlist: tuple[str, ...],
) -> ProvenanceEvidenceBundle:
    return bundle_claims(
        [
            collect_configured(configured_label),
            collect_transport_bound(transport.peer_origin),
            collect_origin_allowlisted(allowlist_origin(transport.peer_origin, origin_allowlist)),
            collect_provider_session_bound(obs["session_token"]),
            collect_served_model_observed(obs["served_model"]),
            collect_account_observed(obs["account_id"]),
        ]
    )


def observation_from_bundle(bundle: ProvenanceEvidenceBundle) -> dict[str, str]:
    """Recover the four continuity dimensions from a role-scoped bundle."""
    return {
        "peer_origin": bundle.observed_value("transport_bound") or "",
        "account_id": bundle.observed_value("account_observed") or "",
        "session_token": bundle.observed_value("provider_session_bound") or "",
        "served_model": bundle.observed_value("served_model_observed") or "",
    }


def role_observation_identity(role: str, obs: dict[str, str]) -> str:
    """Encode observed-at-install origin/account/session/model for one role."""
    return (
        f"{role}:origin={obs['peer_origin']};account={obs['account_id']};"
        f"session={obs['session_token']};model={obs['served_model']}"
    )


def bind_role_scoped_identities(context: object) -> object:
    """Stamp install snapshot identities from each role's observed bundle.

    Proposer values live on ``proposer_identity``. Examiner values live on
    ``examiner_provenance_identity``. One role cannot occupy the other slot.
    """
    from dataclasses import replace

    examiner_bundle = getattr(context, "examiner_provenance", None)
    if examiner_bundle is None:
        return context
    proposer_obs = observation_from_bundle(context.provenance)
    examiner_obs = observation_from_bundle(examiner_bundle)
    return replace(
        context,
        identity_snapshot=replace(
            context.identity_snapshot,
            proposer_identity=role_observation_identity("proposer", proposer_obs),
            examiner_provenance_identity=role_observation_identity("examiner", examiner_obs),
        ),
    )


def mint_runtime_provenance(
    *,
    configured_label: str,
    proposer: object,
    examiner: object,
    proposer_requested_origin: str,
    examiner_requested_origin: str,
    origin_allowlist: tuple[str, ...],
    examiner_configured_label: str | None = None,
    **kwargs: Any,
) -> tuple[
    ProvenanceEvidenceBundle,
    ProvenanceEvidenceBundle,
    TransportBinding,
    TransportBinding,
    dict[str, str],
    dict[str, str],
]:
    """Mint parallel role-scoped collector bundles from live observation points."""
    reject_authority_kwargs(kwargs, label="mint_runtime_provenance")
    proposer_obs = read_connection_observation(proposer, role="proposer")
    examiner_obs = read_connection_observation(examiner, role="examiner")
    proposer_transport = bind_observed_transport(
        requested_origin=proposer_requested_origin,
        peer_origin=proposer_obs["peer_origin"],
        allowlist=origin_allowlist,
    )
    examiner_transport = bind_observed_transport(
        requested_origin=examiner_requested_origin,
        peer_origin=examiner_obs["peer_origin"],
        allowlist=origin_allowlist,
    )
    proposer_bundle = _bundle_for_role(
        configured_label=configured_label,
        obs=proposer_obs,
        transport=proposer_transport,
        origin_allowlist=origin_allowlist,
    )
    examiner_bundle = _bundle_for_role(
        configured_label=examiner_configured_label or configured_label,
        obs=examiner_obs,
        transport=examiner_transport,
        origin_allowlist=origin_allowlist,
    )
    return (
        proposer_bundle,
        examiner_bundle,
        proposer_transport,
        examiner_transport,
        proposer_obs,
        examiner_obs,
    )


def assert_served_model_matches(*, expected: str, observed: str, **kwargs: Any) -> None:
    reject_authority_kwargs(kwargs, label="assert_served_model_matches")
    if expected != observed:
        raise HybridExecutionAbort(
            "served_model_mismatch",
            f"served model {observed!r} does not match installed {expected!r}",
        )


def assert_account_session_match(
    *,
    expected_account: str,
    observed_account: str,
    expected_session: str,
    observed_session: str,
    **kwargs: Any,
) -> None:
    reject_authority_kwargs(kwargs, label="assert_account_session_match")
    if expected_account != observed_account or expected_session != observed_session:
        raise HybridExecutionAbort(
            "account_session_mismatch",
            "account or provider session identity drifted from installed context",
        )


def assert_origin_matches(*, expected: str, observed: str, **kwargs: Any) -> None:
    reject_authority_kwargs(kwargs, label="assert_origin_matches")
    if expected != observed:
        raise HybridExecutionAbort(
            "origin_allowlist_failure",
            f"peer origin {observed!r} does not match installed {expected!r}",
        )


__all__ = [
    "assert_account_session_match",
    "assert_origin_matches",
    "assert_served_model_matches",
    "bind_observed_transport",
    "bind_role_scoped_identities",
    "mint_runtime_provenance",
    "observation_from_bundle",
    "read_connection_observation",
    "role_observation_identity",
]
