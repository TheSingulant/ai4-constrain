"""Shared fail-closed helpers for inert V07-3A primitives."""

from __future__ import annotations

import math
from typing import Any, Mapping

from ai4.constrain._v07_3a.abort import HybridExecutionAbort

# Kwargs that would smuggle policy, control, install, or activation.
_AUTHORITY_BOUNDARY_KEYS = frozenset(
    {
        "accept",
        "action",
        "arbitration",
        "decision",
        "enable",
        "enabled",
        "evaluator",
        "fusion",
        "hybrid",
        "hybrid_enable",
        "hybrid_enabled",
        "install",
        "install_hybrid",
        "overlay",
        "passed",
        "penalties",
        "policy_map",
        "ready",
        "refuse",
        "registry",
        "revise",
        "terminal",
        "threshold",
        "thresholds",
        "verdict",
        "weights",
    }
)


def reject_authority_kwargs(kwargs: Mapping[str, Any], *, label: str) -> None:
    if not kwargs:
        return
    smuggled = sorted(str(key) for key in kwargs if key in _AUTHORITY_BOUNDARY_KEYS)
    if smuggled:
        raise HybridExecutionAbort(
            "caller_config_pin_forbidden",
            f"{label} supplies policy/control/install field(s) {smuggled}",
        )
    extra = sorted(str(key) for key in kwargs)
    raise HybridExecutionAbort(
        "schema_invalid",
        f"Unknown {label} argument(s) {extra}",
    )


def require_finite_number(raw: object, *, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise HybridExecutionAbort("schema_invalid", f"{field} must be a finite number")
    number = float(raw)
    if not math.isfinite(number):
        raise HybridExecutionAbort("schema_invalid", f"{field} must be a finite number; got {number!r}")
    return number


def require_nonnegative(value: float, *, field: str) -> float:
    if value < 0:
        raise HybridExecutionAbort("schema_invalid", f"{field} must be nonnegative")
    return value


def require_bool(raw: object, *, field: str) -> bool:
    if not isinstance(raw, bool):
        raise HybridExecutionAbort("schema_invalid", f"{field} must be a bool")
    return raw


def require_str(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise HybridExecutionAbort("schema_invalid", f"{field} must be a non-empty string")
    return raw
