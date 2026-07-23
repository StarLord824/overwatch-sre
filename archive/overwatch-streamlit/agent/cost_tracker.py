"""
Cost tracker — records every LLM call's token usage, latency, and estimated cost.

Covers the "LLM Cost Tracer" hackathon idea as a built-in feature rather than
a separate service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# Pricing per 1M tokens (as of mid-2026, approximate)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
}


@dataclass
class LLMCallRecord:
    """A single LLM API call record."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    estimated_cost_usd: float
    timestamp: float = field(default_factory=time.time)
    purpose: str = ""  # e.g. "hypothesis_generation", "evidence_analysis"


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
        """Record a completed LLM call and compute its cost."""
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
    def total_prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.records)

    @property
    def total_completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.records)

    @property
    def call_count(self) -> int:
        return len(self.records)

    def cost_by_model(self) -> dict[str, float]:
        """Aggregate cost grouped by model."""
        costs: dict[str, float] = {}
        for r in self.records:
            costs[r.model] = costs.get(r.model, 0.0) + r.estimated_cost_usd
        return costs

    def cost_by_purpose(self) -> dict[str, float]:
        """Aggregate cost grouped by purpose/phase."""
        costs: dict[str, float] = {}
        for r in self.records:
            key = r.purpose or "untagged"
            costs[key] = costs.get(key, 0.0) + r.estimated_cost_usd
        return costs

    def to_display_records(self) -> list[dict]:
        """Return records as dicts suitable for Streamlit table display."""
        return [
            {
                "Model": r.model,
                "Purpose": r.purpose,
                "Prompt Tokens": r.prompt_tokens,
                "Completion Tokens": r.completion_tokens,
                "Latency (ms)": round(r.latency_ms),
                "Cost ($)": f"${r.estimated_cost_usd:.4f}",
            }
            for r in self.records
        ]
