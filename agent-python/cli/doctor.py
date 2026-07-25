"""
Preflight diagnostics - "why isn't this working?" answered in one command.

Each check returns a CheckResult with a status, a short detail line, and (when
failing) a concrete remediation hint. Nothing here raises: a broken environment
should produce a readable table, not a traceback.

Cheap checks run always. The `--deep` MCP check actually spawns the SigNoz MCP
server over stdio and issues a real query, so it is opt-in.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from rich.table import Table

from cli.console import console

OK, FAIL, WARN = "ok", "fail", "warn"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


# -- individual checks ---------------------------------------------------------

def check_env_file() -> CheckResult:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        return CheckResult(".env file", OK, str(env_path.name))
    return CheckResult(
        ".env file", FAIL, "not found",
        "cp .env.example .env  - then fill in your keys",
    )


def check_openai_key() -> CheckResult:
    from config import OPENAI_API_KEY, LLM_MODEL
    if OPENAI_API_KEY:
        masked = f"{OPENAI_API_KEY[:6]}...{OPENAI_API_KEY[-4:]}" if len(OPENAI_API_KEY) > 12 else "set"
        return CheckResult("OpenAI API key", OK, f"{masked}  (model: {LLM_MODEL})")
    return CheckResult(
        "OpenAI API key", FAIL, "OPENAI_API_KEY is empty",
        "set OPENAI_API_KEY in .env - the agent cannot reason without it",
    )


def check_signoz_config() -> CheckResult:
    from config import SIGNOZ_URL, SIGNOZ_API_KEY
    if not SIGNOZ_API_KEY:
        return CheckResult(
            "SigNoz credentials", WARN, f"{SIGNOZ_URL} (no API key)",
            "set SIGNOZ_API_KEY in .env - without it the agent falls back to MOCK data",
        )
    return CheckResult("SigNoz credentials", OK, SIGNOZ_URL)


def check_signoz_reachable(timeout: float = 6.0) -> CheckResult:
    """Plain HTTPS reachability of the SigNoz instance (no MCP involved)."""
    from config import SIGNOZ_URL
    try:
        import httpx
        resp = httpx.get(SIGNOZ_URL, timeout=timeout, follow_redirects=True)
        # Any HTTP answer proves the host is up; auth-gated codes are still "reachable".
        return CheckResult("SigNoz reachable", OK, f"HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "SigNoz reachable", FAIL, f"{type(exc).__name__}",
            f"cannot reach {SIGNOZ_URL} - check the URL and your connection",
        )


def check_docker() -> CheckResult:
    from config import SIGNOZ_MCP_MODE
    if SIGNOZ_MCP_MODE != "docker":
        return CheckResult("Docker", OK, f"not required (mode={SIGNOZ_MCP_MODE})")
    if shutil.which("docker") is None:
        return CheckResult(
            "Docker", FAIL, "docker not on PATH",
            "install Docker Desktop, or set SIGNOZ_MCP_MODE=binary",
        )
    import subprocess
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=20, text=True,
        )
        if proc.returncode == 0:
            return CheckResult("Docker", OK, "daemon running")
        return CheckResult(
            "Docker", FAIL, "daemon not responding",
            "start Docker Desktop and wait for it to finish booting",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult("Docker", FAIL, type(exc).__name__, "start Docker Desktop")


def _port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_rabbitmq() -> CheckResult:
    from config import RABBITMQ_URL
    parsed = urlparse(RABBITMQ_URL)
    host, port = parsed.hostname or "localhost", parsed.port or 5672
    if _port_open(host, port):
        return CheckResult("RabbitMQ", OK, f"{host}:{port}")
    return CheckResult(
        "RabbitMQ", WARN, f"{host}:{port} closed",
        "docker compose up -d   (only needed for the full pipeline, not for eval)",
    )


def check_redis() -> CheckResult:
    from config import REDIS_URL
    parsed = urlparse(REDIS_URL)
    host, port = parsed.hostname or "localhost", parsed.port or 6379
    if _port_open(host, port):
        return CheckResult("Redis", OK, f"{host}:{port}")
    return CheckResult(
        "Redis", WARN, f"{host}:{port} closed",
        "docker compose up -d   (only needed for the full pipeline, not for eval)",
    )


def check_delivery() -> CheckResult:
    slack = bool(os.getenv("SLACK_WEBHOOK_URL", "").strip())
    tg = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())
    channels = [n for n, on in (("Slack", slack), ("Telegram", tg)) if on]
    if channels:
        return CheckResult("Report delivery", OK, ", ".join(channels))
    return CheckResult(
        "Report delivery", WARN, "no channel configured",
        "optional: set SLACK_WEBHOOK_URL or TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID",
    )


def check_mcp_deep() -> CheckResult:
    """Actually spawn the MCP server and run a live query. Slow; opt-in."""
    async def _run() -> CheckResult:
        try:
            from signoz_mcp import SigNozMCP
            sig = SigNozMCP()
            async with sig.session() as s:
                if not s.live:
                    return CheckResult(
                        "SigNoz MCP (deep)", FAIL, "fell back to MOCK",
                        "run `overwatch doctor` checks above; ensure Docker is up and the image is pulled",
                    )
                result = await s.call("signoz_list_services", {"timeRange": "1h"})
                lowered = result.lower()
                if any(m in lowered for m in ("unexpected status 4", "forbidden", "unauthorized", "403", "401")):
                    return CheckResult(
                        "SigNoz MCP (deep)", FAIL, "connected but API rejected the query",
                        "give the SigNoz service-account key an Editor or Admin role",
                    )
                n_tools = len(s.tool_names)
                return CheckResult("SigNoz MCP (deep)", OK, f"{n_tools} tools, live query succeeded")
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                "SigNoz MCP (deep)", FAIL, type(exc).__name__,
                "check Docker is running and `docker pull signoz/signoz-mcp-server:latest`",
            )

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        return CheckResult("SigNoz MCP (deep)", FAIL, type(exc).__name__)


# -- orchestration -------------------------------------------------------------

def run_checks(deep: bool = False) -> list[CheckResult]:
    results = [
        check_env_file(),
        check_openai_key(),
        check_signoz_config(),
        check_signoz_reachable(),
        check_docker(),
        check_rabbitmq(),
        check_redis(),
        check_delivery(),
    ]
    if deep:
        console.print("[muted]running deep MCP check (spawns the SigNoz MCP server)...[/muted]")
        results.append(check_mcp_deep())
    return results


def render(results: list[CheckResult]) -> int:
    """Print the results table. Returns process exit code (0 = no failures)."""
    table = Table(show_header=True, header_style="info", box=None, padding=(0, 2))
    table.add_column("", width=6)
    table.add_column("Check", style="heading")
    table.add_column("Detail", style="muted", overflow="fold")

    # NOTE: no square brackets in the label text - Rich would parse them as markup tags.
    marks = {
        OK: "[success]PASS[/success]",
        FAIL: "[error]FAIL[/error]",
        WARN: "[warning]WARN[/warning]",
    }
    for r in results:
        table.add_row(marks[r.status], r.name, r.detail)
    console.print()
    console.print(table)

    problems = [r for r in results if r.status in (FAIL, WARN) and r.fix]
    if problems:
        console.print()
        for r in problems:
            style = "error" if r.status == FAIL else "warning"
            console.print(f"  [{style}]{r.name}[/{style}]  [muted]{r.fix}[/muted]")

    failures = sum(1 for r in results if r.status == FAIL)
    console.print()
    if failures:
        console.print(f"[error]{failures} blocking issue(s).[/error] [muted]Warnings are safe to ignore for the benchmark.[/muted]")
    else:
        console.print("[success]All blocking checks passed.[/success] [muted]Try:  overwatch eval[/muted]")
    return 1 if failures else 0
