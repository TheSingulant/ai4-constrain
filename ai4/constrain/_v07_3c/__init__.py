"""V07-3C governing hybrid integration (run() only).

This private package is the first and only governing integration slice.
Product activation is ``RuntimeConfig.integration: GoverningIntegration``.
``hybrid_ready`` here may return ``Ready``. 3A/3B stubs remain unchanged.

``evaluate()`` stays deterministic and does not import this package.
"""

from __future__ import annotations

from ai4.constrain._v07_3a.context import NotReady
from ai4.constrain._v07_3c.entry import execute_configured
from ai4.constrain._v07_3c.install import HybridOrchestrator
from ai4.constrain._v07_3c.ready import Ready, ReadyFacts, hybrid_ready

__all__ = [
    "HybridOrchestrator",
    "NotReady",
    "Ready",
    "ReadyFacts",
    "execute_configured",
    "hybrid_ready",
]
