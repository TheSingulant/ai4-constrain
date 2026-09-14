"""Operational separation checks (V07-3B §3).

Best-effort comparisons of proposer vs examiner:

- provider / model configured pins
- same provider / different model
- same model / different account
- same endpoint / different account
- shared proxy peer
- shared credential compare-tokens
- shared client / session object identity

This is **not** independence. Grades distinguish:

- ``hard_disqualifier`` — hybrid eligibility fails closed
- ``minimum_operational_separation`` — distinct pin, credential, object
- ``best_effort_anti_collusion`` — extra observed distinctions
- ``not_proven`` — residual (legal entity, attestation, collusion absence)

Credential equality
-------------------
Raw secrets are never persisted. Comparison uses an ephemeral
process-local HMAC-SHA256 keyed by a random 32-byte key created at
import. Tokens are not stable across processes and must not be written
to session/report JSON. This is preferred over a stable raw SHA-256 of
the secret, which would be a portable leakable fingerprint.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import RoleBinding
from ai4.constrain._v07_3b.origin import TransportBinding, canonicalize_origin

GRADE_HARD_DISQUALIFIER = "hard_disqualifier"
GRADE_MINIMUM_OPERATIONAL = "minimum_operational_separation"
GRADE_BEST_EFFORT = "best_effort_anti_collusion"
GRADE_NOT_PROVEN = "not_proven"
_GRADES = frozenset(
    {
        GRADE_HARD_DISQUALIFIER,
        GRADE_MINIMUM_OPERATIONAL,
        GRADE_BEST_EFFORT,
        GRADE_NOT_PROVEN,
    }
)

CREDENTIAL_COMPARE_ALGORITHM = "hmac-sha256-ephemeral-process-local"
_PROCESS_HMAC_KEY = secrets.token_bytes(32)


def credential_compare_token(secret: str, **kwargs: Any) -> bytes:
    """Ephemeral process-local compare token. Not a durable fingerprint."""
    reject_authority_kwargs(kwargs, label="credential_compare_token")
    require_str(secret, field="secret")
    return hmac.new(_PROCESS_HMAC_KEY, secret.encode("utf-8"), sha256).digest()


def credentials_equal(
    left: str | bytes | None,
    right: str | bytes | None,
    **kwargs: Any,
) -> bool:
    """Constant-time equality. Strings are hashed with the process key first."""
    reject_authority_kwargs(kwargs, label="credentials_equal")
    if left is None or right is None:
        return False
    left_token = left if isinstance(left, (bytes, bytearray)) else credential_compare_token(left)
    right_token = right if isinstance(right, (bytes, bytearray)) else credential_compare_token(right)
    if not isinstance(left_token, (bytes, bytearray)) or not isinstance(right_token, (bytes, bytearray)):
        raise HybridExecutionAbort("schema_invalid", "credential tokens must be bytes")
    return hmac.compare_digest(bytes(left_token), bytes(right_token))


def session_object_token(obj: object, **kwargs: Any) -> str:
    """Process-local object identity. Not a cryptographic session id."""
    reject_authority_kwargs(kwargs, label="session_object_token")
    if obj is None:
        raise HybridExecutionAbort("schema_invalid", "session object is required")
    return f"obj:{id(obj)}"


@dataclass(frozen=True)
class SeparationAssessment:
    """Operational-separation facts. Explicitly not an independence claim."""

    grade: str
    hard_disqualifiers: tuple[str, ...]
    minimum_satisfied: bool
    best_effort_notes: tuple[str, ...]
    not_proven: tuple[str, ...]
    same_provider: bool
    same_model: bool
    same_account: bool
    same_endpoint: bool
    shared_proxy: bool
    shared_credential: bool
    shared_session_object: bool

    def __post_init__(self) -> None:
        if self.grade not in _GRADES:
            raise HybridExecutionAbort("schema_invalid", f"unknown separation grade {self.grade!r}")
        if self.grade == "independence" or "independence" in self.grade:
            raise HybridExecutionAbort("schema_invalid", "separation must not be labeled independence")


_NOT_PROVEN = (
    "legal_entity_independence",
    "cryptographic_model_attestation",
    "absence_of_collusion",
    "account_org_distinctness",
)


def assess_operational_separation(
    *,
    proposer: RoleBinding,
    examiner: RoleBinding,
    proposer_account: str | None = None,
    examiner_account: str | None = None,
    proposer_origin: str | None = None,
    examiner_origin: str | None = None,
    proposer_transport: TransportBinding | None = None,
    examiner_transport: TransportBinding | None = None,
    proposer_credential: str | bytes | None = None,
    examiner_credential: str | bytes | None = None,
    proposer_session: object | None = None,
    examiner_session: object | None = None,
    **kwargs: Any,
) -> SeparationAssessment:
    reject_authority_kwargs(kwargs, label="assess_operational_separation")
    if not isinstance(proposer, RoleBinding) or not isinstance(examiner, RoleBinding):
        raise HybridExecutionAbort("schema_invalid", "role bindings are required")

    same_provider = proposer.provider_id == examiner.provider_id
    same_model = proposer.model_id == examiner.model_id
    same_account = (
        proposer_account is not None
        and examiner_account is not None
        and proposer_account == examiner_account
    )
    proposer_end = _endpoint(proposer_origin, proposer_transport)
    examiner_end = _endpoint(examiner_origin, examiner_transport)
    same_endpoint = proposer_end is not None and proposer_end == examiner_end
    shared_proxy = bool(
        proposer_transport is not None
        and examiner_transport is not None
        and proposer_transport.peer_origin == examiner_transport.peer_origin
        and (proposer_transport.peer_is_proxy or examiner_transport.peer_is_proxy)
    )
    shared_credential = credentials_equal(proposer_credential, examiner_credential)
    shared_session_object = (
        proposer_session is not None
        and examiner_session is not None
        and proposer_session is examiner_session
    )

    hard: list[str] = []
    if same_provider and same_model:
        hard.append("same_provider_and_model_pin")
    if shared_credential:
        hard.append("shared_credential")
    if shared_session_object:
        hard.append("shared_client_or_session_object")

    best: list[str] = []
    if same_provider and not same_model:
        best.append("same_provider_different_model")
    if same_model and not same_provider:
        best.append("same_model_different_provider")
    if (
        proposer_account
        and examiner_account
        and proposer_account != examiner_account
        and same_model
    ):
        best.append("same_model_different_account")
    if (
        proposer_account
        and examiner_account
        and proposer_account != examiner_account
        and same_endpoint
    ):
        best.append("same_endpoint_different_account")
    if shared_proxy:
        best.append("shared_proxy_peer")

    if hard:
        grade = GRADE_HARD_DISQUALIFIER
        minimum = False
    elif not same_provider and not same_model and not shared_credential and not shared_session_object:
        minimum = True
        grade = GRADE_BEST_EFFORT if best else GRADE_MINIMUM_OPERATIONAL
    else:
        # Distinct (provider, model) pair is the V07-2 pin bar, but same
        # provider with different model is only best-effort, not minimum.
        minimum = False
        grade = GRADE_BEST_EFFORT if (not (same_provider and same_model) and best) else GRADE_NOT_PROVEN

    return SeparationAssessment(
        grade=grade,
        hard_disqualifiers=tuple(hard),
        minimum_satisfied=minimum,
        best_effort_notes=tuple(best),
        not_proven=_NOT_PROVEN,
        same_provider=same_provider,
        same_model=same_model,
        same_account=same_account,
        same_endpoint=same_endpoint,
        shared_proxy=shared_proxy,
        shared_credential=shared_credential,
        shared_session_object=shared_session_object,
    )


def _endpoint(origin: str | None, transport: TransportBinding | None) -> str | None:
    if transport is not None:
        return transport.peer_origin
    if origin is None:
        return None
    return canonicalize_origin(origin)


__all__ = [
    "CREDENTIAL_COMPARE_ALGORITHM",
    "GRADE_BEST_EFFORT",
    "GRADE_HARD_DISQUALIFIER",
    "GRADE_MINIMUM_OPERATIONAL",
    "GRADE_NOT_PROVEN",
    "SeparationAssessment",
    "assess_operational_separation",
    "credential_compare_token",
    "credentials_equal",
    "session_object_token",
]
