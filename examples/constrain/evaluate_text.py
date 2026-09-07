"""Score existing text with frozen v0.1 shards. No model calls."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai4.constrain import evaluate


def main() -> None:
    clean = evaluate(
        "Here is a brief, checkable answer: I can outline options and limits, "
        "and I will mark anything I cannot verify."
    )
    leaking = evaluate("Jane Doe lives at 123 Main Street. SSN 078-05-1120.")
    print(f"clean:    decision={clean.decision} veto={clean.arbitration.veto}")
    print(f"leaking:  decision={leaking.decision} targets={leaking.arbitration.revision_targets}")
    for shard in leaking.shard_evaluations:
        if not shard.passed:
            print(f"  {shard.shard_id}: {shard.verdict} {list(shard.reasons)}")


if __name__ == "__main__":
    main()
