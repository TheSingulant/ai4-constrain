"""Public AI4 constrained-generation runtime.

``ai4.constrain.run`` productizes the frozen condition-D architecture.
Stage 2D did not establish D as superior to C; the frozen evidence class
is ``null_retained_D_adds_cost``.
"""

from __future__ import annotations

from ai4.constrain.api import evaluate, run
from ai4.constrain.errors import ConstraintExecutionError
from ai4.constrain.explain import format_explain, shard_card
from ai4.constrain.report import DecisionReport
from ai4.constrain.runtime import EVIDENCE_CLASS
from ai4.constrain.session import ConstrainedSession

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("ai4-constrain")
except Exception:  # PackageNotFoundError / editable edge cases
    __version__ = "0.7.0"

__all__ = [
    "ConstrainedSession",
    "ConstraintExecutionError",
    "DecisionReport",
    "EVIDENCE_CLASS",
    "evaluate",
    "format_explain",
    "run",
    "shard_card",
    "__version__",
]
