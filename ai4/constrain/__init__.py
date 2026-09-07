"""Public shard runtime: ``ai4.constrain.run(...) -> DecisionReport``.

This productizes frozen condition D. It is not a claim that D beat C.
ConstrainedSession is a thin multi-turn wrapper around that same path.
"""

from __future__ import annotations

from src.providers.base import Completion

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.explain import format_explain, shard_card
from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import EVIDENCE_CLASS, RUNTIME_VERSION, RuntimeConfig
from ai4.constrain.session import ConstrainedSession

__all__ = [
    "Completion",
    "ConstrainedSession",
    "ConstraintExecutionError",
    "DecisionReport",
    "EVIDENCE_CLASS",
    "RUNTIME_VERSION",
    "RuntimeConfig",
    "evaluate",
    "format_explain",
    "run",
    "shard_card",
]
