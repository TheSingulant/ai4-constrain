"""Shared agent types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from src.providers.base import Completion
from src.shards.models import Evaluation


class TerminalState(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    REFUSE = "refuse"
    TIMEOUT = "timeout"
    REPEATED = "repeated"


@dataclass(frozen=True)
class AgentConfig:
    max_revision_rounds: int = 2
    timeout_s: float = 30.0
    max_completions: int = 3
    condition: str = "D"


@dataclass
class RunResult:
    text: str
    state: TerminalState
    condition: str
    evaluation: Evaluation | None
    completions: list[Completion] = field(default_factory=list)
    revision_rounds_used: int = 0
    reason: str = ""
    specified_shards: tuple[str, ...] = ()
    prompt_id: str = ""
    failed_evaluation: Evaluation | None = None

    @property
    def model_calls(self) -> int:
        return len(self.completions)

    @property
    def prompt_tokens(self) -> int:
        return sum(item.prompt_tokens for item in self.completions)

    @property
    def completion_tokens(self) -> int:
        return sum(item.completion_tokens for item in self.completions)

    @property
    def latency_ms(self) -> float:
        return sum(item.latency_ms for item in self.completions)

    @property
    def estimated_usd(self) -> float:
        return sum(item.estimated_usd for item in self.completions)


class Agent(Protocol):
    def run(self, prompt: str, *, prompt_id: str = "", specified_shards: tuple[str, ...] = ()) -> RunResult:
        """Propose text and apply the condition's controller."""
