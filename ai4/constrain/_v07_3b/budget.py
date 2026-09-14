"""Shared budget integration surface (V07-3B §5).

Wrappers around the approved V07-3A ``RunBudgetAuthority``. Proposal and
examiner lanes keep separate counts; USD and wall-clock are shared;
``commit(actual_usd)`` records honest spend.

When a ``RunBudgetAuthority`` is bound, unknown cost is not zero cost.
``estimated_usd`` must be an explicit finite nonnegative number.
Missing, ``None``, NaN, Inf, negative, or malformed values fail closed.
The reservation is released (count lane returned); nothing is committed
as known spend. The reservation amount is never substituted as actual.
Explicit ``0.0`` is valid zero cost.

Provider adapters are inert unless an internal 3B test injects a
``RunBudgetAuthority``. Normal OFF provider behavior is unchanged:
``api.run`` / ``LiveProvider`` do not import this module.
"""

from __future__ import annotations

from typing import Any

from src.providers.base import Completion

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_nonnegative, require_finite_number
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain._v07_3a.budget import (
    KIND_EXAMINER_CALL,
    KIND_PROPOSAL_COMPLETION,
    RunBudgetAuthority,
    RunBudgetReservation,
)


class BudgetAwareProviderAdapter:
    """Optional proposal-lane wrapper. Pass-through when authority is None."""

    def __init__(
        self,
        inner: object,
        *,
        budget_authority: RunBudgetAuthority | None = None,
        reserve_usd: float = 0.0,
        **kwargs: Any,
    ) -> None:
        reject_authority_kwargs(kwargs, label="BudgetAwareProviderAdapter")
        if inner is None:
            raise HybridExecutionAbort("schema_invalid", "inner provider is required")
        self._inner = inner
        self._budget = budget_authority
        self._reserve_usd = require_nonnegative(
            require_finite_number(reserve_usd, field="reserve_usd"),
            field="reserve_usd",
        )
        self.name = getattr(inner, "name", "budget-adapter")

    @property
    def budget_authority(self) -> RunBudgetAuthority | None:
        return self._budget

    def complete(self, *, system: str, user: str) -> Completion:
        return self._call("complete", system=system, user=user)

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        return self._call("revise", system=system, user=user, draft=draft, feedback=feedback)

    def _call(self, method: str, **call_kwargs: Any) -> Completion:
        op = getattr(self._inner, method)
        if self._budget is None:
            return op(**call_kwargs)
        reservation = self._budget.reserve_proposal_completion(usd=self._reserve_usd)
        executing = self._budget.begin_execute(reservation)
        try:
            result = op(**call_kwargs)
        except Exception:
            self._budget.release(executing)
            raise
        try:
            actual = require_known_actual_usd(result)
        except Exception:
            # Provider call completed but cost is unknown. Release the
            # reservation/count lane. Do not commit fictitious zero spend.
            # Actual USD remains unknown and is not booked as known spend.
            self._budget.release(executing)
            raise
        self._budget.commit(executing, actual_usd=actual)
        return result


def require_known_actual_usd(result: object, *, field: str = "estimated_usd") -> float:
    """Explicit finite nonnegative known cost. Unknown is not zero.

    Shared by the proposal adapter and the governing examiner path.
    Attribute absence, ``None``, malformed/non-numeric, NaN, Inf, and
    negative values fail closed. Explicit ``0.0`` is valid known zero.
    No default is substituted for a missing attribute.
    """
    if not hasattr(result, field):
        raise HybridExecutionAbort(
            "schema_invalid",
            f"{field} is required when a budget authority is bound; "
            "unknown cost is not zero and is not booked as known spend",
        )
    raw = getattr(result, field)
    if raw is None:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"{field} is required when a budget authority is bound; "
            "unknown cost is not zero and is not booked as known spend",
        )
    amount = require_finite_number(raw, field=field)
    return require_nonnegative(amount, field=field)


def _require_known_actual_usd(result: object) -> float:
    """Backward-compatible alias for the proposal-path field name."""
    return require_known_actual_usd(result, field="estimated_usd")


def bind_shared_budget(
    *,
    deadline_monotonic: float,
    max_proposal_completions: int,
    max_examiner_calls: int,
    max_usd: float,
    **kwargs: Any,
) -> RunBudgetAuthority:
    reject_authority_kwargs(kwargs, label="bind_shared_budget")
    return RunBudgetAuthority(
        deadline_monotonic=deadline_monotonic,
        max_proposal_completions=max_proposal_completions,
        max_examiner_calls=max_examiner_calls,
        max_usd=max_usd,
    )


def reserve_examiner_lane(
    authority: RunBudgetAuthority,
    *,
    usd: float,
    **kwargs: Any,
) -> RunBudgetReservation:
    reject_authority_kwargs(kwargs, label="reserve_examiner_lane")
    if not isinstance(authority, RunBudgetAuthority):
        raise HybridExecutionAbort("schema_invalid", "shared budget authority is required")
    return authority.reserve_examiner_call(usd=usd)


__all__ = [
    "BudgetAwareProviderAdapter",
    "KIND_EXAMINER_CALL",
    "KIND_PROPOSAL_COMPLETION",
    "bind_shared_budget",
    "require_known_actual_usd",
    "reserve_examiner_lane",
]
