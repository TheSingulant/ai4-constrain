"""Bounded revision agent (max two revision rounds).

Condition controllers:
  A: one-shot, no extra principles
  B: one-shot with the same five-value principle prefix
  C: Self-Refine-style principle-guided revision control (unified critique, no shard scores)
  D: explicit per-shard scores plus constrained revision
"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.agents.base_agent import AgentConfig, RunResult, TerminalState
from src.constraints.constraint_middleware import SAFE_REFUSAL, ConstraintMiddleware
from src.control_contract import LoopDecision, next_loop_action, parse_c_decision, parse_d_decision
from src.principles import PRINCIPLE_GUIDED_CRITIQUE, PRINCIPLES_SYSTEM, PrincipleCritic
from src.providers.base import LLMProvider
from src.shards.shard_evaluator import ShardEvaluator

VALID_CONDITIONS = frozenset({"A", "B", "C", "D"})

STANDARD_SYSTEM = "Answer the user. Be concise."

# Re-export so tests can quote the exact C critique and B prefix.
__all__ = [
    "ConstrainedAgent",
    "PRINCIPLE_GUIDED_CRITIQUE",
    "PRINCIPLES_SYSTEM",
    "STANDARD_SYSTEM",
]


class ConstrainedAgent:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        evaluator: ShardEvaluator | None = None,
        middleware: ConstraintMiddleware | None = None,
        critic: PrincipleCritic | None = None,
        config: AgentConfig | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.provider = provider
        self.evaluator = evaluator or ShardEvaluator()
        self.critic = critic or PrincipleCritic()
        self.config = config or AgentConfig()
        self.middleware = middleware or ConstraintMiddleware(max_revision_rounds=self.config.max_revision_rounds)
        self._now = now or time.monotonic

    def run(
        self,
        prompt: str,
        *,
        prompt_id: str = "",
        specified_shards: tuple[str, ...] = (),
    ) -> RunResult:
        condition = self.config.condition.upper()
        if condition not in VALID_CONDITIONS:
            raise ValueError(f"Unsupported condition {condition!r}. Expected A, B, C, or D.")
        deadline = self._now() + self.config.timeout_s
        system = PRINCIPLES_SYSTEM if condition == "B" else STANDARD_SYSTEM
        completions: list = []

        def timed_out() -> bool:
            return self._now() >= deadline

        def budget_left() -> bool:
            return len(completions) < self.config.max_completions

        def finish(
            text: str,
            state: TerminalState,
            reason: str,
            revision_rounds_used: int,
            evaluation=None,
            failed_evaluation=None,
        ) -> RunResult:
            scored = evaluation if evaluation is not None else self.evaluator.evaluate(text)
            return RunResult(
                text=text,
                state=state,
                condition=condition,
                evaluation=scored,
                completions=completions,
                revision_rounds_used=revision_rounds_used,
                reason=reason,
                specified_shards=specified_shards,
                prompt_id=prompt_id,
                failed_evaluation=failed_evaluation,
            )

        if timed_out() or not budget_left():
            return finish("", TerminalState.TIMEOUT, "timeout before first completion", 0)

        first = self.provider.complete(system=system, user=prompt)
        completions.append(first)
        current = first.text

        if condition in {"A", "B"}:
            return finish(current, TerminalState.ACCEPT, "one-shot emit", 0)

        if condition in {"C", "D"}:
            used = 0
            last_reason = ""
            last_evaluation = None
            while True:
                decision, last_evaluation = self._loop_decision(
                    condition, current, used, timed_out()
                )
                last_reason = decision.reason
                step = next_loop_action(
                    decision,
                    revision_rounds_used=used,
                    max_revision_rounds=self.config.max_revision_rounds,
                    budget_left=budget_left(),
                    timed_out=timed_out(),
                )
                if step == "timeout":
                    reason = decision.reason if decision.action == "timeout" else last_reason
                    if not budget_left() and decision.action == "revise":
                        reason = "completion budget exhausted"
                    return finish(current, TerminalState.TIMEOUT, reason, used, last_evaluation)
                if step == "accept":
                    return finish(current, TerminalState.ACCEPT, decision.reason, used, last_evaluation)
                if step == "refuse":
                    return finish(
                        SAFE_REFUSAL,
                        TerminalState.REFUSE,
                        decision.reason,
                        used,
                        failed_evaluation=last_evaluation,
                    )
                if step == "revise_call":
                    revised = self.provider.revise(
                        system=system,
                        user=prompt,
                        draft=current,
                        feedback=decision.feedback,
                    )
                    completions.append(revised)
                    used += 1
                    if revised.text == current:
                        return finish(
                            current,
                            TerminalState.REPEATED,
                            "repeated candidate",
                            used,
                            last_evaluation,
                        )
                    current = revised.text
                    continue
                return finish(current, TerminalState.REVISE, last_reason, used, last_evaluation)

        raise ValueError(f"Unsupported condition {condition!r}. Expected A, B, C, or D.")

    def _loop_decision(
        self,
        condition: str,
        text: str,
        used: int,
        timed_out: bool,
    ) -> tuple[LoopDecision, object]:
        """Condition-specific parsers only. The caller loop is shared."""
        if condition == "C":
            if timed_out:
                return (
                    LoopDecision("timeout", "", "timeout during self-refine", False),
                    None,
                )
            return parse_c_decision(self.critic.critique(text)), None
        evaluation = self.evaluator.evaluate(text)
        raw = self.middleware.decide(
            evaluation,
            revision_round=used,
            timed_out=timed_out,
            budget_exhausted=False,
        )
        feedback = ""
        if raw.action == "revise":
            feedback = self.middleware.format_feedback(raw, evaluation)
        return parse_d_decision(action=raw.action, reason=raw.reason, feedback=feedback), evaluation
