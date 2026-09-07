"""Minimal public-runtime call. Offline mock; no API key."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai4.constrain import run


def main() -> None:
    report = run("Please give a brief, checkable outline of options and limits.")
    print(f"decision={report.decision} terminal={report.terminal}")
    print(f"evaluator={report.versions.evaluator_id} protocol={report.versions.protocol}")
    print(report.final_output)
    print("---")
    print(report.to_json())


if __name__ == "__main__":
    main()
