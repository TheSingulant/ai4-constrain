"""Solana DevNet-only E2E proof for ai4.transaction.

Does not sign. Does not load keys. The user signs in Phantom (or equivalent)
via the printed handoff URI, then pastes the public transaction signature.
"""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ai4.transaction.devnet_e2e import main


if __name__ == "__main__":
    raise SystemExit(main())
