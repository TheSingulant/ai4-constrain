"""Fail-closed errors for the public runtime."""

from __future__ import annotations


class ConstraintExecutionError(RuntimeError):
    """A required constraint, evaluator, or runtime step could not execute.

    Callers must treat this as a hard failure. The runtime does not skip
    missing shards, swap in an unregistered evaluator, or fall back to an
    unconstrained completion.
    """
