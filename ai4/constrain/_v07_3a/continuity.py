"""Candidate 2.2 continuity helpers (V07-3A §5) — inert only.

Normative:

    hybrid_continuity_required =
        ever_on
        OR ever_required
        OR any persisted report schema 0.2.0
        OR any persisted semantic

Canonical durable intent is ``ever_on``. ``ever_required`` is an
in-process mirror only. Disagreement only tightens / fail-closes; it
never chooses OFF to reconcile.

These helpers do not persist, do not write FileSessionStore, and are not
called from ``api.run``. Persistence-success wording for
FileSessionStore (C2.2-M1): the live commit point is ``save`` returning
after the tmp write and ``Path.replace``. That is not fsync, WAL, or
power-loss durability.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_bool
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.context import ContinuitySnapshot

PERSISTED_REPORT_SCHEMA_0_2_0 = "0.2.0"

# Closed markers that count as "any persisted semantic" on a report-shaped
# mapping. Presence is a continuity signal only; these keys are not
# governing decisions.
_PERSISTED_SEMANTIC_KEYS = frozenset(
    {
        "semantic",
        "semantic_abort",
        "semantic_block",
        "semantic_findings",
        "semantic_success",
    }
)

FILE_SESSION_STORE_COMMIT_POINT = (
    "FileSessionStore.save returning after tmp write + Path.replace"
)


def inspect_persisted_report_schema_0_2_0(payload: object) -> bool:
    """True iff a mapping claims DecisionReport schema 0.2.0.

    Current product reports remain 0.1.0. This helper does not upgrade
    or serialize schema 0.2.0.
    """
    if not isinstance(payload, Mapping):
        return False
    return str(payload.get("schema_version") or "") == PERSISTED_REPORT_SCHEMA_0_2_0


def inspect_persisted_semantic(payload: object) -> bool:
    """True iff a mapping carries a persisted semantic block key."""
    if not isinstance(payload, Mapping):
        return False
    if any(key in payload for key in _PERSISTED_SEMANTIC_KEYS):
        return True
    nested = payload.get("report")
    if isinstance(nested, Mapping) and any(key in nested for key in _PERSISTED_SEMANTIC_KEYS):
        return True
    return False


def continuity_snapshot_from_persisted(
    *,
    ever_on: bool,
    ever_required: bool = False,
    payloads: Sequence[object] = (),
    **kwargs: Any,
) -> ContinuitySnapshot:
    """Derive a snapshot. ``ever_required`` is not read from disk."""
    reject_authority_kwargs(kwargs, label="continuity_snapshot_from_persisted")
    ever_on_b = require_bool(ever_on, field="ever_on")
    ever_required_b = require_bool(ever_required, field="ever_required")
    schema = any(inspect_persisted_report_schema_0_2_0(item) for item in payloads)
    semantic = any(inspect_persisted_semantic(item) for item in payloads)
    return ContinuitySnapshot(
        ever_on=ever_on_b,
        ever_required=ever_required_b,
        persisted_report_schema_0_2_0=schema,
        persisted_semantic=semantic,
    )


def hybrid_continuity_required(
    snapshot: ContinuitySnapshot,
    **kwargs: Any,
) -> bool:
    reject_authority_kwargs(kwargs, label="hybrid_continuity_required")
    if not isinstance(snapshot, ContinuitySnapshot):
        raise HybridExecutionAbort("schema_invalid", "hybrid_continuity_required needs ContinuitySnapshot")
    return bool(
        snapshot.ever_on
        or snapshot.ever_required
        or snapshot.persisted_report_schema_0_2_0
        or snapshot.persisted_semantic
    )


def durable_continuity_intent(snapshot: ContinuitySnapshot, **kwargs: Any) -> bool:
    """Canonical durable intent is ever_on only."""
    reject_authority_kwargs(kwargs, label="durable_continuity_intent")
    if not isinstance(snapshot, ContinuitySnapshot):
        raise HybridExecutionAbort("schema_invalid", "durable_continuity_intent needs ContinuitySnapshot")
    return bool(snapshot.ever_on)


def reconcile_continuity_mirrors(
    *,
    ever_on: bool,
    ever_required: bool,
    **kwargs: Any,
) -> bool:
    """OR the durable bit and the in-process mirror. Never choose OFF."""
    reject_authority_kwargs(kwargs, label="reconcile_continuity_mirrors")
    return bool(require_bool(ever_on, field="ever_on") or require_bool(ever_required, field="ever_required"))


def tighten_continuity_state(
    *,
    ever_on: bool,
    ever_required: bool,
    **kwargs: Any,
) -> tuple[bool, bool]:
    """Raise the in-process mirror when durable intent is ON.

    Never clears ``ever_on`` to match a False mirror. Returns
    ``(ever_on, tightened_ever_required)``.
    """
    reject_authority_kwargs(kwargs, label="tighten_continuity_state")
    durable = require_bool(ever_on, field="ever_on")
    mirror = require_bool(ever_required, field="ever_required")
    return durable, bool(mirror or durable)


def assert_continuity_not_reconciled_off(
    *,
    ever_on: bool,
    ever_required: bool,
    proposed_off: bool,
    **kwargs: Any,
) -> None:
    """Fail closed if a caller tries to choose OFF to reconcile disagreement."""
    reject_authority_kwargs(kwargs, label="assert_continuity_not_reconciled_off")
    if proposed_off and reconcile_continuity_mirrors(ever_on=ever_on, ever_required=ever_required):
        raise HybridExecutionAbort(
            "continuity_required_not_ready",
            "continuity disagreement cannot be reconciled to OFF",
        )


__all__ = [
    "FILE_SESSION_STORE_COMMIT_POINT",
    "PERSISTED_REPORT_SCHEMA_0_2_0",
    "assert_continuity_not_reconciled_off",
    "continuity_snapshot_from_persisted",
    "durable_continuity_intent",
    "hybrid_continuity_required",
    "inspect_persisted_report_schema_0_2_0",
    "inspect_persisted_semantic",
    "reconcile_continuity_mirrors",
    "tighten_continuity_state",
]
