"""Fail-closed errors for the transaction-control scaffold."""

from __future__ import annotations


class TransactionControlError(Exception):
    """A required transaction-control step could not complete safely."""

    def __init__(self, message: str, *, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reasons = reasons or (message,)


class TransactionValidationError(TransactionControlError):
    """Deterministic validation failed. Treat as DENY."""
