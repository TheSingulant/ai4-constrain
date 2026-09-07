"""Map v0.1 runtime terminals onto the frozen benchmark labels.

Runtime keeps the existing accept/revise/refuse/timeout enum so current
controllers stay stable. The frozen protocol names the same outcomes more
explicitly, and adds repeated-candidate as a first-class terminal.
"""

from __future__ import annotations

from src.agents.base_agent import TerminalState

# Frozen protocol labels (Nathan freeze). Runtime values are on the left.
FROZEN_TERMINAL_LABELS = (
    "accepted",
    "revision_exhausted",
    "refused",
    "timed_out",
    "budget_exhausted",
    "repeated_candidate",
)

_STATE_TO_FROZEN = {
    TerminalState.ACCEPT: "accepted",
    TerminalState.REVISE: "revision_exhausted",
    TerminalState.REFUSE: "refused",
    TerminalState.REPEATED: "repeated_candidate",
}


def frozen_terminal_label(state: TerminalState, reason: str = "") -> str:
    """Return the frozen protocol label for a runtime terminal.

    Wall-clock timeout and completion-budget exhaustion both use runtime
    ``timeout``. The reason string distinguishes ``budget_exhausted`` from
    ``timed_out``.
    """
    if state is TerminalState.TIMEOUT:
        if "budget" in (reason or "").lower():
            return "budget_exhausted"
        return "timed_out"
    try:
        return _STATE_TO_FROZEN[state]
    except KeyError as exc:
        raise ValueError(f"Unknown runtime terminal {state!r}.") from exc
