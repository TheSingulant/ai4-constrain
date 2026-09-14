"""Fail-closed errors for the public runtime."""

from __future__ import annotations


class ConstraintExecutionError(RuntimeError):
    """A required constraint, evaluator, or runtime step could not execute.

    Callers must treat this as a hard failure. The runtime does not skip
    missing shards, swap in an unregistered evaluator, or fall back to an
    unconstrained completion.
    """


class SemanticFindingsError(ConstraintExecutionError):
    """Examiner findings payload or packaged taxonomy failed closed.

    Findings are evidence about a candidate. They do not define policy,
    routing, thresholds, arbitration, revision, refusal, or terminal
    control. V07-0 only parses, binds, and hashes; it does not execute
    mapping or fusion into ConstraintMiddleware.
    """


class SemanticFuseError(SemanticFindingsError):
    """Packaged mapping or packaged_fuse_v2 failed closed.

    Standalone V07-1 primitive error. Findings remain evidence only.
    This does not authorize examiner-defined scores, routing, or
    production fusion into ConstraintMiddleware / run() / evaluate().
    """


class SemanticExaminerError(SemanticFindingsError):
    """Standalone V07-2 semantic examiner adapter failed closed.

    Observation evidence only. This does not authorize scoring, routing,
    fusion, thresholds, arbitration, revision, refusal, or terminal
    control, and it is not wired into run() / evaluate().
    """
