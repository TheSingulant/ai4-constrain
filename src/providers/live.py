"""Optional OpenAI-compatible live path. Disabled unless env flags allow it."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from src.providers.base import Completion


class LiveSpendError(RuntimeError):
    """Raised when a paid run is requested without a hard cap."""


# Conservative reservation before any HTTP call. A typical chat completion
# must fit under remaining budget; otherwise we refuse without sending.
PER_CALL_FLOOR_USD = 0.01
USD_PER_TOKEN_PLACEHOLDER = 0.000002
WORST_CASE_COMPLETION_TOKENS = 4096


class LiveProvider:
    """Thin HTTP client gated by AI4_ENABLE_LIVE_LLM and AI4_MAX_SPEND_USD."""

    name = "live"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        spent_usd: float = 0.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("AI4_API_KEY", "")
        self.api_base = (api_base or os.environ.get("AI4_API_BASE") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("AI4_MODEL") or "gpt-4o-mini"
        self.spent_usd = spent_usd

    def complete(self, *, system: str, user: str) -> Completion:
        return self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )

    def revise(self, *, system: str, user: str, draft: str, feedback: str) -> Completion:
        return self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": draft},
                {"role": "user", "content": f"Revise using this feedback:\n{feedback}"},
            ]
        )

    def _ensure_allowed(self) -> float:
        if os.environ.get("AI4_ENABLE_LIVE_LLM", "0") != "1":
            raise LiveSpendError("Live LLM is disabled. Set AI4_ENABLE_LIVE_LLM=1 only after a spending cap.")
        raw = os.environ.get("AI4_MAX_SPEND_USD", "")
        try:
            cap = float(raw)
        except ValueError as exc:
            raise LiveSpendError("Paid runs need a hard spending cap first (AI4_MAX_SPEND_USD > 0).") from exc
        if cap <= 0:
            raise LiveSpendError("Paid runs need a hard spending cap first (AI4_MAX_SPEND_USD > 0).")
        if not self.api_key:
            raise LiveSpendError("AI4_API_KEY is empty; live calls are not configured.")
        return cap

    def _reservation_usd(self, messages: list[dict[str, str]]) -> float:
        prompt_tokens = max(1, sum(len(str(item.get("content", "")).split()) for item in messages))
        pessimistic = (prompt_tokens + WORST_CASE_COMPLETION_TOKENS) * USD_PER_TOKEN_PLACEHOLDER
        return max(PER_CALL_FLOOR_USD, pessimistic)

    def _chat(self, messages: list[dict[str, str]]) -> Completion:
        cap = self._ensure_allowed()
        remaining = cap - self.spent_usd
        reservation = self._reservation_usd(messages)
        if remaining < reservation:
            raise LiveSpendError(
                f"Remaining budget {remaining:.6f} USD is below the conservative "
                f"per-call floor/reservation ({reservation:.6f} USD). No request was sent."
            )
        payload = json.dumps({"model": self.model, "messages": messages, "temperature": 0}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Live provider request failed: {exc}") from exc
        latency_ms = (time.monotonic() - started) * 1000
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        # Hook only: conservative placeholder until a real price table is frozen.
        # Do not raise after the request: the call was already sent.
        estimated = (prompt_tokens + completion_tokens) * USD_PER_TOKEN_PLACEHOLDER
        self.spent_usd += estimated
        return Completion(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            estimated_usd=estimated,
            model=self.model,
        )
