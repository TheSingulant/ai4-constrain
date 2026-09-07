"""Dry-run mock demo: accept, revise-then-accept, refuse. No API key."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai4.constrain.session import dry_run_demo


def main() -> None:
    session = dry_run_demo()
    print(f"session={session.session_id} turns={len(session.turns)}")
    for turn in session.turns:
        card = turn.card()
        print(
            f"turn={turn.turn_index} decision={card.decision} "
            f"terminal={card.terminal} revisions={card.revision_rounds} "
            f"veto={card.veto}"
        )


if __name__ == "__main__":
    main()
