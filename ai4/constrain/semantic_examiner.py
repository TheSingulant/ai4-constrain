"""V07-2 semantic examiner adapter (observation only).

Sole job: take a candidate plus the frozen observation prompt/config,
call a distinct examiner backend, receive structured findings, then
parse/validate/bind through the existing V07-0 schema and return
evidence only.

This module MUST NOT score shards, route to shards, select penalties,
apply fusion, decide thresholds, arbitrate, revise, refuse, or determine
terminal outcomes.

Authority
---------
Examiner = observation. Packaged map = policy translation. Fusion =
deterministic tightening. Wall/arbitration = governing authority.

The adapter does not load or send the packaged policy map, shard caps,
fusion equation, arbitration thresholds, revision budget, or terminal
decision rules. It does not import the V07-1 fusion primitive.

Distinct pin
------------
``provider_id``, ``model_id``, ``examiner_id``, and ``examiner_version``
are caller-configured examiner labels/pins in V07-2. Echo validation
proves payload/config consistency only. It is not authenticated
provider/model provenance. V07-2 does not attest that a backend is
actually OpenAI/Anthropic/etc.

Hybrid-eligible use requires the caller-configured examiner pin to be
distinct from the caller-configured proposer pin. A fail-closed helper
rejects ``(provider_id, model_id)`` equality when a proposer pin is
supplied to this standalone adapter. That comparison is raw configured
label equality, not authenticated origin. Same-pin production use is not
operationalized. The helper is not wired into ``run()`` / ``evaluate()``.

Production hybrid use in V07-3 must bind independently authenticated
provider/model provenance before using distinct-pin guarantees
operationally. V07-2 records pin kind as adapter constant
``EXAMINER_PIN_KIND = caller_config`` only. A provenance-kind field is
not added to the V07-0 findings schema.

Span splitting
--------------
The adapter does not invent semantic clustering and does not fabricate
``claim_fingerprint_v1``. Spans are bound exactly to the candidate text
actually supplied. Span-splitting is an examiner-quality / adversarial
vector for later evaluation; it is not authority.

``SEMANTIC_EXAMINER_OPERATIONAL`` remains False. This primitive is
callable for tests and review the same way V07-1 fusion is callable; it
is not activated on the governing path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Mapping, Protocol

from ai4.constrain.errors import SemanticExaminerError, SemanticFindingsError
from ai4.constrain.semantic_findings import (
    FINDINGS_SCHEMA_VERSION,
    POLICY_SMUGGLE_KEYS,
    SEMANTIC_EXAMINER_OPERATIONAL,
    STATUSES,
    BoundSemanticFindings,
    bind_semantic_findings,
    parse_semantic_findings,
    validate_semantic_findings,
)

_PACKAGE = "ai4.data"
_RELATIVE = ("semantic_v07",)
OBSERVATION_PROMPT_FILENAME = "observation_prompt_v1.txt"
OBSERVATION_PROMPT_ARTIFACT_ID = "observation_prompt_v1"
OBSERVATION_PROMPT_VERSION = "0.7.2"
LOCKED_OBSERVATION_PROMPT_SHA256 = (
    "6ec541e391f7207a1b12ee1a00c7311c8de4a50810651a0eca829a2f07dc62bf"
)

EXAMINER_REQUEST_FIELDS = (
    "candidate",
    "observation_prompt",
    "observation_prompt_sha256",
    "schema_version",
    "examiner_id",
    "examiner_version",
    "model_id",
    "provider_id",
    "temperature",
)
BACKEND_RESULT_FIELDS = ("status", "payload_text")

# Adapter-level pin kind. Not a V07-0 findings-schema field.
# Echo validation compares caller-supplied labels to the payload; it does
# not authenticate a provider or model.
EXAMINER_PIN_KIND_CALLER_CONFIG = "caller_config"
EXAMINER_PIN_KIND_AUTHENTICATED = "authenticated"
EXAMINER_PIN_KIND = EXAMINER_PIN_KIND_CALLER_CONFIG

# Adapter kwargs that would smuggle policy, control, or frozen-config overrides.
_ADAPTER_AUTHORITY_KEYS = frozenset(POLICY_SMUGGLE_KEYS) | frozenset(
    {
        "arbitration_thresholds",
        "cap",
        "caps",
        "delta",
        "deltas",
        "fusion",
        "fusion_equation",
        "max_revision_rounds",
        "observation_prompt",
        "observation_prompt_sha256",
        "overlay",
        "overlays",
        "overlay_deltas",
        "penalties",
        "penalty",
        "policy_map",
        "registry",
        "revision_budget",
        "route",
        "routing",
        "shard_caps",
        "temperature",
        "terminal_decision_rules",
        "weight",
        "weights",
    }
)

_NON_OK_STATUSES = tuple(status for status in STATUSES if status != "ok")


def _sha256_hex(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise SemanticExaminerError("SHA-256 identity requires bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def _require_str(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SemanticExaminerError(f"{field} must be a non-empty string")
    return raw


def packaged_observation_prompt_bytes() -> bytes:
    """Exact UTF-8 bytes of the frozen V07-2 observation prompt artifact."""
    traversable = files(_PACKAGE).joinpath(*_RELATIVE, OBSERVATION_PROMPT_FILENAME)
    try:
        payload = traversable.read_bytes()
    except Exception as exc:
        raise SemanticExaminerError(
            f"Packaged observation prompt {OBSERVATION_PROMPT_FILENAME!r} "
            f"is missing or unreadable: {exc}"
        ) from exc
    if not payload.strip():
        raise SemanticExaminerError(
            f"Packaged observation prompt {OBSERVATION_PROMPT_FILENAME!r} is empty"
        )
    return bytes(payload)


def observation_prompt_text() -> str:
    raw = packaged_observation_prompt_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SemanticExaminerError(
            f"Observation prompt is not UTF-8: {exc}"
        ) from exc


def observation_prompt_sha256() -> str:
    digest = _sha256_hex(packaged_observation_prompt_bytes())
    if digest != LOCKED_OBSERVATION_PROMPT_SHA256:
        raise SemanticExaminerError(
            "observation prompt digest mismatch; failing closed"
        )
    return digest


@dataclass(frozen=True)
class ExaminerObservationRequest:
    """Narrow observation request. This is not a policy or control object.

    ``examiner_id``, ``examiner_version``, ``provider_id``, and ``model_id``
    are caller-configured examiner labels/pins
    (``EXAMINER_PIN_KIND == caller_config``). Echo validation proves
    payload/config consistency only. They are not authenticated
    provider/model provenance.

    The backend may receive only what is necessary to examine the candidate.
    It must not receive a packaged policy map, shard caps, fusion equation,
    arbitration thresholds, revision budget, or terminal decision rules.
    """

    candidate: str
    observation_prompt: str
    observation_prompt_sha256: str
    schema_version: str
    examiner_id: str
    examiner_version: str
    model_id: str
    provider_id: str
    temperature: int


@dataclass(frozen=True)
class ExaminerBackendResult:
    """Narrow backend result. Status is observation status, not a decision."""

    status: str
    payload_text: str | bytes | None = None


class ExaminerBackend(Protocol):
    """Distinct examiner backend. Tests may supply a synthetic implementation."""

    def observe(self, request: ExaminerObservationRequest) -> ExaminerBackendResult:
        """Return structured observation output or a non-ok observation status."""


def assert_hybrid_eligible_distinct_pin(
    *,
    proposer_provider_id: str,
    proposer_model_id: str,
    examiner_provider_id: str,
    examiner_model_id: str,
    **kwargs: Any,
) -> None:
    """Fail closed when proposer and examiner share ``(provider_id, model_id)``.

    Hybrid-eligible use requires a distinct caller-configured examiner pin.
    This helper compares raw ``(provider_id, model_id)`` labels only. It is
    not authenticated provider/model provenance. It is not called from
    ``run()`` / ``evaluate()`` and does not operationalize same-pin
    production use. Production hybrid use in V07-3 must bind independently
    authenticated provider/model provenance before using this guarantee
    operationally.
    """
    if kwargs:
        blocked = sorted(str(key) for key in kwargs if key in _ADAPTER_AUTHORITY_KEYS)
        if blocked:
            raise SemanticExaminerError(
                f"distinct-pin helper supplies policy/control field(s) {blocked}; "
                "failing closed"
            )
        extra = sorted(str(key) for key in kwargs)
        raise SemanticExaminerError(
            f"Unknown distinct-pin helper argument(s) {extra}; failing closed"
        )
    proposer_provider = _require_str(
        proposer_provider_id, field="proposer_provider_id"
    )
    proposer_model = _require_str(proposer_model_id, field="proposer_model_id")
    examiner_provider = _require_str(
        examiner_provider_id, field="examiner_provider_id"
    )
    examiner_model = _require_str(examiner_model_id, field="examiner_model_id")
    if (proposer_provider, proposer_model) == (examiner_provider, examiner_model):
        raise SemanticExaminerError(
            "hybrid-eligible use requires examiner (provider_id, model_id) "
            "distinct from proposer; failing closed"
        )


def _reject_adapter_kwargs(kwargs: Mapping[str, Any], *, label: str) -> None:
    if not kwargs:
        return
    blocked = sorted(str(key) for key in kwargs if key in _ADAPTER_AUTHORITY_KEYS)
    if blocked:
        raise SemanticExaminerError(
            f"{label} supplies policy/control field(s) {blocked}; failing closed"
        )
    extra = sorted(str(key) for key in kwargs)
    raise SemanticExaminerError(f"Unknown {label} argument(s) {extra}; failing closed")


def _non_ok_payload(request: ExaminerObservationRequest, status: str) -> dict[str, Any]:
    return {
        "schema_version": request.schema_version,
        "examiner_id": request.examiner_id,
        "examiner_version": request.examiner_version,
        "model_id": request.model_id,
        "provider_id": request.provider_id,
        "observation_prompt_sha256": request.observation_prompt_sha256,
        "temperature": request.temperature,
        "status": status,
        "findings": [],
    }


def _assert_payload_matches_request(
    payload: Any,
    request: ExaminerObservationRequest,
) -> None:
    if payload.schema_version != request.schema_version:
        raise SemanticExaminerError(
            "examiner schema_version does not match frozen observation config; "
            "failing closed"
        )
    if payload.examiner_id != request.examiner_id:
        raise SemanticExaminerError(
            "examiner_id does not match caller-configured examiner pin; failing closed"
        )
    if payload.examiner_version != request.examiner_version:
        raise SemanticExaminerError(
            "examiner_version does not match caller-configured examiner pin; failing closed"
        )
    if payload.model_id != request.model_id:
        raise SemanticExaminerError(
            "model_id does not match caller-configured examiner pin; failing closed"
        )
    if payload.provider_id != request.provider_id:
        raise SemanticExaminerError(
            "provider_id does not match caller-configured examiner pin; failing closed"
        )
    if payload.observation_prompt_sha256 != request.observation_prompt_sha256:
        raise SemanticExaminerError(
            "observation_prompt_sha256 does not match frozen observation prompt; "
            "failing closed"
        )
    if payload.temperature != 0 or request.temperature != 0:
        raise SemanticExaminerError("temperature must remain 0; failing closed")


def _bind_non_ok(
    request: ExaminerObservationRequest,
    status: str,
) -> BoundSemanticFindings:
    if status not in _NON_OK_STATUSES:
        raise SemanticExaminerError(f"Unknown findings status {status!r}; failing closed")
    payload = validate_semantic_findings(_non_ok_payload(request, status))
    bound = bind_semantic_findings(payload, candidate=request.candidate)
    if bound.payload.status != status:
        raise SemanticExaminerError(
            "adapter would not preserve examiner failure status; failing closed"
        )
    if bound.payload.status == "ok":
        raise SemanticExaminerError(
            "examiner failure must not become empty successful findings"
        )
    if bound.findings:
        raise SemanticExaminerError("non-ok examiner result must not include findings")
    return bound


def _parse_ok_payload(
    request: ExaminerObservationRequest,
    payload_text: str | bytes | None,
) -> BoundSemanticFindings:
    if payload_text is None or payload_text == b"" or payload_text == "":
        raise SemanticExaminerError(
            "ok examiner status requires findings JSON; failing closed"
        )
    try:
        payload = parse_semantic_findings(payload_text)
    except SemanticFindingsError:
        raise
    if payload.status != "ok":
        raise SemanticExaminerError(
            "backend reported ok but payload status is non-ok; failing closed"
        )
    _assert_payload_matches_request(payload, request)
    return bind_semantic_findings(payload, candidate=request.candidate)


def _parse_reported_non_ok(
    request: ExaminerObservationRequest,
    result: ExaminerBackendResult,
) -> BoundSemanticFindings:
    if result.payload_text is None or result.payload_text == b"" or result.payload_text == "":
        return _bind_non_ok(request, result.status)
    try:
        payload = parse_semantic_findings(result.payload_text)
    except SemanticFindingsError:
        raise
    if payload.status != result.status:
        raise SemanticExaminerError(
            "backend status and payload status disagree; failing closed"
        )
    if payload.status == "ok":
        raise SemanticExaminerError(
            "examiner failure must not become empty successful findings"
        )
    _assert_payload_matches_request(payload, request)
    bound = bind_semantic_findings(payload, candidate=request.candidate)
    if bound.payload.status != result.status or bound.findings:
        raise SemanticExaminerError(
            "non-ok examiner result must preserve status and empty findings"
        )
    return bound


def observe_semantic_candidate(
    candidate: str,
    backend: ExaminerBackend,
    *,
    examiner_id: str,
    examiner_version: str,
    provider_id: str,
    model_id: str,
    proposer_provider_id: str | None = None,
    proposer_model_id: str | None = None,
    **kwargs: Any,
) -> BoundSemanticFindings:
    """Call a distinct examiner backend and bind V07-0 evidence.

    Returns bound findings (evidence only). Does not score, fuse, route,
    threshold, arbitrate, revise, refuse, or emit ACCEPT/REVISE/REFUSE.

    Caller-supplied ``examiner_id``, ``examiner_version``, ``provider_id``,
    and ``model_id`` are configuration pins. Echo validation proves
    payload/config consistency only. It is not authenticated
    provider/model provenance. V07-2 does not attest that a backend is
    actually OpenAI/Anthropic/etc.

    If a caller-configured proposer pin is supplied, hybrid-eligible
    distinct-pin equality of ``(provider_id, model_id)`` fails closed on
    raw label equality. That check is not wired into ``run()`` /
    ``evaluate()``. Production hybrid use in V07-3 must bind independently
    authenticated provider/model provenance before using distinct-pin
    guarantees operationally.
    """
    if SEMANTIC_EXAMINER_OPERATIONAL is not False:
        raise SemanticExaminerError(
            "SEMANTIC_EXAMINER_OPERATIONAL must remain False for V07-2"
        )
    if EXAMINER_PIN_KIND != EXAMINER_PIN_KIND_CALLER_CONFIG:
        raise SemanticExaminerError(
            "V07-2 examiner pin kind must be caller_config; authenticated "
            "provenance is not implemented; failing closed"
        )
    _reject_adapter_kwargs(kwargs, label="observe_semantic_candidate")
    if not isinstance(candidate, str):
        raise SemanticExaminerError("candidate must be a string")
    if backend is None or not callable(getattr(backend, "observe", None)):
        raise SemanticExaminerError(
            "examiner backend must implement observe(request); failing closed"
        )
    examiner_id_s = _require_str(examiner_id, field="examiner_id")
    examiner_version_s = _require_str(examiner_version, field="examiner_version")
    provider_id_s = _require_str(provider_id, field="provider_id")
    model_id_s = _require_str(model_id, field="model_id")

    proposer_supplied = proposer_provider_id is not None or proposer_model_id is not None
    if proposer_supplied:
        if proposer_provider_id is None or proposer_model_id is None:
            raise SemanticExaminerError(
                "proposer identity requires both proposer_provider_id and "
                "proposer_model_id; failing closed"
            )
        assert_hybrid_eligible_distinct_pin(
            proposer_provider_id=proposer_provider_id,
            proposer_model_id=proposer_model_id,
            examiner_provider_id=provider_id_s,
            examiner_model_id=model_id_s,
        )

    prompt = observation_prompt_text()
    prompt_digest = observation_prompt_sha256()
    request = ExaminerObservationRequest(
        candidate=candidate,
        observation_prompt=prompt,
        observation_prompt_sha256=prompt_digest,
        schema_version=FINDINGS_SCHEMA_VERSION,
        examiner_id=examiner_id_s,
        examiner_version=examiner_version_s,
        model_id=model_id_s,
        provider_id=provider_id_s,
        temperature=0,
    )
    extra_request_fields = sorted(
        field for field in request.__dataclass_fields__ if field not in EXAMINER_REQUEST_FIELDS
    )
    if extra_request_fields:
        raise SemanticExaminerError(
            f"examiner request has extra field(s) {extra_request_fields}; failing closed"
        )

    try:
        raw_result = backend.observe(request)
    except SemanticFindingsError:
        raise
    except Exception as exc:
        raise SemanticExaminerError(
            f"examiner backend failed closed: {exc}"
        ) from exc

    if not isinstance(raw_result, ExaminerBackendResult):
        raise SemanticExaminerError(
            "examiner backend must return ExaminerBackendResult; failing closed"
        )
    extra_result_fields = sorted(
        field
        for field in raw_result.__dataclass_fields__
        if field not in BACKEND_RESULT_FIELDS
    )
    if extra_result_fields:
        raise SemanticExaminerError(
            f"examiner backend result has extra field(s) {extra_result_fields}; "
            "failing closed"
        )
    status = _require_str(raw_result.status, field="backend status")
    if status not in STATUSES:
        raise SemanticExaminerError(f"Unknown findings status {status!r}; failing closed")
    if status == "ok":
        return _parse_ok_payload(request, raw_result.payload_text)
    return _parse_reported_non_ok(request, raw_result)


__all__ = [
    "BACKEND_RESULT_FIELDS",
    "EXAMINER_PIN_KIND",
    "EXAMINER_PIN_KIND_AUTHENTICATED",
    "EXAMINER_PIN_KIND_CALLER_CONFIG",
    "EXAMINER_REQUEST_FIELDS",
    "LOCKED_OBSERVATION_PROMPT_SHA256",
    "OBSERVATION_PROMPT_ARTIFACT_ID",
    "OBSERVATION_PROMPT_FILENAME",
    "OBSERVATION_PROMPT_VERSION",
    "ExaminerBackend",
    "ExaminerBackendResult",
    "ExaminerObservationRequest",
    "assert_hybrid_eligible_distinct_pin",
    "observation_prompt_sha256",
    "observation_prompt_text",
    "observe_semantic_candidate",
    "packaged_observation_prompt_bytes",
]
