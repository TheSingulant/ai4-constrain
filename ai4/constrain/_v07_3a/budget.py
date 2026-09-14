"""Run-scoped budget/deadline authority (V07-3A §3).

Internal primitive. Proposal completions and examiner calls share one
USD ledger and one wall-clock deadline. Count budgets stay separate.
This module does not modify LiveProvider and is not wired into
``api.run`` / ``api.evaluate``.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ai4.constrain._v07_3a._common import (
    reject_authority_kwargs,
    require_finite_number,
    require_nonnegative,
)
from ai4.constrain._v07_3a.abort import HybridExecutionAbort

ReservationKind = str

KIND_PROPOSAL_COMPLETION = "proposal_completion"
KIND_EXAMINER_CALL = "examiner_call"
_KINDS = frozenset({KIND_PROPOSAL_COMPLETION, KIND_EXAMINER_CALL})

STATE_RESERVED = "reserved"
STATE_EXECUTING = "executing"
STATE_COMMITTED = "committed"
STATE_RELEASED = "released"


@dataclass(frozen=True)
class RunBudgetReservation:
    """Handle for one reserved proposal completion or examiner call.

    Not a terminal decision. ``kind`` is a count-budget lane; USD is
    shared across lanes on the parent authority.
    """

    reservation_id: int
    kind: str
    reserved_usd: float
    state: str


class RunBudgetAuthority:
    """In-process, thread-safe run budget.

    Transitions: reserve → execute → commit(actual_usd).
    A reserved or executing handle may also be released (abort).
    Reserve after the deadline fails with ``already_expired_deadline``.
    Execute after the deadline fails with ``wall_deadline_exhausted``.

    ``commit(actual_usd)`` always records incurred spend (Candidate 2
    §I.2). Actual provider spend may exceed the pessimistic reservation
    and is still counted. That overrun of the reservation does not by
    itself invalidate already-incurred external spend. If the honest
    ``_usd_committed`` then exceeds ``max_usd``, the method raises
    ``spend_reservation_rejection`` *after* the ledger update as the
    fail-closed post-call overrun signal (no new abort class; this is
    the existing spend-budget class). The raise does not roll back.
    """

    def __init__(
        self,
        *,
        deadline_monotonic: float,
        max_proposal_completions: int,
        max_examiner_calls: int,
        max_usd: float,
        clock: Callable[[], float] | None = None,
        **kwargs: Any,
    ) -> None:
        reject_authority_kwargs(kwargs, label="RunBudgetAuthority")
        self._deadline = require_finite_number(
            deadline_monotonic, field="deadline_monotonic"
        )
        if not isinstance(max_proposal_completions, int) or isinstance(
            max_proposal_completions, bool
        ):
            raise HybridExecutionAbort(
                "schema_invalid", "max_proposal_completions must be an int"
            )
        if not isinstance(max_examiner_calls, int) or isinstance(max_examiner_calls, bool):
            raise HybridExecutionAbort("schema_invalid", "max_examiner_calls must be an int")
        if max_proposal_completions < 0 or max_examiner_calls < 0:
            raise HybridExecutionAbort("schema_invalid", "count maxima must be nonnegative")
        self._max_proposal = max_proposal_completions
        self._max_examiner = max_examiner_calls
        self._max_usd = require_nonnegative(
            require_finite_number(max_usd, field="max_usd"), field="max_usd"
        )
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._usd_committed = 0.0
        self._usd_reserved = 0.0
        self._proposal_reserved = 0
        self._proposal_committed = 0
        self._examiner_reserved = 0
        self._examiner_committed = 0
        self._reservations: dict[int, RunBudgetReservation] = {}

    @property
    def deadline_monotonic(self) -> float:
        return self._deadline

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "usd_committed": self._usd_committed,
                "usd_reserved": self._usd_reserved,
                "usd_available": self._max_usd - self._usd_committed - self._usd_reserved,
                "proposal_reserved": self._proposal_reserved,
                "proposal_committed": self._proposal_committed,
                "examiner_reserved": self._examiner_reserved,
                "examiner_committed": self._examiner_committed,
                "max_usd": self._max_usd,
                "max_proposal_completions": self._max_proposal,
                "max_examiner_calls": self._max_examiner,
            }

    def reserve_proposal_completion(self, *, usd: float, **kwargs: Any) -> RunBudgetReservation:
        reject_authority_kwargs(kwargs, label="reserve_proposal_completion")
        return self._reserve(KIND_PROPOSAL_COMPLETION, usd)

    def reserve_examiner_call(self, *, usd: float, **kwargs: Any) -> RunBudgetReservation:
        reject_authority_kwargs(kwargs, label="reserve_examiner_call")
        return self._reserve(KIND_EXAMINER_CALL, usd)

    def begin_execute(self, reservation: RunBudgetReservation, **kwargs: Any) -> RunBudgetReservation:
        reject_authority_kwargs(kwargs, label="begin_execute")
        self._require_handle(reservation)
        with self._lock:
            current = self._reservations[reservation.reservation_id]
            if current.state != STATE_RESERVED:
                raise HybridExecutionAbort(
                    "schema_invalid",
                    f"reservation {current.reservation_id} is {current.state}, not reserved",
                )
            if self._clock() >= self._deadline:
                self._release_locked(current)
                raise HybridExecutionAbort(
                    "wall_deadline_exhausted",
                    "wall-clock deadline passed before execute",
                )
            updated = RunBudgetReservation(
                reservation_id=current.reservation_id,
                kind=current.kind,
                reserved_usd=current.reserved_usd,
                state=STATE_EXECUTING,
            )
            self._reservations[current.reservation_id] = updated
            return updated

    def commit(
        self,
        reservation: RunBudgetReservation,
        *,
        actual_usd: float,
        **kwargs: Any,
    ) -> RunBudgetReservation:
        reject_authority_kwargs(kwargs, label="commit")
        self._require_handle(reservation)
        actual = require_nonnegative(
            require_finite_number(actual_usd, field="actual_usd"), field="actual_usd"
        )
        with self._lock:
            current = self._reservations[reservation.reservation_id]
            if current.state != STATE_EXECUTING:
                raise HybridExecutionAbort(
                    "schema_invalid",
                    f"reservation {current.reservation_id} is {current.state}, not executing",
                )
            # Commit path is always: release reserved USD → record actual →
            # release reserved count → increment committed count → terminal
            # committed with actual stored. leftover reserved USD returns to
            # the shared ledger; extra actual above reserved is incurred spend.
            self._usd_reserved -= current.reserved_usd
            self._usd_committed += actual
            if current.kind == KIND_PROPOSAL_COMPLETION:
                self._proposal_reserved -= 1
                self._proposal_committed += 1
            else:
                self._examiner_reserved -= 1
                self._examiner_committed += 1
            updated = RunBudgetReservation(
                reservation_id=current.reservation_id,
                kind=current.kind,
                reserved_usd=actual,
                state=STATE_COMMITTED,
            )
            self._reservations[current.reservation_id] = updated
            if self._usd_committed > self._max_usd:
                raise HybridExecutionAbort(
                    "spend_reservation_rejection",
                    f"actual_usd {actual} committed; usd_committed "
                    f"{self._usd_committed} exceeds max_usd {self._max_usd}",
                )
            return updated

    def release(self, reservation: RunBudgetReservation, **kwargs: Any) -> RunBudgetReservation:
        reject_authority_kwargs(kwargs, label="release")
        self._require_handle(reservation)
        with self._lock:
            current = self._reservations[reservation.reservation_id]
            if current.state in {STATE_COMMITTED, STATE_RELEASED}:
                raise HybridExecutionAbort(
                    "schema_invalid",
                    f"reservation {current.reservation_id} is already {current.state}",
                )
            return self._release_locked(current)

    def _reserve(self, kind: str, usd: float) -> RunBudgetReservation:
        if kind not in _KINDS:
            raise HybridExecutionAbort("schema_invalid", f"unknown reservation kind {kind!r}")
        amount = require_nonnegative(require_finite_number(usd, field="usd"), field="usd")
        with self._lock:
            if self._clock() >= self._deadline:
                raise HybridExecutionAbort(
                    "already_expired_deadline",
                    "no reserve after the wall-clock deadline",
                )
            if kind == KIND_PROPOSAL_COMPLETION:
                in_flight = self._proposal_reserved + self._proposal_committed
                if in_flight >= self._max_proposal:
                    raise HybridExecutionAbort(
                        "proposal_completion_exhausted",
                        "proposal completion count budget exhausted",
                    )
            else:
                in_flight = self._examiner_reserved + self._examiner_committed
                if in_flight >= self._max_examiner:
                    raise HybridExecutionAbort(
                        "examiner_call_exhaustion",
                        "examiner call count budget exhausted",
                    )
            available = self._max_usd - self._usd_committed - self._usd_reserved
            if amount > available:
                raise HybridExecutionAbort(
                    "spend_reservation_rejection",
                    f"USD reservation {amount} exceeds available {available}",
                )
            reservation_id = next(self._ids)
            if kind == KIND_PROPOSAL_COMPLETION:
                self._proposal_reserved += 1
            else:
                self._examiner_reserved += 1
            self._usd_reserved += amount
            handle = RunBudgetReservation(
                reservation_id=reservation_id,
                kind=kind,
                reserved_usd=amount,
                state=STATE_RESERVED,
            )
            self._reservations[reservation_id] = handle
            return handle

    def _release_locked(self, current: RunBudgetReservation) -> RunBudgetReservation:
        if current.state == STATE_RESERVED or current.state == STATE_EXECUTING:
            self._usd_reserved -= current.reserved_usd
            if current.kind == KIND_PROPOSAL_COMPLETION:
                self._proposal_reserved -= 1
            else:
                self._examiner_reserved -= 1
        updated = RunBudgetReservation(
            reservation_id=current.reservation_id,
            kind=current.kind,
            reserved_usd=0.0,
            state=STATE_RELEASED,
        )
        self._reservations[current.reservation_id] = updated
        return updated

    def _require_handle(self, reservation: object) -> None:
        if not isinstance(reservation, RunBudgetReservation):
            raise HybridExecutionAbort("schema_invalid", "reservation handle is invalid")
        with self._lock:
            current = self._reservations.get(reservation.reservation_id)
        if current is None:
            raise HybridExecutionAbort("schema_invalid", "unknown reservation id")
        if current.kind != reservation.kind:
            raise HybridExecutionAbort("identity_drift", "reservation kind mismatch")


__all__ = [
    "KIND_EXAMINER_CALL",
    "KIND_PROPOSAL_COMPLETION",
    "ReservationKind",
    "RunBudgetAuthority",
    "RunBudgetReservation",
]
