"""Public AI4 constrained-generation runtime.

``ai4.constrain.run`` productizes the frozen condition-D architecture.
Stage 2D did not establish D as superior to C; the frozen evidence class
is ``null_retained_D_adds_cost``.
"""

from __future__ import annotations

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import EVIDENCE_CLASS

__version__ = "0.1.0"

__all__ = [
    "ConstraintExecutionError",
    "DecisionReport",
    "EVIDENCE_CLASS",
    "evaluate",
    "run",
    "__version__",
]
