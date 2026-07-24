"""
Tool registry + dispatcher for the investigation loop.

The agent sees a single flat list of tools. Under the hood they split into two
families that mirror the OpenSRE architecture:

  • Observability tools → dispatched to the SigNoz MCP session (real telemetry)
  • Knowledge/Memory tools → dispatched to the local KnowledgeStore

`dispatch()` routes a tool call to the right backend and always returns a string
result to feed back into the model.
"""

from __future__ import annotations

import json

from signoz_mcp import SIGNOZ_MCP_TOOLS
from signoz_mcp.client import SIGNOZ_MCP_TOOL_NAMES
from knowledge import KNOWLEDGE_TOOLS, KnowledgeStore

# The full toolset advertised to the LLM.
ALL_TOOLS: list[dict] = KNOWLEDGE_TOOLS + SIGNOZ_MCP_TOOLS

_KNOWLEDGE_TOOL_NAMES = {t["function"]["name"] for t in KNOWLEDGE_TOOLS}


def tool_family(name: str) -> str:
    """Classify a tool for UI labeling: 'observability' or 'knowledge'."""
    if name in SIGNOZ_MCP_TOOL_NAMES:
        return "observability"
    if name in _KNOWLEDGE_TOOL_NAMES:
        return "knowledge"
    return "unknown"


async def dispatch(name: str, arguments: dict, signoz_session, knowledge: KnowledgeStore) -> str:
    """
    Execute one tool call.

    Args:
        name: tool name the LLM requested
        arguments: parsed JSON arguments
        signoz_session: an open SigNoz MCP session (_Session or _MockSession)
        knowledge: the local KnowledgeStore
    """
    # ── Knowledge / Memory (local) ────────────────────────────────────────────
    if name == "search_runbooks":
        return json.dumps(knowledge.search_runbooks(arguments.get("query", "")), default=str)
    if name == "recall_similar_incidents":
        return json.dumps(
            knowledge.recall_similar_incidents(arguments.get("description", "")), default=str
        )
    if name == "save_incident_memory":
        return json.dumps(
            knowledge.save_incident_memory(
                title=arguments.get("title", "Untitled incident"),
                root_cause=arguments.get("root_cause", ""),
                summary=arguments.get("summary", ""),
                confidence=arguments.get("confidence", ""),
            ),
            default=str,
        )

    # ── Observability (SigNoz MCP) ────────────────────────────────────────────
    if name in SIGNOZ_MCP_TOOL_NAMES:
        return await signoz_session.call(name, arguments)

    return json.dumps({"error": f"Unknown tool: {name}"})
