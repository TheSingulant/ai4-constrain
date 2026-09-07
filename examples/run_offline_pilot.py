"""Thin wrapper: run the offline A/B/C/D pilot with the mock provider."""

from __future__ import annotations

import json

from src.experiment import run_experiment


def main() -> None:
    print(json.dumps(run_experiment(), indent=2))


if __name__ == "__main__":
    main()
