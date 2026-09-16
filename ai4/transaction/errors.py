"""Fail-closed errors for the transaction-control scaffold."""

from __future__ import annotations


class TransactionControlError(Exception):
    """A required transaction-control step could not complete safely."""

    def __init__(self, message: str, *, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        if isinstance(reasons, str):
            reasons = (reasons,)
        self.reasons = tuple(reasons) if reasons else (message,)


class TransactionValidationError(TransactionControlError):
    """Deterministic validation failed. Treat as DENY."""
