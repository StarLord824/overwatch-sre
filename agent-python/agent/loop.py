"""
The investigation loop — a direct tool-calling ReAct agent.

This is the OpenSRE-faithful brain: NO graph, NO chain framework. One loop that
lets the LLM freely choose tools (SigNoz observability + local knowledge/memory),
executes them, feeds results back, and repeats until the model writes its final
RCA. Every step is streamed out via an `emit` callback so the Node gateway can
push it to the dashboard in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Awaitable, Callable

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, LLM_MODEL, model_supports_temperature
from agent.prompts import SYSTEM_PROMPT
from agent.cost_tracker import CostTracker
from agent.tools import ALL_TOOLS, dispatch, tool_family
from knowledge import KnowledgeStore
from signoz_mcp import SigNozMCP
from signoz_mcp.links import build_links
from agent.notify import deliver_report

logger = logging.getLogger(__name__)

# emit(event_dict) -> None. Sync callback; kept simple because Redis publish is sync.
EmitFn = Callable[[dict], None]

MAX_ITERATIONS = 12


class Investigator:
    """Runs one incident investigation as a streaming tool-calling loop."""

    def __init__(self, emit: EmitFn | None = None, signoz=None) -> None:
        self.emit = emit or (lambda e: None)
        # max_retries lets the SDK ride out 429s (it honors Retry-After) instead
        # of surfacing a rate-limit error mid-investigation on low-TPM tiers.
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY, max_retries=6)
        self.model = LLM_MODEL
        self.cost = CostTracker()
        self.knowledge = KnowledgeStore()
        # `signoz` can be overridden with any object exposing .session() (async CM
        # yielding a .call(name, args) session) and .is_live — the eval harness
        # injects a scenario-driven telemetry source here.
        self.signoz = signoz or SigNozMCP()

    async def investigate(self, alert_context: dict) -> dict:
        """
        Investigate an alert. Streams events as it goes; returns the final
        structured report dict (also emitted as the 'final_report' event).
        """
        user_msg = (
            "A production alert has fired. Investigate it and produce an "
            "evidence-backed RCA.\n\nAlert payload:\n"
            + json.dumps(alert_context, indent=2)
        )
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        # One MCP session held open for the whole investigation.
        async with self.signoz.session() as sig:
            self.emit({
                "type": "status",
                "content": (
                    "Connected to SigNoz MCP (live telemetry)."
                    if sig.live else
                    "SigNoz MCP unreachable — running on LABELED MOCK data for demo."
                ),
                "data": {"signoz_live": sig.live},
            })

            for iteration in range(MAX_ITERATIONS):
                choice, usage = await self._chat(messages)
                self._record_cost(usage, iteration, choice.finish_reason)

                msg = choice.message

                # The model reasoned out loud before/while acting.
                if msg.content and msg.tool_calls:
                    self.emit({"type": "thinking", "content": msg.content})

                # Case 1: the model wants to call tools.
                if msg.tool_calls:
                    messages.append(msg.model_dump())
                    await self._run_tool_calls(msg.tool_calls, messages, sig)
                    continue

                # Case 2: final report (no tool calls).
                if msg.content:
                    report = _parse_report(msg.content)
                    report["signoz_live"] = sig.live
                    self._finalize(report, alert_context)
                    self.emit({"type": "final_report", "data": report})
                    self.emit({"type": "cost", "data": self.cost.summary()})
                    await self._deliver(report, alert_context)
                    return report

                # Case 3: empty — nudge once, then bail.
                self.emit({
                    "type": "status",
                    "content": "Model returned no content or tool calls; stopping.",
                })
                break

        # Safety exit (hit iteration cap or empty response).
        fallback = {
            "root_cause": "Investigation did not converge within the iteration budget.",
            "confidence": "LOW",
            "summary": "Review the partial evidence stream above.",
            "evidence": [],
            "report_md": "Investigation halted early.",
            "signoz_live": self.signoz.is_live,
        }
        self._finalize(fallback, alert_context)
        self.emit({"type": "final_report", "data": fallback})
        self.emit({"type": "cost", "data": self.cost.summary()})
        await self._deliver(fallback, alert_context)
        return fallback

    def _finalize(self, report: dict, alert_context: dict) -> None:
        """Attach SigNoz deep-links so cited evidence is one click away."""
        report["signoz_links"] = build_links(report, alert_context)

    async def _deliver(self, report: dict, alert_context: dict) -> None:
        """OpenSRE step 6 — post the RCA to Slack/Telegram if configured (else no-op)."""
        channels = await deliver_report(report, alert_context)
        if channels:
            self.emit({
                "type": "status",
                "content": f"Report delivered to {', '.join(channels)}.",
                "data": {"delivered_to": channels},
            })

    # ── internals ─────────────────────────────────────────────────────────────
    async def _chat(self, messages: list[dict]):
        start = time.time()
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "tools": ALL_TOOLS,
            "tool_choice": "auto",
        }
        # GPT-5 / Codex reasoning models reject a custom temperature.
        if model_supports_temperature(self.model):
            kwargs["temperature"] = 0.1
        response = await self.client.chat.completions.create(**kwargs)
        latency_ms = (time.time() - start) * 1000
        self._last_latency = latency_ms
        return response.choices[0], response.usage

    def _record_cost(self, usage, iteration: int, finish_reason: str) -> None:
        if not usage:
            return
        purpose = "final_report" if finish_reason == "stop" else "tool_planning"
        self.cost.record_call(
            model=self.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=getattr(self, "_last_latency", 0.0),
            purpose=purpose,
        )

    async def _run_tool_calls(self, tool_calls, messages: list[dict], sig) -> None:
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            self.emit({
                "type": "tool_call",
                "content": f"{tool_family(name)} · {name}",
                "data": {"tool": name, "family": tool_family(name), "args": args},
            })

            result = await dispatch(name, args, sig, self.knowledge)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })


# ── Report parsing ────────────────────────────────────────────────────────────

def _section(md: str, heading_keyword: str) -> str:
    """Extract the text under a '## ... <keyword> ...' heading."""
    pattern = rf"##[^\n]*{heading_keyword}[^\n]*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, md, flags=re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _parse_report(md: str) -> dict:
    """
    Parse the agent's Markdown RCA into the structured shape the Next.js frontend
    and Slack formatter expect: root_cause, confidence, summary, evidence[].
    Falls back gracefully if the model didn't follow the template exactly.
    """
    root_cause = _section(md, "Root Cause") or md.strip()[:400]

    conf_text = _section(md, "Confidence")
    confidence = "MEDIUM"
    for level in ("HIGH", "MEDIUM", "LOW"):
        if re.search(rf"\b{level}\b", conf_text or md, flags=re.IGNORECASE):
            confidence = level
            break

    remediation = _section(md, "Remediation")
    summary = remediation or _section(md, "Root Cause") or root_cause

    evidence_block = _section(md, "Evidence")
    evidence = [
        re.sub(r"^[-*]\s*", "", line).strip()
        for line in evidence_block.splitlines()
        if line.strip().startswith(("-", "*"))
    ]

    prevention = _section(md, "Prevention")

    return {
        "root_cause": root_cause,
        "confidence": confidence,
        "summary": summary,
        "evidence": evidence,
        "prevention": prevention,
        "report_md": md.strip(),
    }
