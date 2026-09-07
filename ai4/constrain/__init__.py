"""Public shard runtime: ``ai4.constrain.run(...) -> DecisionReport``.

This productizes frozen condition D. It is not a claim that D beat C.
"""

from __future__ import annotations

from src.providers.base import Completion

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import EVIDENCE_CLASS, RUNTIME_VERSION, RuntimeConfig

__all__ = [
    "Completion",
    "ConstraintExecutionError",
    "DecisionReport",
    "EVIDENCE_CLASS",
    "RUNTIME_VERSION",
    "RuntimeConfig",
    "evaluate",
    "run",
]
