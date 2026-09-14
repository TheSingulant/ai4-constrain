"""Public shard runtime: ``ai4.constrain.run(...) -> DecisionReport``.

This productizes frozen condition D. It is not a claim that D beat C.
ConstrainedSession is a thin multi-turn wrapper around that same path.
"""

from __future__ import annotations

from src.providers.base import Completion

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import (
    ConstraintExecutionError,
    SemanticExaminerError,
    SemanticFindingsError,
    SemanticFuseError,
)
from ai4.constrain.explain import format_explain, shard_card
from ai4.constrain.report import DecisionReport
from ai4.constrain.governing import GOVERNING_INTEGRATION_VERSION, GoverningIntegration
from ai4.constrain.runtime import EVIDENCE_CLASS, RUNTIME_VERSION, RuntimeConfig
from ai4.constrain.semantic_examiner import (
    assert_hybrid_eligible_distinct_pin,
    observation_prompt_sha256,
    observe_semantic_candidate,
)
from ai4.constrain.semantic_findings import (
    FINDINGS_SCHEMA_VERSION,
    SEMANTIC_EXAMINER_OPERATIONAL,
    bind_semantic_findings,
    claim_fingerprint_v1,
    parse_semantic_findings,
    validate_semantic_findings,
)
from ai4.constrain.semantic_fuse import map_and_fuse_v2, packaged_fuse_v2
from ai4.constrain.semantic_taxonomy import (
    finding_policy_map_sha256,
    finding_registry_sha256,
    load_finding_policy_map_v1,
    load_finding_registry_v1,
)
from ai4.constrain.session import ConstrainedSession

__all__ = [
    "Completion",
    "ConstrainedSession",
    "ConstraintExecutionError",
    "DecisionReport",
    "EVIDENCE_CLASS",
    "FINDINGS_SCHEMA_VERSION",
    "GOVERNING_INTEGRATION_VERSION",
    "GoverningIntegration",
    "RUNTIME_VERSION",
    "RuntimeConfig",
    "SEMANTIC_EXAMINER_OPERATIONAL",
    "SemanticExaminerError",
    "SemanticFindingsError",
    "SemanticFuseError",
    "assert_hybrid_eligible_distinct_pin",
    "bind_semantic_findings",
    "claim_fingerprint_v1",
    "evaluate",
    "finding_policy_map_sha256",
    "finding_registry_sha256",
    "format_explain",
    "load_finding_policy_map_v1",
    "load_finding_registry_v1",
    "map_and_fuse_v2",
    "observation_prompt_sha256",
    "observe_semantic_candidate",
    "packaged_fuse_v2",
    "parse_semantic_findings",
    "run",
    "shard_card",
    "validate_semantic_findings",
]
