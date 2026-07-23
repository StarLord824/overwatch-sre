"""
SigNoz API tools — the agent's ONLY window into the production environment.

These tools wrap the SigNoz HTTP API to query traces, logs, metrics, and alerts.
Each tool is defined as an OpenAI function-calling schema so the LLM can invoke
them natively within the ReAct loop.

If a SigNoz MCP server is available, these can be swapped for MCP tool calls.
The abstraction stays the same.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx

from config import SIGNOZ_BASE_URL, SIGNOZ_API_KEY


# ── HTTP client ──────────────────────────────────────────────────────────────

def _signoz_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if SIGNOZ_API_KEY:
        headers["SIGNOZ-API-KEY"] = SIGNOZ_API_KEY
    return headers


def _signoz_get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the SigNoz API."""
    url = f"{SIGNOZ_BASE_URL}/api/v1{path}"
    try:
        resp = httpx.get(url, headers=_signoz_headers(), params=params, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"SigNoz API returned {e.response.status_code}", "detail": e.response.text[:500]}
    except httpx.ConnectError:
        return {"error": f"Cannot connect to SigNoz at {SIGNOZ_BASE_URL}. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


def _signoz_post(path: str, body: dict) -> dict:
    """Make a POST request to the SigNoz API."""
    url = f"{SIGNOZ_BASE_URL}/api/v1{path}"
    try:
        resp = httpx.post(url, headers=_signoz_headers(), json=body, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"SigNoz API returned {e.response.status_code}", "detail": e.response.text[:500]}
    except httpx.ConnectError:
        return {"error": f"Cannot connect to SigNoz at {SIGNOZ_BASE_URL}. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


# ── Tool implementations ─────────────────────────────────────────────────────

def query_services() -> dict:
    """List all services reporting to SigNoz with their metadata."""
    return _signoz_get("/services", params={"start": _minutes_ago(60), "end": _now()})


def query_traces(
    service_name: str,
    time_range_minutes: int = 30,
    status: str = "error",
    limit: int = 20,
) -> dict:
    """
    Query traces from SigNoz for a specific service.

    Args:
        service_name: The service to query traces for
        time_range_minutes: How far back to look (default 30 min)
        status: Filter by status — 'error', 'ok', or 'all'
        limit: Maximum number of traces to return
    """
    start = _minutes_ago(time_range_minutes)
    end = _now()

    # SigNoz trace search via query builder
    payload = {
        "start": start,
        "end": end,
        "step": 60,
        "compositeQuery": {
            "queryType": "builder",
            "panelType": "list",
            "builderQueries": {
                "A": {
                    "dataSource": "traces",
                    "queryName": "A",
                    "aggregateOperator": "noop",
                    "aggregateAttribute": {},
                    "filters": {
                        "op": "AND",
                        "items": _build_trace_filters(service_name, status),
                    },
                    "limit": limit,
                    "orderBy": [{"columnName": "timestamp", "order": "desc"}],
                }
            },
        },
    }
    return _signoz_post("/query_range", payload)


def query_logs(
    service_name: str = "",
    severity: str = "error",
    time_range_minutes: int = 30,
    search_text: str = "",
    limit: int = 50,
) -> dict:
    """
    Query logs from SigNoz.

    Args:
        service_name: Filter by service name (optional)
        severity: Minimum severity — 'error', 'warn', 'info', 'debug'
        time_range_minutes: How far back to look
        search_text: Free-text search within log body
        limit: Maximum logs to return
    """
    start = _minutes_ago(time_range_minutes)
    end = _now()

    filters: list[dict] = []
    if service_name:
        filters.append({
            "key": {"key": "service.name", "dataType": "string", "type": "resource", "isColumn": False},
            "op": "=",
            "value": service_name,
        })
    if severity:
        severity_map = {"debug": "DEBUG", "info": "INFO", "warn": "WARN", "error": "ERROR", "fatal": "FATAL"}
        sev_val = severity_map.get(severity.lower(), severity.upper())
        filters.append({
            "key": {"key": "severity_text", "dataType": "string", "type": "tag", "isColumn": True},
            "op": "in",
            "value": [sev_val, "FATAL"] if sev_val == "ERROR" else [sev_val],
        })
    if search_text:
        filters.append({
            "key": {"key": "body", "dataType": "string", "type": "tag", "isColumn": True},
            "op": "contains",
            "value": search_text,
        })

    payload = {
        "start": start,
        "end": end,
        "step": 60,
        "compositeQuery": {
            "queryType": "builder",
            "panelType": "list",
            "builderQueries": {
                "A": {
                    "dataSource": "logs",
                    "queryName": "A",
                    "aggregateOperator": "noop",
                    "aggregateAttribute": {},
                    "filters": {"op": "AND", "items": filters},
                    "limit": limit,
                    "orderBy": [{"columnName": "timestamp", "order": "desc"}],
                }
            },
        },
    }
    return _signoz_post("/query_range", payload)


def query_metrics(
    metric_name: str,
    service_name: str = "",
    time_range_minutes: int = 60,
    aggregation: str = "avg",
    step_seconds: int = 60,
) -> dict:
    """
    Query a metric time-series from SigNoz.

    Args:
        metric_name: The metric name (e.g. 'signoz_latency', 'signoz_calls_total')
        service_name: Filter by service name (optional)
        time_range_minutes: How far back to look
        aggregation: Aggregation function — 'avg', 'sum', 'min', 'max', 'count', 'p99', 'p95', 'p50'
        step_seconds: Resolution step in seconds
    """
    start = _minutes_ago(time_range_minutes)
    end = _now()

    filters: list[dict] = []
    if service_name:
        filters.append({
            "key": {"key": "service_name", "dataType": "string", "type": "resource", "isColumn": False},
            "op": "=",
            "value": service_name,
        })

    payload = {
        "start": start,
        "end": end,
        "step": step_seconds,
        "compositeQuery": {
            "queryType": "builder",
            "panelType": "graph",
            "builderQueries": {
                "A": {
                    "dataSource": "metrics",
                    "queryName": "A",
                    "aggregateOperator": aggregation,
                    "aggregateAttribute": {
                        "key": metric_name,
                        "dataType": "float64",
                        "type": "Gauge",
                        "isColumn": False,
                    },
                    "filters": {"op": "AND", "items": filters},
                    "groupBy": [],
                }
            },
        },
    }
    return _signoz_post("/query_range", payload)


def query_service_overview(
    service_name: str,
    time_range_minutes: int = 60,
) -> dict:
    """
    Get a high-level overview of a service: error rate, latency percentiles,
    and request throughput.

    Args:
        service_name: The service to get overview for
        time_range_minutes: How far back to look
    """
    return _signoz_get(
        "/service/overview",
        params={
            "service": service_name,
            "start": _minutes_ago(time_range_minutes),
            "end": _now(),
            "step": 60,
        },
    )


def list_alerts(
    state: str = "firing",
    limit: int = 20,
) -> dict:
    """
    List alerts from SigNoz.

    Args:
        state: Alert state filter — 'firing', 'resolved', 'all'
        limit: Maximum alerts to return
    """
    params: dict[str, Any] = {"limit": limit}
    if state != "all":
        params["state"] = state
    return _signoz_get("/rules", params=params)


# ── Helper functions ─────────────────────────────────────────────────────────

def _now() -> int:
    """Current time in nanoseconds."""
    return int(time.time() * 1_000_000_000)


def _minutes_ago(minutes: int) -> int:
    """Time N minutes ago in nanoseconds."""
    return int((time.time() - minutes * 60) * 1_000_000_000)


def _build_trace_filters(service_name: str, status: str) -> list[dict]:
    """Build filter items for a trace query."""
    filters = [
        {
            "key": {"key": "service.name", "dataType": "string", "type": "resource", "isColumn": False},
            "op": "=",
            "value": service_name,
        }
    ]
    if status == "error":
        filters.append({
            "key": {"key": "hasError", "dataType": "bool", "type": "tag", "isColumn": True},
            "op": "=",
            "value": True,
        })
    return filters


# ── OpenAI function-calling tool schemas ──────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_services",
            "description": "List all services currently reporting to SigNoz with their names and metadata. Use this first to discover what services exist.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_traces",
            "description": "Query traces from SigNoz for a specific service. Returns trace spans with timing, status, and attributes. Use this to find error traces, slow requests, or trace a specific request flow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "The service name to query traces for"},
                    "time_range_minutes": {"type": "integer", "description": "How far back to look in minutes (default: 30)", "default": 30},
                    "status": {"type": "string", "enum": ["error", "ok", "all"], "description": "Filter traces by status (default: error)", "default": "error"},
                    "limit": {"type": "integer", "description": "Max traces to return (default: 20)", "default": 20},
                },
                "required": ["service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_logs",
            "description": "Query logs from SigNoz. Filter by service, severity level, and free-text search. Use this to find error messages, stack traces, and application log output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Filter logs by service name (optional)", "default": ""},
                    "severity": {"type": "string", "enum": ["debug", "info", "warn", "error", "fatal"], "description": "Minimum severity level (default: error)", "default": "error"},
                    "time_range_minutes": {"type": "integer", "description": "How far back to look in minutes (default: 30)", "default": 30},
                    "search_text": {"type": "string", "description": "Free-text search within log body (optional)", "default": ""},
                    "limit": {"type": "integer", "description": "Max logs to return (default: 50)", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics",
            "description": "Query a metric time-series from SigNoz. Use this to check latency trends, error rates, throughput, and other numerical indicators over time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_name": {"type": "string", "description": "The metric name (e.g. 'signoz_latency', 'signoz_calls_total')"},
                    "service_name": {"type": "string", "description": "Filter by service name (optional)", "default": ""},
                    "time_range_minutes": {"type": "integer", "description": "How far back to look (default: 60)", "default": 60},
                    "aggregation": {"type": "string", "enum": ["avg", "sum", "min", "max", "count", "p99", "p95", "p50"], "description": "Aggregation function (default: avg)", "default": "avg"},
                    "step_seconds": {"type": "integer", "description": "Time resolution step in seconds (default: 60)", "default": 60},
                },
                "required": ["metric_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_service_overview",
            "description": "Get a high-level overview of a service including error rate, latency percentiles (p50/p95/p99), and request throughput. Good starting point for any investigation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "The service to get overview for"},
                    "time_range_minutes": {"type": "integer", "description": "How far back to look (default: 60)", "default": 60},
                },
                "required": ["service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_alerts",
            "description": "List alerts from SigNoz. Use this to check if any alerts are currently firing or recently resolved that may correlate with the incident.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "enum": ["firing", "resolved", "all"], "description": "Alert state filter (default: firing)", "default": "firing"},
                    "limit": {"type": "integer", "description": "Max alerts to return (default: 20)", "default": 20},
                },
                "required": [],
            },
        },
    },
]


# ── Tool dispatcher ──────────────────────────────────────────────────────────

TOOL_FUNCTIONS: dict[str, callable] = {
    "query_services": query_services,
    "query_traces": query_traces,
    "query_logs": query_logs,
    "query_metrics": query_metrics,
    "query_service_overview": query_service_overview,
    "list_alerts": list_alerts,
}


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name and return the result as a JSON string."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = fn(**arguments)
        # Truncate very large responses to avoid blowing up the context window
        result_str = json.dumps(result, indent=2, default=str)
        if len(result_str) > 8000:
            result_str = result_str[:8000] + "\n... [truncated — too many results]"
        return result_str
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})
