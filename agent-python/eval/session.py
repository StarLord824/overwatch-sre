"""
Scenario-driven SigNoz session for the eval harness.

Mimics the exact interface the Investigator expects from a SigNoz MCP client
(`.session()` async context manager yielding an object with `.call(name, args)`
and `.live`), but instead of talking to a real server it serves a scenario's
*injected telemetry* — including deliberate red herrings on the wrong services.

This lets the benchmark run deterministically with NO SigNoz and NO Docker; the
only external dependency is the LLM the agent itself uses.

Telemetry dict schema (all keys optional):
    {
      "services":       [ {name, p99_ms, error_rate, rps}, ... ],
      "traces":         { "<service>": [ {traceId, spanId, service, operation,
                                          durationMs, status, error}, ... ] },
      "trace_details":  { "<traceId>": {...span tree...} },
      "logs":           { "<service>": [ {ts, severity, body}, ... ] },
      "metrics":        { "<metricName>": {...series...} },
      "alerts":         [ {name, state, since}, ... ],
    }
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator


class ScenarioSigNoz:
    """Drop-in replacement for SigNozMCP that serves scenario fixtures."""

    def __init__(self, telemetry: dict) -> None:
        self.telemetry = telemetry
        self._live = True

    @property
    def is_live(self) -> bool:
        return self._live

    @asynccontextmanager
    async def session(self) -> AsyncIterator["_ScenarioSession"]:
        yield _ScenarioSession(self.telemetry)


class _ScenarioSession:
    live = True  # the scenario telemetry IS the designated ground truth

    def __init__(self, telemetry: dict) -> None:
        self.t = telemetry

    async def call(self, name: str, arguments: dict) -> str:
        result = self._route(name, arguments)
        text = json.dumps(result, default=str)
        if len(text) > 8000:
            text = text[:8000] + "\n... [truncated]"
        return text

    # ── routing ───────────────────────────────────────────────────────────────
    def _route(self, name: str, args: dict) -> Any:
        if name == "signoz_list_services":
            return {"services": self.t.get("services", [])}

        if name == "signoz_search_traces":
            svc = args.get("service", "")
            spans = self.t.get("traces", {}).get(svc, [])
            if args.get("error") is True:
                spans = [s for s in spans if str(s.get("status", "")).upper() == "ERROR"] or spans
            return {"service": svc, "spans": spans[: args.get("limit", 20)]}

        if name == "signoz_get_trace_details":
            tid = args.get("traceId", "")
            return self.t.get("trace_details", {}).get(tid, {"traceId": tid, "spans": []})

        if name == "signoz_search_logs":
            svc = args.get("service", "")
            logs_by_svc = self.t.get("logs", {})
            if svc:
                logs = logs_by_svc.get(svc, [])
            else:
                logs = [l for group in logs_by_svc.values() for l in group]
            return {"service": svc, "logs": logs[: args.get("limit", 50)]}

        if name == "signoz_query_metrics":
            requested = args.get("metricName", "")
            metrics = self.t.get("metrics", {})
            data = _fuzzy_metric(requested, metrics)
            if data is None:
                return {"metric": requested, "series": [], "note": "no data for this metric"}
            return {"metric": requested, **data}

        if name == "signoz_list_alerts":
            return {"alerts": self.t.get("alerts", [])}

        if name == "signoz_create_alert":
            # The self-improving step: acknowledge the guard alert would be created.
            return {"created": True, "alert_id": "alert-eval-001",
                    "name": args.get("name", ""), "condition": args.get("condition", "")}

        return {"note": f"no fixture for {name}"}


def _fuzzy_metric(requested: str, metrics: dict) -> dict | None:
    """Match a requested metric name to a fixture key with some tolerance."""
    if not requested:
        return None
    if requested in metrics:
        return metrics[requested]
    r = requested.lower()
    for key, val in metrics.items():
        k = key.lower()
        if r in k or k in r or _token_overlap(r, k):
            return val
    return None


def _token_overlap(a: str, b: str) -> bool:
    ta = {t for t in a.replace(".", "_").split("_") if len(t) > 2}
    tb = {t for t in b.replace(".", "_").split("_") if len(t) > 2}
    return bool(ta & tb)
