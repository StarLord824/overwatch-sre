"""
Cost tracker — records every LLM call's token usage, latency, and estimated cost.

Delivers the "LLM Cost Tracer" hackathon idea as a built-in feature: every
investigation reports exactly what it cost to run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


# Pricing per 1M tokens (USD). gpt-4.1 family are published prices; the gpt-5/codex
# entry is approximate — update if your account's rate differs. Unknown models fall
# back to a conservative default (see record_call).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    # Approximate — adjust to your actual Codex/GPT-5 rate.
    "gpt-5.3-codex": {"input": 1.25, "output": 10.00},
}


@dataclass
class LLMCallRecord:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    timestamp: float = field(default_factory=time.time)
    purpose: str = ""


class CostTracker:
    """Accumulates LLM call records and provides aggregate stats."""

    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    def record_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        purpose: str = "",
    ) -> LLMCallRecord:
        total_tokens = prompt_tokens + completion_tokens
        pricing = MODEL_PRICING.get(model, {"input": 5.0, "output": 15.0})
        cost = (
            (prompt_tokens / 1_000_000) * pricing["input"]
            + (completion_tokens / 1_000_000) * pricing["output"]
        )
        record = LLMCallRecord(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=round(cost, 6),
            purpose=purpose,
        )
        self.records.append(record)
        return record

    @property
    def total_cost(self) -> float:
        return sum(r.estimated_cost_usd for r in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    @property
    def call_count(self) -> int:
        return len(self.records)

    def summary(self) -> dict:
        """A compact snapshot for streaming to the dashboard."""
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_tokens": self.total_tokens,
            "llm_calls": self.call_count,
            "model": self.records[-1].model if self.records else None,
        }
