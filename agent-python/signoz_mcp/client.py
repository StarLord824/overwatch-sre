"""
SigNoz MCP client — the agent's window into production telemetry.

This talks to the *real* SigNoz MCP server (https://github.com/SigNoz/signoz-mcp-server)
over stdio using the official MCP Python SDK. The agent spawns the server as a
subprocess (docker or a downloaded binary), performs the MCP `initialize`
handshake, and calls the server's real tools by their real names.

If the MCP server can't be reached (image not pulled, no SigNoz, offline demo),
we fall back to clearly-labeled MOCK data so a live demo never hard-crashes — but
every mock result is tagged `"_source": "MOCK"` so it's never mistaken for truth.

Reference — real SigNoz MCP tool names & params:
  signoz_list_services(timeRange, start, end, limit, offset)
  signoz_search_traces(service, operation, filter, error, minDuration, timeRange, limit, ...)
  signoz_search_logs(service, severity, searchText, filter, timeRange, limit, ...)
  signoz_query_metrics(metricName, timeAggregation, spaceAggregation, filter, timeRange, ...)
  signoz_list_alerts(active, silenced, filter, limit, ...)
  signoz_get_trace_details(...)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator

from config import signoz_mcp_launch

logger = logging.getLogger(__name__)


# ── The subset of SigNoz MCP tools we expose to the LLM ───────────────────────
# Names match the real server exactly. Descriptions/params are trimmed to what an
# SRE investigation actually needs so the model isn't overwhelmed with 50 tools.
SIGNOZ_MCP_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "signoz_list_services",
            "description": "List all services reporting to SigNoz in the given window. Call this first to learn what services exist and their health at a glance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeRange": {"type": "string", "description": "Relative window, e.g. '30m', '1h', '3h'. Default '1h'.", "default": "1h"},
                    "limit": {"type": "integer", "description": "Max services to return.", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "signoz_search_traces",
            "description": "Search distributed traces. Use error=true to find failing requests, or minDuration to find slow ones. Returns spans with service, operation, duration, status, and trace/span IDs to cite as evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service name to filter by."},
                    "operation": {"type": "string", "description": "Operation / http.route to filter by (optional)."},
                    "error": {"type": "boolean", "description": "Only return error spans.", "default": True},
                    "minDuration": {"type": "string", "description": "Minimum span duration in nanoseconds, e.g. '2000000000' for 2s (optional)."},
                    "timeRange": {"type": "string", "description": "Relative window, e.g. '30m', '1h'.", "default": "30m"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "signoz_search_logs",
            "description": "Search logs. Filter by service and severity (ERROR/FATAL/WARN) or free-text searchText to find exception messages and stack traces. Include exact log lines + timestamps as evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service name to filter by (optional)."},
                    "severity": {"type": "string", "description": "Minimum severity: DEBUG/INFO/WARN/ERROR/FATAL.", "default": "ERROR"},
                    "searchText": {"type": "string", "description": "Free-text to match in the log body (optional)."},
                    "timeRange": {"type": "string", "default": "30m"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "signoz_query_metrics",
            "description": "Query a metric time-series to confirm latency/error/throughput/saturation trends over time. Use for p99 latency, error rate, CPU/memory saturation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metricName": {"type": "string", "description": "Metric name, e.g. 'signoz_latency', 'signoz_calls_total', 'container_memory_usage'."},
                    "timeAggregation": {"type": "string", "description": "avg/sum/min/max/count/rate/p50/p90/p95/p99.", "default": "avg"},
                    "spaceAggregation": {"type": "string", "description": "How to combine series: sum/avg/min/max.", "default": "avg"},
                    "filter": {"type": "string", "description": "Filter expression, e.g. \"service.name = 'checkout'\" (optional)."},
                    "timeRange": {"type": "string", "default": "1h"},
                },
                "required": ["metricName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "signoz_list_alerts",
            "description": "List alert rules and their firing state. Use to see what else is firing that may correlate with this incident.",
            "parameters": {
                "type": "object",
                "properties": {
                    "active": {"type": "boolean", "description": "Only currently-firing alerts.", "default": True},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "signoz_get_trace_details",
            "description": "Fetch the full span hierarchy for a single traceId to see exactly where time was spent or where an error originated downstream.",
            "parameters": {
                "type": "object",
                "properties": {
                    "traceId": {"type": "string", "description": "The trace ID to expand."},
                },
                "required": ["traceId"],
            },
        },
    },
]

SIGNOZ_MCP_TOOL_NAMES: set[str] = {t["function"]["name"] for t in SIGNOZ_MCP_TOOLS}


class SigNozMCP:
    """
    Manages one stdio MCP session to the SigNoz MCP server for the duration of an
    investigation. Use as an async context manager:

        async with SigNozMCP().session() as sig:
            result = await sig.call("signoz_list_services", {"timeRange": "1h"})
    """

    def __init__(self) -> None:
        self._live = False

    @property
    def is_live(self) -> bool:
        """True if the last opened session reached a real MCP server."""
        return self._live

    @asynccontextmanager
    async def session(self, attempts: int = 3) -> AsyncIterator["_Session"]:
        """
        Open one MCP session. The MCP Docker container can be slow to cold-start,
        so we retry the connection a few times with backoff BEFORE falling back to
        mock — a silent live→mock downgrade mid-demo is the worst failure mode.

        Set SIGNOZ_MCP_STRICT=1 to raise instead of falling back to mock (use this
        for `--live` / demos so a connection failure is loud, not disguised as a
        clean run on fake data).
        """
        command, args, env = signoz_mcp_launch()
        logger.info("Launching SigNoz MCP server: %s %s", command, " ".join(args))

        strict = os.getenv("SIGNOZ_MCP_STRICT", "").lower() in ("1", "true", "yes")
        stack = AsyncExitStack()
        mcp_session = None
        available: set[str] = set()
        last_err = ""

        for attempt in range(1, attempts + 1):
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client

                params = StdioServerParameters(command=command, args=args, env=env)
                read, write = await stack.enter_async_context(stdio_client(params))
                mcp_session = await stack.enter_async_context(ClientSession(read, write))
                await mcp_session.initialize()
                tools = await mcp_session.list_tools()
                available = {t.name for t in tools.tools}
                logger.info("Connected to SigNoz MCP. %d tools available.", len(available))
                break
            except BaseException as exc:  # noqa: BLE001 — includes ExceptionGroup
                last_err = _unwrap_error(exc)
                await stack.aclose()
                stack = AsyncExitStack()
                mcp_session = None
                logger.warning("MCP connect attempt %d/%d failed: %s", attempt, attempts, last_err)
                if attempt < attempts:
                    await asyncio.sleep(2 * attempt)

        if mcp_session is not None:
            self._live = True
            try:
                yield _Session(mcp_session, available)
            finally:
                self._live = False
                await stack.aclose()
            return

        # All attempts failed.
        self._live = False
        if strict:
            await stack.aclose()
            raise RuntimeError(
                f"SigNoz MCP unreachable after {attempts} attempts (SIGNOZ_MCP_STRICT=1). "
                f"Last error: {last_err}"
            )
        logger.warning(
            "Could not reach SigNoz MCP server after %d attempts (%s). Falling back to labeled MOCK data.",
            attempts, last_err,
        )
        yield _MockSession()


class _Session:
    """A live MCP session — real tool calls against the SigNoz MCP server."""

    def __init__(self, mcp_session: Any, available: set[str]) -> None:
        self._session = mcp_session
        self._available = available
        self.live = True

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._available)

    async def call(self, name: str, arguments: dict) -> str:
        if name not in self._available:
            return json.dumps({
                "error": f"Tool '{name}' is not offered by this SigNoz MCP server.",
                "available_hint": sorted(self._available)[:15],
            })
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"MCP tool '{name}' failed: {exc}"})

        return _flatten_content(result)


class _MockSession:
    """
    Fallback session used only when the MCP server is unreachable. Returns
    plausible-but-clearly-labeled data so a demo still tells a coherent story.
    Every payload carries "_source": "MOCK".
    """

    live = False
    tool_names: list[str] = []

    async def call(self, name: str, arguments: dict) -> str:
        service = arguments.get("service") or arguments.get("filter") or "checkout-service"
        mock = _MOCK_RESPONSES.get(name, lambda s: {"note": f"mock result for {name}"})(service)
        mock["_source"] = "MOCK"
        return json.dumps(mock, indent=2, default=str)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unwrap_error(exc: BaseException) -> str:
    """
    Dig the real cause out of an ExceptionGroup / TaskGroup wrapper so the log
    says e.g. 'TimeoutError: ...' instead of the opaque
    'unhandled errors in a TaskGroup (1 sub-exception)'.
    """
    sub = getattr(exc, "exceptions", None)
    if sub:
        return " | ".join(_unwrap_error(e) for e in sub)
    msg = str(exc).strip()
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def _flatten_content(result: Any) -> str:
    """Turn an MCP CallToolResult into a JSON/text string for the LLM."""
    try:
        blocks = getattr(result, "content", None) or []
        texts: list[str] = []
        for block in blocks:
            text = getattr(block, "text", None)
            if text is not None:
                texts.append(text)
            else:
                texts.append(str(block))
        joined = "\n".join(texts) if texts else str(result)
    except Exception:  # noqa: BLE001
        joined = str(result)

    if len(joined) > 8000:
        joined = joined[:8000] + "\n... [truncated — too many results]"
    return joined


_MOCK_RESPONSES = {
    "signoz_list_services": lambda s: {
        "services": [
            {"name": "checkout-service", "p99_ms": 4200, "error_rate": 0.17, "rps": 320},
            {"name": "payment-gateway", "p99_ms": 3900, "error_rate": 0.02, "rps": 310},
            {"name": "inventory-service", "p99_ms": 180, "error_rate": 0.00, "rps": 300},
        ],
    },
    "signoz_search_traces": lambda s: {
        "service": s,
        "spans": [
            {
                "traceId": "a1b2c3d4e5f6", "spanId": "9f8e7d",
                "service": s, "operation": "POST /checkout",
                "durationMs": 4500, "status": "ERROR",
                "error": "context deadline exceeded calling payment-gateway",
            },
            {
                "traceId": "b2c3d4e5f6a1", "spanId": "1a2b3c",
                "service": "payment-gateway", "operation": "charge_card",
                "durationMs": 4300, "status": "ERROR",
                "error": "connection pool exhausted (max=20)",
            },
        ],
    },
    "signoz_search_logs": lambda s: {
        "service": s,
        "logs": [
            {"ts": "2026-07-24T10:31:02Z", "severity": "ERROR",
             "body": "payment-gateway: HikariCP - connection is not available, request timed out after 5000ms (pool size 20)"},
            {"ts": "2026-07-24T10:31:04Z", "severity": "FATAL",
             "body": "checkout-service: upstream timeout after 3 retries to payment-gateway"},
        ],
    },
    "signoz_query_metrics": lambda s: {
        "metric": "connection_pool_active",
        "series": [{"t": "10:25", "v": 12}, {"t": "10:28", "v": 20}, {"t": "10:31", "v": 20}],
        "note": "pool saturated at max=20 starting 10:28, coincides with deploy v2.4.1",
    },
    "signoz_list_alerts": lambda s: {
        "alerts": [
            {"name": "High Error Rate — checkout-service", "state": "firing", "since": "10:30"},
            {"name": "DB Connection Pool Saturation", "state": "firing", "since": "10:28"},
        ],
    },
    "signoz_get_trace_details": lambda s: {
        "traceId": "a1b2c3d4e5f6",
        "spans": [
            {"service": "checkout-service", "op": "POST /checkout", "ms": 4500},
            {"service": "payment-gateway", "op": "charge_card", "ms": 4300, "error": "pool exhausted"},
        ],
    },
}
