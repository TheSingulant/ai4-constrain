"""Stage 2D stress-benchmark authoring and infra.

Authoring and offline harness only. No paid held-out execution.
Does not modify Stage 2C sealed artifacts.
"""

from src.stage2d.constants import (
    STAGE2D_CATEGORIES,
    STAGE2D_HELDOUT_N,
    STAGE2D_HELDOUT_SEED,
    STAGE2D_MAX_SPEND_USD,
)

__all__ = [
    "STAGE2D_CATEGORIES",
    "STAGE2D_HELDOUT_N",
    "STAGE2D_HELDOUT_SEED",
    "STAGE2D_MAX_SPEND_USD",
]
