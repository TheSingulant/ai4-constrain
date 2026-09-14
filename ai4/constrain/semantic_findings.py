"""V07-0 findings-only semantic evidence schema.

The semantic examiner may produce evidence about a candidate. It may not
define policy, routing, thresholds, arbitration, revision/refusal, or
terminal control. Evaluator-wall and packaged-policy authority stay
product-owned.

V07-0 parses, validates, and binds examiner payloads and computes a
runtime-owned ``claim_fingerprint_v1``. It does not call an examiner
backend, does not fuse overlays into accept/revise/refuse, and does not
change default ``run()`` / ``evaluate()`` behavior. Semantic mode remains
non-operational.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.shards.shard_loader import REQUIRED_IDS

from ai4.constrain.errors import SemanticFindingsError
from ai4.constrain.semantic_taxonomy import (
    CONFIDENCE_BINS,
    FindingRegistryV1,
    load_finding_registry_v1,
)

FINDINGS_SCHEMA_VERSION = "ai4.semantic_findings.v0.7-c2"
CLAIM_FINGERPRINT_VERSION = "cf_v1"
SEMANTIC_EXAMINER_OPERATIONAL = False

STATUSES = (
    "ok",
    "timeout",
    "schema_invalid",
    "backend_error",
    "injection_suspected",
    "empty_parse",
)

PAYLOAD_KEYS = (
    "schema_version",
    "examiner_id",
    "examiner_version",
    "model_id",
    "provider_id",
    "observation_prompt_sha256",
    "temperature",
    "status",
    "findings",
)
FINDING_KEYS = (
    "finding_id",
    "class_id",
    "confidence_bin",
    "span",
    "quote_sha256",
    "observation_code",
    "injection_signal_codes",
)
SPAN_KEYS = ("start", "end")

# Examiner payloads may not smuggle policy, control, or runtime-owned fields.
POLICY_SMUGGLE_KEYS = frozenset(
    {
        "accept",
        "arbitration",
        "claim_fingerprint",
        "comment",
        "comments",
        "decision",
        "explanation",
        "freeform",
        "fused_score",
        "fused_scores",
        "hard",
        "kind",
        "note",
        "notes",
        "passed",
        "priority",
        "rationale",
        "reasoning",
        "refuse",
        "revise",
        "revision_targets",
        "score",
        "scores",
        "shard_hints",
        "shard_id",
        "shard_ids",
        "soft",
        "threshold",
        "thresholds",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNIT_SEPARATOR = b"\x1f"


def _sha256_hex(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise SemanticFindingsError("SHA-256 requires bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def _require_object(raw: object, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SemanticFindingsError(f"{label} must be a JSON object")
    if any(not isinstance(key, str) for key in raw):
        raise SemanticFindingsError(f"{label} keys must be strings")
    return raw


def _reject_extra(raw: Mapping[str, Any], keys: tuple[str, ...], *, label: str) -> None:
    extra = sorted(str(key) for key in raw if key not in keys)
    if extra:
        raise SemanticFindingsError(f"Unknown {label} field(s) {extra}; failing closed")
    missing = [key for key in keys if key not in raw]
    if missing:
        raise SemanticFindingsError(f"{label} missing keys: {missing}")


def _require_str(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SemanticFindingsError(f"{field} must be a non-empty string")
    return raw


def _require_sha256_hex(raw: object, *, field: str) -> str:
    text = _require_str(raw, field=field)
    if not _SHA256_RE.fullmatch(text):
        raise SemanticFindingsError(f"{field} must be lowercase SHA-256 hex")
    return text


def _require_int(raw: object, *, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise SemanticFindingsError(f"{field} must be an integer")
    return raw


def _walk_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise SemanticFindingsError("Non-string object key; failing closed")
            keys.append(key)
            keys.extend(_walk_keys(nested))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    elif isinstance(value, float) and not math.isfinite(value):
        raise SemanticFindingsError("Non-finite number in findings payload; failing closed")
    return keys


def _reject_smuggled_and_shard_keys(payload: Mapping[str, Any]) -> None:
    keys = _walk_keys(payload)
    smuggled = sorted({key for key in keys if key in POLICY_SMUGGLE_KEYS})
    if smuggled:
        raise SemanticFindingsError(
            f"Examiner payload supplies policy/control field(s) {smuggled}; failing closed"
        )
    shard_keys = sorted({key for key in keys if key in REQUIRED_IDS})
    if shard_keys:
        raise SemanticFindingsError(
            f"Examiner payload supplies extra shard name(s) {shard_keys}; failing closed"
        )


def quote_sha256_for_span(candidate: str, start: int, end: int) -> str:
    """SHA-256 of UTF-8 bytes of candidate[start:end] using Unicode scalar indices."""
    excerpt = _slice_scalars(candidate, start, end)
    return _sha256_hex(excerpt.encode("utf-8"))


def _slice_scalars(candidate: str, start: int, end: int) -> str:
    if not isinstance(candidate, str):
        raise SemanticFindingsError("candidate must be a string")
    length = len(candidate)
    if start > end:
        raise SemanticFindingsError("span start must not exceed end")
    if start == end:
        raise SemanticFindingsError("span must be non-empty (start == end)")
    if start < 0 or end < 0 or start >= length or end > length:
        raise SemanticFindingsError("span is out of bounds for the bound candidate")
    return candidate[start:end]


def claim_fingerprint_v1(
    *,
    class_id: str,
    start: int,
    end: int,
    quote_sha256: str,
) -> str:
    """Runtime-owned claim fingerprint. Examiners must not supply this field.

    SHA-256 of UTF-8 bytes:
    ``cf_v1`` + 0x1f + class_id + 0x1f + start_decimal + 0x1f + end_decimal
    + 0x1f + quote_sha256
    """
    if not isinstance(class_id, str) or not class_id:
        raise SemanticFindingsError("class_id must be a non-empty string")
    if isinstance(start, bool) or not isinstance(start, int):
        raise SemanticFindingsError("span start must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise SemanticFindingsError("span end must be an integer")
    digest = _require_sha256_hex(quote_sha256, field="quote_sha256")
    material = (
        CLAIM_FINGERPRINT_VERSION.encode("ascii")
        + _UNIT_SEPARATOR
        + class_id.encode("utf-8")
        + _UNIT_SEPARATOR
        + str(start).encode("ascii")
        + _UNIT_SEPARATOR
        + str(end).encode("ascii")
        + _UNIT_SEPARATOR
        + digest.encode("ascii")
    )
    return _sha256_hex(material)


@dataclass(frozen=True)
class FindingSpan:
    start: int
    end: int


@dataclass(frozen=True)
class SemanticFinding:
    finding_id: str
    class_id: str
    confidence_bin: str
    span: FindingSpan
    quote_sha256: str
    observation_code: str
    injection_signal_codes: tuple[str, ...]


@dataclass(frozen=True)
class SemanticFindingsPayload:
    schema_version: str
    examiner_id: str
    examiner_version: str
    model_id: str
    provider_id: str
    observation_prompt_sha256: str
    temperature: int
    status: str
    findings: tuple[SemanticFinding, ...]


@dataclass(frozen=True)
class BoundFinding:
    finding: SemanticFinding
    claim_fingerprint: str


@dataclass(frozen=True)
class BoundSemanticFindings:
    payload: SemanticFindingsPayload
    candidate: str
    findings: tuple[BoundFinding, ...]


def _decode_json(raw: str | bytes) -> object:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SemanticFindingsError(f"Findings payload is not UTF-8: {exc}") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise SemanticFindingsError("parse_semantic_findings requires JSON text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SemanticFindingsError(f"Malformed findings JSON: {exc}") from exc


def _require_temperature(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SemanticFindingsError("temperature must be the finite number 0")
    if isinstance(raw, float) and not math.isfinite(raw):
        raise SemanticFindingsError("temperature must be the finite number 0")
    if raw != 0:
        raise SemanticFindingsError("temperature must be 0")
    return 0


def _parse_span(raw: object, *, label: str) -> FindingSpan:
    span = _require_object(raw, label=label)
    _reject_extra(span, SPAN_KEYS, label=label)
    start = _require_int(span["start"], field=f"{label}.start")
    end = _require_int(span["end"], field=f"{label}.end")
    if start > end:
        raise SemanticFindingsError(f"{label} start must not exceed end")
    if start == end:
        raise SemanticFindingsError(f"{label} must be non-empty (start == end)")
    if start < 0 or end < 0:
        raise SemanticFindingsError(f"{label} offsets must be >= 0")
    return FindingSpan(start=start, end=end)


def _parse_finding(
    raw: object,
    *,
    index: int,
    registry: FindingRegistryV1,
    require_complete: bool,
) -> SemanticFinding:
    label = f"findings[{index}]"
    item = _require_object(raw, label=label)
    _reject_smuggled_and_shard_keys(item)
    if not require_complete:
        raise SemanticFindingsError("non-ok status must not include findings")
    _reject_extra(item, FINDING_KEYS, label=label)
    finding_id = _require_str(item["finding_id"], field=f"{label}.finding_id")
    class_id = _require_str(item["class_id"], field=f"{label}.class_id")
    if class_id not in registry.class_id_set():
        raise SemanticFindingsError(f"Unknown class_id {class_id!r}; failing closed")
    confidence_bin = _require_str(item["confidence_bin"], field=f"{label}.confidence_bin")
    if confidence_bin not in CONFIDENCE_BINS:
        raise SemanticFindingsError(
            f"{label}.confidence_bin must be one of {list(CONFIDENCE_BINS)}"
        )
    span = _parse_span(item["span"], label=f"{label}.span")
    quote_sha256 = _require_sha256_hex(item["quote_sha256"], field=f"{label}.quote_sha256")
    observation_code = _require_str(item["observation_code"], field=f"{label}.observation_code")
    if observation_code not in registry.observation_code_set():
        raise SemanticFindingsError(
            f"Unknown observation_code {observation_code!r}; failing closed"
        )
    codes_raw = item["injection_signal_codes"]
    if not isinstance(codes_raw, list):
        raise SemanticFindingsError(f"{label}.injection_signal_codes must be an array")
    codes: list[str] = []
    allowed_injection = registry.injection_signal_code_set()
    for code_index, code in enumerate(codes_raw):
        text = _require_str(code, field=f"{label}.injection_signal_codes[{code_index}]")
        if text not in allowed_injection:
            raise SemanticFindingsError(
                f"Unknown injection_signal_code {text!r}; failing closed"
            )
        if text in codes:
            raise SemanticFindingsError(
                f"{label}.injection_signal_codes has duplicate {text!r}"
            )
        codes.append(text)
    return SemanticFinding(
        finding_id=finding_id,
        class_id=class_id,
        confidence_bin=confidence_bin,
        span=span,
        quote_sha256=quote_sha256,
        observation_code=observation_code,
        injection_signal_codes=tuple(codes),
    )


def validate_semantic_findings(
    payload: object,
    *,
    registry: FindingRegistryV1 | None = None,
) -> SemanticFindingsPayload:
    """Validate an examiner findings object. Fail closed. Does not bind a candidate."""
    document = _require_object(payload, label="semantic findings payload")
    _reject_smuggled_and_shard_keys(document)
    _reject_extra(document, PAYLOAD_KEYS, label="semantic findings payload")
    schema_version = _require_str(document["schema_version"], field="schema_version")
    if schema_version != FINDINGS_SCHEMA_VERSION:
        raise SemanticFindingsError(
            f"schema_version must be {FINDINGS_SCHEMA_VERSION!r}"
        )
    status = _require_str(document["status"], field="status")
    if status not in STATUSES:
        raise SemanticFindingsError(f"Unknown findings status {status!r}; failing closed")
    loaded_registry = registry if registry is not None else load_finding_registry_v1()
    findings_raw = document["findings"]
    if not isinstance(findings_raw, list):
        raise SemanticFindingsError("findings must be an array")
    require_complete = status == "ok"
    if not require_complete and findings_raw:
        raise SemanticFindingsError("non-ok status must use an empty findings array")
    findings = tuple(
        _parse_finding(
            item,
            index=index,
            registry=loaded_registry,
            require_complete=require_complete,
        )
        for index, item in enumerate(findings_raw)
    )
    seen_ids: set[str] = set()
    for item in findings:
        if item.finding_id in seen_ids:
            raise SemanticFindingsError(
                f"Duplicate finding_id {item.finding_id!r}; failing closed"
            )
        seen_ids.add(item.finding_id)
    return SemanticFindingsPayload(
        schema_version=schema_version,
        examiner_id=_require_str(document["examiner_id"], field="examiner_id"),
        examiner_version=_require_str(document["examiner_version"], field="examiner_version"),
        model_id=_require_str(document["model_id"], field="model_id"),
        provider_id=_require_str(document["provider_id"], field="provider_id"),
        observation_prompt_sha256=_require_sha256_hex(
            document["observation_prompt_sha256"], field="observation_prompt_sha256"
        ),
        temperature=_require_temperature(document["temperature"]),
        status=status,
        findings=findings,
    )


def parse_semantic_findings(
    raw: str | bytes,
    *,
    registry: FindingRegistryV1 | None = None,
) -> SemanticFindingsPayload:
    """Parse JSON text and validate the examiner findings schema. Fail closed."""
    return validate_semantic_findings(_decode_json(raw), registry=registry)


def _as_payload(
    raw: str | bytes | Mapping[str, Any] | SemanticFindingsPayload,
    *,
    registry: FindingRegistryV1 | None = None,
) -> SemanticFindingsPayload:
    if isinstance(raw, SemanticFindingsPayload):
        return raw
    if isinstance(raw, (str, bytes)):
        return parse_semantic_findings(raw, registry=registry)
    return validate_semantic_findings(raw, registry=registry)


def bind_semantic_findings(
    raw: str | bytes | Mapping[str, Any] | SemanticFindingsPayload,
    *,
    candidate: str,
    registry: FindingRegistryV1 | None = None,
) -> BoundSemanticFindings:
    """Bind validated findings to the candidate actually passed to this call.

    Recomputes ``quote_sha256`` from Unicode-scalar offsets into ``candidate``.
    Mismatch, empty, inverted, or out-of-bounds spans fail closed. Attaches
    runtime-owned ``claim_fingerprint_v1``. Examiners must not supply it.
    """
    if not isinstance(candidate, str):
        raise SemanticFindingsError("bind_semantic_findings requires a candidate string")
    payload = _as_payload(raw, registry=registry)
    if payload.status != "ok":
        if payload.findings:
            raise SemanticFindingsError("non-ok status must not include findings")
        return BoundSemanticFindings(payload=payload, candidate=candidate, findings=())
    bound: list[BoundFinding] = []
    for finding in payload.findings:
        excerpt = _slice_scalars(candidate, finding.span.start, finding.span.end)
        actual_quote = _sha256_hex(excerpt.encode("utf-8"))
        if actual_quote != finding.quote_sha256:
            raise SemanticFindingsError(
                "quote_sha256 does not match the bound candidate span; failing closed"
            )
        fingerprint = claim_fingerprint_v1(
            class_id=finding.class_id,
            start=finding.span.start,
            end=finding.span.end,
            quote_sha256=actual_quote,
        )
        bound.append(BoundFinding(finding=finding, claim_fingerprint=fingerprint))
    return BoundSemanticFindings(
        payload=payload,
        candidate=candidate,
        findings=tuple(bound),
    )


def findings_to_dict(payload: SemanticFindingsPayload) -> dict[str, Any]:
    """Re-serialize a validated payload. Never includes claim_fingerprint."""
    return {
        "schema_version": payload.schema_version,
        "examiner_id": payload.examiner_id,
        "examiner_version": payload.examiner_version,
        "model_id": payload.model_id,
        "provider_id": payload.provider_id,
        "observation_prompt_sha256": payload.observation_prompt_sha256,
        "temperature": payload.temperature,
        "status": payload.status,
        "findings": [
            {
                "finding_id": item.finding_id,
                "class_id": item.class_id,
                "confidence_bin": item.confidence_bin,
                "span": {"start": item.span.start, "end": item.span.end},
                "quote_sha256": item.quote_sha256,
                "observation_code": item.observation_code,
                "injection_signal_codes": list(item.injection_signal_codes),
            }
            for item in payload.findings
        ],
    }


__all__ = [
    "BoundFinding",
    "BoundSemanticFindings",
    "CLAIM_FINGERPRINT_VERSION",
    "FINDINGS_SCHEMA_VERSION",
    "FindingSpan",
    "POLICY_SMUGGLE_KEYS",
    "SEMANTIC_EXAMINER_OPERATIONAL",
    "STATUSES",
    "SemanticFinding",
    "SemanticFindingsPayload",
    "bind_semantic_findings",
    "claim_fingerprint_v1",
    "findings_to_dict",
    "parse_semantic_findings",
    "quote_sha256_for_span",
    "validate_semantic_findings",
]
