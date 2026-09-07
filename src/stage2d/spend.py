"""Stage 2D live spend gate.

Hard cap is $2.00. Uses the same pre-request reservation pattern as
LiveProvider. Fail closed. No request is sent when the gate fails.
"""

from __future__ import annotations

import os

from src.providers.base import Completion
from src.providers.live import PER_CALL_FLOOR_USD, LiveProvider, LiveSpendError
from src.stage2d.constants import STAGE2D_MAX_SPEND_USD


class Stage2DSpendError(LiveSpendError):
    """Stage 2D paid path refused before any HTTP call."""


def parse_cap(raw: str | None) -> float:
    if raw is None or str(raw).strip() == "":
        raise Stage2DSpendError(
            "Stage 2D paid runs need AI4_MAX_SPEND_USD=2 (hard cap $2.00)."
        )
    try:
        cap = float(raw)
    except ValueError as exc:
        raise Stage2DSpendError(
            "Stage 2D paid runs need a numeric AI4_MAX_SPEND_USD=2 hard cap."
        ) from exc
    if cap <= 0:
        raise Stage2DSpendError(
            "Stage 2D paid runs need AI4_MAX_SPEND_USD=2 (hard cap $2.00)."
        )
    if cap > STAGE2D_MAX_SPEND_USD + 1e-12:
        raise Stage2DSpendError(
            f"Stage 2D hard cap is ${STAGE2D_MAX_SPEND_USD:.2f}. "
            f"AI4_MAX_SPEND_USD={cap} is above the freeze. No request was sent."
        )
    return cap


def assert_stage2d_live_allowed(
    env: dict[str, str] | None = None,
) -> float:
    """Fail closed before constructing a live client."""
    lookup = env if env is not None else os.environ
    if lookup.get("AI4_ENABLE_LIVE_LLM", "0") != "1":
        raise Stage2DSpendError(
            "Stage 2D live LLM is disabled. Set AI4_ENABLE_LIVE_LLM=1 only after the $2 cap."
        )
    return parse_cap(lookup.get("AI4_MAX_SPEND_USD"))


class Stage2DLiveGuard:
    """Wrap LiveProvider and re-check the $2 cap before every call.

    Reservation math is the same conservative floor used by LiveProvider.
    This wrapper never calls urlopen itself.
    """

    name = "stage2d-live-guard"

    def __init__(self, provider: LiveProvider | None = None) -> None:
        self.cap = assert_stage2d_live_allowed()
        self.provider = provider or LiveProvider()

    @property
    def spent_usd(self) -> float:
        return float(getattr(self.provider, "spent_usd", 0.0))

    def _preflight(self, messages: list[dict[str, str]]) -> None:
        cap = assert_stage2d_live_allowed()
        if cap > STAGE2D_MAX_SPEND_USD + 1e-12:
            raise Stage2DSpendError(
                f"Stage 2D hard cap is ${STAGE2D_MAX_SPEND_USD:.2f}. No request was sent."
            )
        remaining = cap - self.spent_usd
        reservation = self.provider._reservation_usd(messages)
        if remaining < reservation:
            raise Stage2DSpendError(
                f"Stage 2D remaining budget {remaining:.6f} USD is below the "
                f"conservative per-call reservation ({reservation:.6f} USD). "
                "No request was sent."
            )
        if remaining < PER_CALL_FLOOR_USD:
            raise Stage2DSpendError(
                f"Stage 2D remaining budget {remaining:.6f} USD is below "
                f"PER_CALL_FLOOR_USD={PER_CALL_FLOOR_USD}. No request was sent."
            )

    def complete(self, *, system: str, user: str) -> Completion:
        self._preflight(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        return self.provider.complete(system=system, user=user)

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        self._preflight(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": draft},
                {"role": "user", "content": f"Revise using this feedback:\n{feedback}"},
            ]
        )
        return self.provider.revise(system=system, user=user, draft=draft, feedback=feedback)
