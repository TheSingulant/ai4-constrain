"""Closed internal HybridExecutionAbort (V07-3A §1).

This exception carries a versioned abort_class vocabulary only. It has no
terminal decision, passed bit, threshold, arbitration, or other governing
authority. Raising it does not accept, revise, or refuse a candidate.
"""

from __future__ import annotations

from typing import Any

HYBRID_ABORT_VOCABULARY_VERSION = "v07.3a.1"

HYBRID_ABORT_CLASSES = (
    "already_expired_deadline",
    "wall_deadline_exhausted",
    "spend_reservation_rejection",
    "proposal_completion_exhausted",
    "examiner_call_exhaustion",
    "backend_error",
    "schema_invalid",
    "empty_parse",
    "injection_suspected",
    "caller_config_pin_forbidden",
    "provenance_mismatch",
    "origin_allowlist_failure",
    "served_model_mismatch",
    "account_session_mismatch",
    "observation_prompt_hash_mismatch",
    "registry_hash_mismatch",
    "policy_map_hash_mismatch",
    "fuse_failure",
    "identity_drift",
    "continuity_required_not_ready",
)

# Fields this primitive must never carry as governing authority.
_FORBIDDEN_ABORT_AUTHORITY_FIELDS = frozenset(
    {
        "action",
        "arbitration",
        "decision",
        "passed",
        "terminal",
        "threshold",
        "verdict",
    }
)


class HybridExecutionAbort(Exception):
    """Closed internal abort. Not a DecisionReport outcome.

    ``abort_class`` must be a member of the closed vocabulary
    ``HYBRID_ABORT_CLASSES``. Extra authority-bearing kwargs fail closed
    rather than becoming a terminal decision.
    """

    vocabulary_version = HYBRID_ABORT_VOCABULARY_VERSION

    def __init__(self, abort_class: str, message: str = "", **kwargs: Any) -> None:
        if abort_class not in HYBRID_ABORT_CLASSES:
            raise ValueError(
                f"Unknown HybridExecutionAbort.abort_class {abort_class!r}; "
                f"closed vocabulary {HYBRID_ABORT_VOCABULARY_VERSION}"
            )
        blocked = sorted(key for key in kwargs if key in _FORBIDDEN_ABORT_AUTHORITY_FIELDS)
        if blocked:
            raise ValueError(
                f"HybridExecutionAbort cannot carry governing field(s) {blocked}"
            )
        if kwargs:
            extra = sorted(str(key) for key in kwargs)
            raise ValueError(f"Unknown HybridExecutionAbort argument(s) {extra}")
        if not isinstance(message, str):
            raise ValueError("HybridExecutionAbort message must be a string")
        self.abort_class = abort_class
        self.message = message
        super().__init__(f"{abort_class}: {message}" if message else abort_class)

    def to_audit_dict(self) -> dict[str, str]:
        """Non-governing abort record. No decision/passed/threshold."""
        return {
            "abort_class": self.abort_class,
            "message": self.message,
            "vocabulary_version": self.vocabulary_version,
        }
