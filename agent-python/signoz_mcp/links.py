"""
SigNoz deep-link builder — turn cited evidence into clickable SigNoz UI URLs.

Closing the loop: an RCA is far more useful when every trace ID / service the
agent cites links straight back into SigNoz. We post-process the final report,
find trace IDs and service names, and attach deep links an engineer can click.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from config import SIGNOZ_URL

# 24–32 hex chars = a trace/span id. Kept slightly loose to catch demo IDs too.
_TRACE_ID_RE = re.compile(r"\b([0-9a-fA-F]{12,32})\b")


def _base() -> str:
    return SIGNOZ_URL.rstrip("/")


def trace_link(trace_id: str) -> str:
    return f"{_base()}/trace/{quote(trace_id)}"


def service_link(service: str) -> str:
    return f"{_base()}/services/{quote(service)}"


def logs_link(service: str = "") -> str:
    if service:
        return f"{_base()}/logs?service={quote(service)}"
    return f"{_base()}/logs"


def build_links(report: dict, alert: dict | None = None) -> list[dict]:
    """
    Extract deep links from a finished report. Returns a list of
    {label, url, kind} dicts (deduped, order-preserving).
    """
    text = " ".join([
        report.get("report_md", ""),
        report.get("root_cause", ""),
        " ".join(report.get("evidence", []) or []),
    ])
    links: list[dict] = []
    seen: set[str] = set()

    def add(label: str, url: str, kind: str) -> None:
        if url not in seen:
            seen.add(url)
            links.append({"label": label, "url": url, "kind": kind})

    # Trace IDs cited anywhere in the report.
    for tid in _TRACE_ID_RE.findall(text):
        # Skip pure decimal runs (timestamps, durations) — require a letter.
        if not re.search(r"[a-fA-F]", tid):
            continue
        add(f"Trace {tid}", trace_link(tid), "trace")

    # The alerting service always gets a service + logs link.
    svc = (alert or {}).get("service", "")
    if svc:
        add(f"{svc} service view", service_link(svc), "service")
        add(f"{svc} logs", logs_link(svc), "logs")

    return links
