"""On-chain token feedback is excluded from v0.1."""

from pathlib import Path

from src.metrics import usefulness_proxy


def test_token_integration_not_in_v0_1():
    root = Path(__file__).resolve().parents[1] / "src" / "token_integration"
    text = (root / "onchain_listener.py").read_text(encoding="utf-8").lower()
    assert "out of scope" in text


def test_cost_hooks_exist_on_usefulness_proxy():
    assert usefulness_proxy("why citations", "") == 0.0
    assert 0.0 < usefulness_proxy("why citations need a source", "Citations need a real source you can check.") <= 1.0
