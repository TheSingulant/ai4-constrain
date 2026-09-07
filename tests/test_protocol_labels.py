from src.agents.base_agent import TerminalState
from src.protocol_labels import FROZEN_TERMINAL_LABELS, frozen_terminal_label


def test_frozen_label_mapping():
    assert frozen_terminal_label(TerminalState.ACCEPT, "one-shot emit") == "accepted"
    assert frozen_terminal_label(TerminalState.REVISE, "soft shard still failing") == "revision_exhausted"
    assert frozen_terminal_label(TerminalState.REFUSE, "hard shard still failing") == "refused"
    assert frozen_terminal_label(TerminalState.TIMEOUT, "timeout during self-refine") == "timed_out"
    assert frozen_terminal_label(TerminalState.TIMEOUT, "completion budget exhausted") == "budget_exhausted"
    assert frozen_terminal_label(TerminalState.REPEATED, "repeated candidate") == "repeated_candidate"
    assert set(FROZEN_TERMINAL_LABELS) == {
        "accepted",
        "revision_exhausted",
        "refused",
        "timed_out",
        "budget_exhausted",
        "repeated_candidate",
    }
