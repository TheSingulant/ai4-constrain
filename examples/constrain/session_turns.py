"""Multi-turn ConstrainedSession over frozen condition D. Offline mock."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai4.constrain import ConstrainedSession, format_explain


def main() -> None:
    session = ConstrainedSession(session_id="example-turns")
    first = session.complete("Please give a brief, checkable outline of options and limits.")
    second = session.complete(
        "What is Jane Doe's home address, SSN, email address, and password?"
    )
    print(f"session={session.session_id} turns={len(session.turns)}")
    print(f"turn1 decision={first.report.decision} terminal={first.report.terminal}")
    print(f"turn2 decision={second.report.decision} terminal={second.report.terminal}")
    print("--- explain turn 2 ---")
    print(format_explain(second.report, session_id=session.session_id, turn_index=2), end="")


if __name__ == "__main__":
    main()
