"""Provider protocol and shared completion record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    estimated_usd: float = 0.0
    model: str = "mock"
    metadata: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    """Minimal complete-or-revise interface used by the agent."""

    name: str

    def complete(self, *, system: str, user: str) -> Completion:
        """Return a first-pass completion."""

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        """Return a revision of draft given feedback."""
