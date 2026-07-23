"""
ReAct Agent Core — the investigation engine.

A simple, robust ReAct (Reason + Act) loop that:
  1. Sends the system prompt + user query to the LLM
  2. If the LLM requests tool calls, executes them against SigNoz
  3. Feeds tool results back to the LLM
  4. Repeats until the LLM produces a final text response (no more tool calls)
  5. Tracks every LLM call's cost

No LangGraph, no framework overhead. Just a clean loop that's easy to debug
and explain to hackathon judges.

Inspired by OpenSRE's "shared runtime tool-calling loop" (AGENTS.md).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Generator, Optional

from openai import OpenAI

from config import OPENAI_API_KEY, LLM_MODEL
from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOL_SCHEMAS, execute_tool
from agent.cost_tracker import CostTracker


@dataclass
class ToolCallEvent:
    """Represents a single tool call made during investigation."""

    tool_name: str
    arguments: dict
    result: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentStep:
    """One step of the agent's reasoning — either thinking or acting."""

    step_type: str  # "thinking", "tool_call", "final_report"
    content: str
    tool_calls: list[ToolCallEvent] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class SREAgent:
    """
    The Over-Watch SRE investigation agent.

    Usage:
        agent = SREAgent()
        for step in agent.investigate("Our checkout service is returning 500s"):
            print(step)
    """

    MAX_ITERATIONS = 15  # Safety limit to prevent infinite loops

    def __init__(
        self,
        model: str = "",
        api_key: str = "",
        cost_tracker: Optional[CostTracker] = None,
    ) -> None:
        self.model = model or LLM_MODEL
        self.client = OpenAI(api_key=api_key or OPENAI_API_KEY)
        self.cost_tracker = cost_tracker or CostTracker()
        self.steps: list[AgentStep] = []
        self.messages: list[dict] = []

    def investigate(self, user_input: str) -> Generator[AgentStep, None, None]:
        """
        Run a full investigation. Yields AgentStep objects as the agent
        reasons and acts, enabling real-time streaming in the UI.

        Args:
            user_input: The incident description or alert context
        """
        # Initialize conversation
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
        self.steps = []

        for iteration in range(self.MAX_ITERATIONS):
            # Call the LLM
            start_time = time.time()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.1,  # Low temperature for precise investigation
            )
            latency_ms = (time.time() - start_time) * 1000

            choice = response.choices[0]
            usage = response.usage

            # Track cost
            if usage:
                purpose = f"iteration_{iteration}"
                if choice.finish_reason == "stop":
                    purpose = "final_report"
                elif choice.finish_reason == "tool_calls":
                    purpose = "tool_planning"

                self.cost_tracker.record_call(
                    model=self.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    latency_ms=latency_ms,
                    purpose=purpose,
                )

            # Case 1: The agent wants to call tools
            if choice.message.tool_calls:
                # If the agent also produced reasoning text, yield it
                if choice.message.content:
                    thinking_step = AgentStep(
                        step_type="thinking",
                        content=choice.message.content,
                    )
                    self.steps.append(thinking_step)
                    yield thinking_step

                # Add assistant message (with tool calls) to conversation
                self.messages.append(choice.message.model_dump())

                # Execute each tool call
                tool_events = []
                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        fn_args = {}

                    # Execute the tool
                    result = execute_tool(fn_name, fn_args)

                    tool_event = ToolCallEvent(
                        tool_name=fn_name,
                        arguments=fn_args,
                        result=result,
                    )
                    tool_events.append(tool_event)

                    # Add tool result to conversation
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })

                # Yield the tool call step
                tool_step = AgentStep(
                    step_type="tool_call",
                    content=f"Executed {len(tool_events)} tool(s): {', '.join(tc.tool_name for tc in tool_events)}",
                    tool_calls=tool_events,
                )
                self.steps.append(tool_step)
                yield tool_step

            # Case 2: The agent produced a final response (no tool calls)
            elif choice.finish_reason == "stop" and choice.message.content:
                final_step = AgentStep(
                    step_type="final_report",
                    content=choice.message.content,
                )
                self.steps.append(final_step)
                yield final_step
                return  # Investigation complete

            # Case 3: Unexpected — no content and no tool calls
            else:
                error_step = AgentStep(
                    step_type="final_report",
                    content="⚠️ Agent stopped unexpectedly without producing a report.",
                )
                self.steps.append(error_step)
                yield error_step
                return

        # Safety: if we hit MAX_ITERATIONS
        safety_step = AgentStep(
            step_type="final_report",
            content=f"⚠️ Investigation halted after {self.MAX_ITERATIONS} iterations to prevent runaway costs. Review partial findings above.",
        )
        self.steps.append(safety_step)
        yield safety_step

    def get_investigation_timeline(self) -> list[dict]:
        """Return the investigation steps as a timeline for UI display."""
        timeline = []
        for i, step in enumerate(self.steps):
            entry = {
                "step": i + 1,
                "type": step.step_type,
                "content": step.content[:200] + "..." if len(step.content) > 200 else step.content,
                "timestamp": step.timestamp,
            }
            if step.tool_calls:
                entry["tools"] = [
                    {"name": tc.tool_name, "args": tc.arguments}
                    for tc in step.tool_calls
                ]
            timeline.append(entry)
        return timeline
