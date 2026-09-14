"""Session identity schema 0.2.0 (V07-3B §6).

Additive hybrid-capable identity. Product ``SessionState`` remains
schema 0.1.1 and OFF serialization is unchanged unless a caller
constructs an explicit 0.2.0 object through this internal module.

Continuity
----------
``ever_on`` is the canonical durable intent. ``ever_required`` is an
in-process mirror only. Redundant evidence only tightens / fail-closes
(Candidate 2.2). This parser never sets ``ever_on=true`` from
``api.run``.

Readers
-------
- 0.1.x OFF documents load as OFF (``ever_on=False``)
- 0.2.0 OFF (``ever_on=false``, no semantic payload) is behavior-compatible
- 0.2.0 hybrid identity is parseable here and does not install
- Product ``SessionState.from_dict`` hitting 0.2.0 or injected hybrid
  keys fails predictably (no silent drop)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_bool, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import ContinuitySnapshot
from ai4.constrain._v07_3a.continuity import (
    continuity_snapshot_from_persisted,
    durable_continuity_intent,
    hybrid_continuity_required,
    tighten_continuity_state,
)
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.session import SESSION_SCHEMA_VERSION, SessionState
from ai4.constrain._v07_3b.snapshot import ArtifactContinuitySnapshot

SESSION_SCHEMA_VERSION_0_1_0 = "0.1.0"
SESSION_SCHEMA_VERSION_0_1_1 = "0.1.1"
SESSION_SCHEMA_VERSION_0_2_0 = "0.2.0"
HYBRID_IDENTITY_SCHEMA_VERSION = "0.2.0"

_OFF_COMPATIBLE = frozenset({SESSION_SCHEMA_VERSION_0_1_0, SESSION_SCHEMA_VERSION_0_1_1})
HYBRID_SESSION_IDENTITY_KEYS = (
    "schema_version",
    "ever_on",
    "artifact_snapshot",
)


@dataclass(frozen=True)
class HybridSessionIdentity:
    """Additive 0.2.0 identity block. Not an activation switch."""

    ever_on: bool
    schema_version: str = HYBRID_IDENTITY_SCHEMA_VERSION
    artifact_snapshot: ArtifactContinuitySnapshot | None = None

    def __post_init__(self) -> None:
        require_bool(self.ever_on, field="ever_on")
        if self.schema_version != HYBRID_IDENTITY_SCHEMA_VERSION:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"hybrid identity schema must be {HYBRID_IDENTITY_SCHEMA_VERSION}",
            )
        if self.artifact_snapshot is not None and not isinstance(
            self.artifact_snapshot, ArtifactContinuitySnapshot
        ):
            raise HybridExecutionAbort("schema_invalid", "artifact_snapshot type mismatch")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "ever_on": self.ever_on,
            "artifact_snapshot": None
            if self.artifact_snapshot is None
            else self.artifact_snapshot.to_dict(),
        }
        return payload

    @classmethod
    def from_dict(cls, raw: object) -> HybridSessionIdentity:
        if not isinstance(raw, Mapping):
            raise HybridExecutionAbort("schema_invalid", "hybrid_identity must be an object")
        extra = sorted(str(key) for key in raw if key not in HYBRID_SESSION_IDENTITY_KEYS)
        if extra:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unknown hybrid_identity field(s) {extra}; refusing silent drop",
            )
        missing = [key for key in ("schema_version", "ever_on") if key not in raw]
        if missing:
            raise HybridExecutionAbort("schema_invalid", f"hybrid_identity missing {missing}")
        snapshot_raw = raw.get("artifact_snapshot")
        snapshot = None if snapshot_raw is None else ArtifactContinuitySnapshot.from_dict(snapshot_raw)
        return cls(
            schema_version=require_str(raw["schema_version"], field="schema_version"),
            ever_on=require_bool(raw["ever_on"], field="ever_on"),
            artifact_snapshot=snapshot,
        )


@dataclass(frozen=True)
class HybridSessionDocument:
    """0.2.0 session document or an OFF 0.1.x view."""

    schema_version: str
    off_state: SessionState
    identity: HybridSessionIdentity
    ever_required: bool = False

    def __post_init__(self) -> None:
        if self.schema_version not in _OFF_COMPATIBLE | {SESSION_SCHEMA_VERSION_0_2_0}:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"unsupported session schema_version {self.schema_version!r}",
            )
        if not isinstance(self.off_state, SessionState):
            raise HybridExecutionAbort("schema_invalid", "off_state type mismatch")
        if not isinstance(self.identity, HybridSessionIdentity):
            raise HybridExecutionAbort("schema_invalid", "identity type mismatch")
        require_bool(self.ever_required, field="ever_required")
        if self.schema_version in _OFF_COMPATIBLE and self.identity.ever_on:
            raise HybridExecutionAbort(
                "schema_invalid",
                "0.1.x OFF documents cannot carry ever_on=true",
            )

    def continuity_snapshot(self) -> ContinuitySnapshot:
        durable, mirror = tighten_continuity_state(
            ever_on=self.identity.ever_on,
            ever_required=self.ever_required,
        )
        payloads = [turn.report.to_dict() for turn in self.off_state.turns]
        return continuity_snapshot_from_persisted(
            ever_on=durable,
            ever_required=mirror,
            payloads=payloads,
        )

    def continuity_required(self) -> bool:
        return hybrid_continuity_required(self.continuity_snapshot())

    def durable_intent(self) -> bool:
        return durable_continuity_intent(self.continuity_snapshot())


def _off_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    payload["schema_version"] = SESSION_SCHEMA_VERSION
    payload.pop("ever_on", None)
    payload.pop("ever_required", None)
    payload.pop("hybrid_identity", None)
    payload.pop("hybrid", None)
    payload.pop("continuity", None)
    payload.pop("artifact_snapshot", None)
    return payload


def parse_session_document(raw: object, **kwargs: Any) -> HybridSessionDocument:
    """Load 0.1.x OFF or 0.2.0 hybrid-capable identity. Does not install."""
    reject_authority_kwargs(kwargs, label="parse_session_document")
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HybridExecutionAbort("schema_invalid", f"malformed session JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise HybridExecutionAbort("schema_invalid", "session document must be an object")
    schema = str(raw.get("schema_version") or "")
    if schema in _OFF_COMPATIBLE:
        leaked = [
            key
            for key in ("ever_on", "ever_required", "hybrid_identity", "hybrid", "semantic")
            if key in raw
        ]
        if leaked:
            raise HybridExecutionAbort(
                "schema_invalid",
                f"0.1.x session carries hybrid identity field(s) {leaked}; "
                "refusing silent drop",
            )
        try:
            state = SessionState.from_dict(_off_payload(raw))
        except ConstraintExecutionError as exc:
            raise HybridExecutionAbort("schema_invalid", str(exc)) from exc
        return HybridSessionDocument(
            schema_version=schema,
            off_state=state,
            identity=HybridSessionIdentity(ever_on=False),
            ever_required=False,
        )
    if schema != SESSION_SCHEMA_VERSION_0_2_0:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"unsupported session schema_version {schema!r}",
        )
    identity_raw = raw.get("hybrid_identity")
    if identity_raw is None:
        ever_on = raw.get("ever_on", False)
        identity = HybridSessionIdentity(
            ever_on=require_bool(ever_on, field="ever_on") if "ever_on" in raw else False,
            artifact_snapshot=(
                ArtifactContinuitySnapshot.from_dict(raw["artifact_snapshot"])
                if raw.get("artifact_snapshot") is not None
                else None
            ),
        )
    else:
        identity = HybridSessionIdentity.from_dict(identity_raw)
        if "ever_on" in raw and require_bool(raw["ever_on"], field="ever_on") != identity.ever_on:
            raise HybridExecutionAbort(
                "schema_invalid",
                "ever_on disagrees with hybrid_identity.ever_on; fail-closed tighten only",
            )
    ever_required = False
    if "ever_required" in raw:
        ever_required = require_bool(raw["ever_required"], field="ever_required")
        durable, ever_required = tighten_continuity_state(
            ever_on=identity.ever_on,
            ever_required=ever_required,
        )
        if durable != identity.ever_on:
            raise HybridExecutionAbort(
                "continuity_required_not_ready",
                "continuity disagreement cannot clear ever_on",
            )
    try:
        state = SessionState.from_dict(_off_payload(raw))
    except ConstraintExecutionError as exc:
        raise HybridExecutionAbort("schema_invalid", str(exc)) from exc
    return HybridSessionDocument(
        schema_version=SESSION_SCHEMA_VERSION_0_2_0,
        off_state=state,
        identity=identity,
        ever_required=ever_required,
    )


def serialize_session_document(document: HybridSessionDocument, **kwargs: Any) -> dict[str, Any]:
    """Serialize. 0.1.x OFF uses the product SessionState mapping unchanged."""
    reject_authority_kwargs(kwargs, label="serialize_session_document")
    if not isinstance(document, HybridSessionDocument):
        raise HybridExecutionAbort("schema_invalid", "serialize_session_document needs HybridSessionDocument")
    if document.schema_version in _OFF_COMPATIBLE:
        payload = document.off_state.to_dict()
        # Product snapshots are 0.1.1. Preserve the source 0.1.x label only
        # when the caller constructed an explicit 0.1.0 view.
        if document.schema_version == SESSION_SCHEMA_VERSION_0_1_0:
            payload = dict(payload)
            payload["schema_version"] = SESSION_SCHEMA_VERSION_0_1_0
        return payload
    payload = document.off_state.to_dict()
    payload["schema_version"] = SESSION_SCHEMA_VERSION_0_2_0
    payload["ever_on"] = document.identity.ever_on
    payload["hybrid_identity"] = document.identity.to_dict()
    return payload


def serialize_session_json(document: HybridSessionDocument, **kwargs: Any) -> str:
    reject_authority_kwargs(kwargs, label="serialize_session_json")
    payload = serialize_session_document(document)
    if document.schema_version in _OFF_COMPATIBLE:
        return document.off_state.to_json()
    return json.dumps(payload, indent=2, ensure_ascii=False)


__all__ = [
    "HYBRID_IDENTITY_SCHEMA_VERSION",
    "HYBRID_SESSION_IDENTITY_KEYS",
    "HybridSessionDocument",
    "HybridSessionIdentity",
    "SESSION_SCHEMA_VERSION_0_1_0",
    "SESSION_SCHEMA_VERSION_0_1_1",
    "SESSION_SCHEMA_VERSION_0_2_0",
    "parse_session_document",
    "serialize_session_document",
    "serialize_session_json",
]
