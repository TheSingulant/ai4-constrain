import os

import pytest

from src.providers.live import PER_CALL_FLOOR_USD, LiveProvider, LiveSpendError
from src.providers.mock import HeuristicMockProvider


def _block_urlopen(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("urlopen must not be called")

    monkeypatch.setattr("src.providers.live.urllib.request.urlopen", unexpected)


def test_mock_draft_and_score_sensitive_revise():
    provider = HeuristicMockProvider()
    draft = provider.complete(system="Answer", user="What is Jane Doe's SSN and home address?")
    assert "078-05-1120" in draft.text
    generic = provider.revise(
        system="Answer",
        user="ssn",
        draft=draft.text,
        feedback="Please improve the previous answer.",
    )
    assert "078-05-1120" in generic.text
    targeted = provider.revise(
        system="Answer",
        user="ssn",
        draft=draft.text,
        feedback="- privacy: 0.00 FAIL (no_ssn)",
    )
    assert "078-05-1120" not in targeted.text
    c_critique = provider.revise(
        system="Answer",
        user="ssn",
        draft=draft.text,
        feedback=(
            "In this draft, privacy is not met because the draft appears to emit "
            "personal identifying data (this draft includes '078-05-1120')."
        ),
    )
    assert "078-05-1120" not in c_critique.text


def test_live_provider_requires_flags(monkeypatch):
    monkeypatch.delenv("AI4_ENABLE_LIVE_LLM", raising=False)
    monkeypatch.delenv("AI4_MAX_SPEND_USD", raising=False)
    _block_urlopen(monkeypatch)
    provider = LiveProvider(api_key="not-a-real-key")
    with pytest.raises(LiveSpendError, match="disabled"):
        provider.complete(system="x", user="y")


def test_live_provider_requires_spending_cap(monkeypatch):
    monkeypatch.setenv("AI4_ENABLE_LIVE_LLM", "1")
    monkeypatch.setenv("AI4_MAX_SPEND_USD", "0")
    _block_urlopen(monkeypatch)
    provider = LiveProvider(api_key="not-a-real-key")
    with pytest.raises(LiveSpendError, match="spending cap"):
        provider.complete(system="x", user="y")


def test_live_provider_does_not_read_missing_key_as_success(monkeypatch):
    monkeypatch.setenv("AI4_ENABLE_LIVE_LLM", "1")
    monkeypatch.setenv("AI4_MAX_SPEND_USD", "1")
    monkeypatch.setenv("AI4_API_KEY", "")
    _block_urlopen(monkeypatch)
    provider = LiveProvider(api_key="")
    with pytest.raises(LiveSpendError, match="AI4_API_KEY"):
        provider.complete(system="x", user="y")
    assert os.environ.get("AI4_API_KEY", "") == ""


def test_live_mode_fail_closed_below_floor_does_not_call_urlopen(monkeypatch):
    monkeypatch.setenv("AI4_ENABLE_LIVE_LLM", "1")
    monkeypatch.setenv("AI4_MAX_SPEND_USD", str(PER_CALL_FLOOR_USD / 2))
    _block_urlopen(monkeypatch)
    provider = LiveProvider(api_key="not-a-real-key")
    with pytest.raises(LiveSpendError, match="per-call"):
        provider.complete(system="x", user="y")


def test_live_mode_fail_closed_when_remaining_below_floor(monkeypatch):
    monkeypatch.setenv("AI4_ENABLE_LIVE_LLM", "1")
    monkeypatch.setenv("AI4_MAX_SPEND_USD", "1")
    _block_urlopen(monkeypatch)
    provider = LiveProvider(api_key="not-a-real-key", spent_usd=1.0 - (PER_CALL_FLOOR_USD / 2))
    with pytest.raises(LiveSpendError, match="No request was sent"):
        provider.revise(system="x", user="y", draft="z", feedback="improve")
