"""Closed hybrid revision feedback templates (V07-3B §8).

Feedback is template-only. Inputs are closed class IDs, observation
codes, and allowlisted product templates / safe enums. Examiner
freeform, candidate quotes, span text, fingerprints, raw regex notes,
and arbitrary result blobs are rejected.

This registry is **not** wired into ``ConstraintMiddleware.format_feedback``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ai4.constrain._v07_3a._common import reject_authority_kwargs, require_str
from ai4.constrain._v07_3a.abort import HybridExecutionAbort
from ai4.constrain.semantic_taxonomy import load_finding_registry_v1

FEEDBACK_TEMPLATE_REGISTRY_VERSION = "ai4.hybrid_feedback.v0.7-3b"

# Safe enum of product-owned template ids. Values are the emitted text.
FEEDBACK_TEMPLATES: dict[tuple[str, str], str] = {
    ("deceptive_claim", "deceptive_framing_cue"): (
        "Revise so each claim keeps an honest evidential status."
    ),
    ("fabricated_authority", "invented_citation_cue"): (
        "Revise to remove unsupported citations or authority references."
    ),
    ("fabricated_authority", "invented_credential_cue"): (
        "Revise to remove unsupported credentials or institutional mandates."
    ),
    ("fabricated_authority", "ungrounded_authority_cue"): (
        "Revise so authority claims are limited to what the text supports."
    ),
    ("governance_manipulation_claim", "governance_override_cue"): (
        "Revise to remove claims that the assistant may set or override policy."
    ),
    ("overclaim_from_ambiguity", "ambiguity_as_fact_cue"): (
        "Revise so underspecified content is not restated as a settled fact."
    ),
    ("unsupported_certainty", "numeric_precision_without_support"): (
        "Revise to drop precise quantities that the text does not support."
    ),
    ("unsupported_certainty", "ungrounded_certainty_cue"): (
        "Revise so certainty matches the evidence actually given."
    ),
}

_INJECTION_KEYS = frozenset(
    {
        "candidate",
        "comment",
        "comments",
        "detail",
        "evidence",
        "explanation",
        "feedback",
        "fingerprint",
        "freeform",
        "message",
        "note",
        "notes",
        "quote",
        "quote_sha256",
        "raw",
        "regex",
        "result",
        "results",
        "span",
        "text",
    }
)


def _closed_ids() -> tuple[frozenset[str], frozenset[str]]:
    registry = load_finding_registry_v1()
    return registry.class_id_set(), registry.observation_code_set()


def lookup_feedback_template(
    class_id: str,
    observation_code: str,
    **kwargs: Any,
) -> str:
    reject_authority_kwargs(kwargs, label="lookup_feedback_template")
    cid = require_str(class_id, field="class_id")
    code = require_str(observation_code, field="observation_code")
    class_ids, observation_codes = _closed_ids()
    if cid not in class_ids:
        raise HybridExecutionAbort("schema_invalid", f"unknown class_id {cid!r}")
    if code not in observation_codes:
        raise HybridExecutionAbort("schema_invalid", f"unknown observation_code {code!r}")
    template = FEEDBACK_TEMPLATES.get((cid, code))
    if template is None:
        raise HybridExecutionAbort(
            "schema_invalid",
            f"no allowlisted template for ({cid!r}, {code!r})",
        )
    return template


def format_hybrid_revision_feedback(
    pairs: Iterable[tuple[str, str]],
    **kwargs: Any,
) -> str:
    """Join closed templates. Extra kwargs fail closed (injection test)."""
    if kwargs:
        injected = sorted(str(key) for key in kwargs if key in _INJECTION_KEYS)
        if injected:
            raise HybridExecutionAbort(
                "injection_suspected",
                f"feedback template rejected injected field(s) {injected}",
            )
        reject_authority_kwargs(kwargs, label="format_hybrid_revision_feedback")
    items = list(pairs)
    if not items:
        raise HybridExecutionAbort("schema_invalid", "feedback requires at least one closed pair")
    lines = ["Hybrid revision guidance (template-only):"]
    seen: set[tuple[str, str]] = set()
    for pair in items:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise HybridExecutionAbort("schema_invalid", "feedback pairs must be (class_id, observation_code)")
        key = (str(pair[0]), str(pair[1]))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {lookup_feedback_template(key[0], key[1])}")
    return "\n".join(lines)


def reject_injected_feedback_payload(payload: Mapping[str, Any], **kwargs: Any) -> None:
    reject_authority_kwargs(kwargs, label="reject_injected_feedback_payload")
    injected = sorted(str(key) for key in payload if key in _INJECTION_KEYS)
    if injected:
        raise HybridExecutionAbort(
            "injection_suspected",
            f"feedback payload rejected injected field(s) {injected}",
        )


__all__ = [
    "FEEDBACK_TEMPLATES",
    "FEEDBACK_TEMPLATE_REGISTRY_VERSION",
    "format_hybrid_revision_feedback",
    "lookup_feedback_template",
    "reject_injected_feedback_payload",
]
