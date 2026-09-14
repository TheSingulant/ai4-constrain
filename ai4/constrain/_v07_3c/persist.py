"""Continuity / session / report persistence (V07-3C).

Commit point matches FileSessionStore.save: tmp write then Path.replace.
This is not fsync, WAL, or power-loss durability.

Install writes ``ever_on=true`` as the last install step. Persistence
failure fails closed and is not treated as a successful install.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from ai4.constrain._v07_3a._common import reject_authority_kwargs
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import ContinuitySnapshot
from ai4.constrain._v07_3a.continuity import (
    FILE_SESSION_STORE_COMMIT_POINT,
    continuity_snapshot_from_persisted,
    hybrid_continuity_required,
    inspect_persisted_report_schema_0_2_0,
    inspect_persisted_semantic,
    tighten_continuity_state,
)
from ai4.constrain._v07_3b.session import (
    SESSION_SCHEMA_VERSION_0_2_0,
    HybridSessionDocument,
    HybridSessionIdentity,
    parse_session_document,
    serialize_session_document,
)
from ai4.constrain._v07_3b.snapshot import ArtifactContinuitySnapshot
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.ext import FROZEN_EVALUATOR_ID, FROZEN_EVALUATOR_IMPL
from ai4.constrain.runtime import (
    ARBITRATION_VERSION,
    CONDITION,
    EVIDENCE_CLASS,
    PROTOCOL_VERSION,
    REPORT_SCHEMA_VERSION,
    RUNTIME_VERSION,
)
from ai4.constrain.session import SESSION_SCHEMA_VERSION, SessionPolicyIdentity, SessionState, validate_session_id
from ai4.constrain.trace import utc_now

COMMIT_POINT = FILE_SESSION_STORE_COMMIT_POINT


class ContinuityStore(Protocol):
    def load(self, session_id: str) -> dict[str, Any] | None:
        """Return a raw document mapping, or None if absent."""

    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        """Persist with tmp write + Path.replace semantics."""


class FileContinuityStore:
    """JSON document store using the FileSessionStore commit point."""

    def __init__(self, directory: str | Path, *, suffix: str = ".json") -> None:
        self.directory = Path(directory)
        self.suffix = suffix
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HybridExecutionAbort("backend_error", f"cannot create persist directory: {exc}") from exc
        if not self.directory.is_dir():
            raise HybridExecutionAbort("backend_error", f"persist path is not a directory: {self.directory}")

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{validate_session_id(session_id)}{self.suffix}"

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HybridExecutionAbort("backend_error", f"failed to load {session_id}: {exc}") from exc
        if not text.strip():
            raise HybridExecutionAbort("schema_invalid", f"truncated persist document {session_id}")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HybridExecutionAbort("schema_invalid", f"malformed persist JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise HybridExecutionAbort("schema_invalid", "persist document must be an object")
        return raw

    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        sid = validate_session_id(session_id)
        if not isinstance(payload, dict):
            raise HybridExecutionAbort("schema_invalid", "persist payload must be an object")
        path = self._path(sid)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            # Live commit point: tmp write then Path.replace. Not fsync/WAL.
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            raise HybridExecutionAbort("backend_error", f"failed to persist {sid}: {exc}") from exc
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


class FailingContinuityStore:
    """Product-owned test/store double that fails closed on save."""

    def __init__(self, inner: ContinuityStore | None = None, *, fail_on_save: bool = True) -> None:
        self._inner = inner
        self.fail_on_save = fail_on_save
        self.save_calls = 0

    def load(self, session_id: str) -> dict[str, Any] | None:
        if self._inner is None:
            return None
        return self._inner.load(session_id)

    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        self.save_calls += 1
        if self.fail_on_save:
            raise HybridExecutionAbort("backend_error", "injected persist failure")
        if self._inner is None:
            raise HybridExecutionAbort("backend_error", "persist store has no inner")
        self._inner.save(session_id, payload)


def empty_off_state(session_id: str) -> SessionState:
    now = utc_now()
    return SessionState(
        session_id=validate_session_id(session_id),
        schema_version=SESSION_SCHEMA_VERSION,
        created_at=now,
        updated_at=now,
        policy_identity=SessionPolicyIdentity(
            runtime_version=RUNTIME_VERSION,
            report_schema_version=REPORT_SCHEMA_VERSION,
            protocol=PROTOCOL_VERSION,
            condition=CONDITION,
            evidence_class=EVIDENCE_CLASS,
            rubric_set="v0.1",
            evaluator_id=FROZEN_EVALUATOR_ID,
            arbitration=ARBITRATION_VERSION,
        ),
        include_history=False,
        max_history_turns=16,
        redact=True,
        turns=(),
        evaluator_impl=FROZEN_EVALUATOR_IMPL,
    )


def load_session_document(store: ContinuityStore, session_id: str, **kwargs: Any) -> HybridSessionDocument | None:
    reject_authority_kwargs(kwargs, label="load_session_document")
    raw = store.load(session_id)
    if raw is None:
        return None
    return parse_session_document(raw)


def repair_continuity(
    *,
    ever_on: bool,
    ever_required: bool,
    payloads: tuple[object, ...],
    **kwargs: Any,
) -> tuple[bool, bool, ContinuitySnapshot]:
    """Fail-closed repair: evidence true while ever_on false → set ever_on true."""
    reject_authority_kwargs(kwargs, label="repair_continuity")
    schema = any(inspect_persisted_report_schema_0_2_0(item) for item in payloads)
    semantic = any(inspect_persisted_semantic(item) for item in payloads)
    evidence = bool(ever_required or schema or semantic)
    repaired_on = bool(ever_on or evidence)
    durable, mirror = tighten_continuity_state(ever_on=repaired_on, ever_required=ever_required)
    snapshot = continuity_snapshot_from_persisted(
        ever_on=durable,
        ever_required=mirror,
        payloads=payloads,
    )
    if hybrid_continuity_required(snapshot) and not snapshot.ever_on:
        raise HybridExecutionAbort(
            "continuity_required_not_ready",
            "repair must raise ever_on; evidence cannot be cleared toward OFF",
        )
    return durable, mirror, snapshot


def persist_continuity_marker(
    store: ContinuityStore,
    *,
    session_id: str,
    snapshot: ArtifactContinuitySnapshot,
    prior: HybridSessionDocument | None = None,
    **kwargs: Any,
) -> HybridSessionDocument:
    """Write ever_on=true as the last install step. Failure is failed install."""
    reject_authority_kwargs(kwargs, label="persist_continuity_marker")
    off_state = prior.off_state if prior is not None else empty_off_state(session_id)
    document = HybridSessionDocument(
        schema_version=SESSION_SCHEMA_VERSION_0_2_0,
        off_state=off_state,
        identity=HybridSessionIdentity(ever_on=True, artifact_snapshot=snapshot),
        ever_required=True,
    )
    try:
        payload = serialize_session_document(document)
        store.save(session_id, payload)
    except HybridExecutionAbort:
        raise
    except ConstraintExecutionError as exc:
        raise HybridExecutionAbort("backend_error", f"continuity persist failed: {exc}") from exc
    except OSError as exc:
        raise HybridExecutionAbort("backend_error", f"continuity persist failed: {exc}") from exc
    return document


def persist_success_session(
    store: ContinuityStore,
    *,
    session_id: str,
    document: HybridSessionDocument,
    **kwargs: Any,
) -> None:
    reject_authority_kwargs(kwargs, label="persist_success_session")
    if not document.identity.ever_on:
        raise HybridExecutionAbort(
            "continuity_required_not_ready",
            "success persist cannot clear ever_on",
        )
    try:
        store.save(session_id, serialize_session_document(document))
    except HybridExecutionAbort:
        raise
    except (ConstraintExecutionError, OSError) as exc:
        raise HybridExecutionAbort("backend_error", f"session persist failed: {exc}") from exc


def persist_report_document(
    store: ContinuityStore,
    *,
    session_id: str,
    payload: dict[str, Any],
    **kwargs: Any,
) -> None:
    reject_authority_kwargs(kwargs, label="persist_report_document")
    try:
        store.save(session_id, payload)
    except HybridExecutionAbort:
        raise
    except (ConstraintExecutionError, OSError) as exc:
        raise HybridExecutionAbort("backend_error", f"report persist failed: {exc}") from exc


__all__ = [
    "COMMIT_POINT",
    "ContinuityStore",
    "FailingContinuityStore",
    "FileContinuityStore",
    "empty_off_state",
    "load_session_document",
    "persist_continuity_marker",
    "persist_report_document",
    "persist_success_session",
    "repair_continuity",
]
