"""
Preflight connectivity test for the SigNoz MCP server.

Run this BEFORE `--live` to confirm the agent can actually reach SigNoz through
the MCP server - so you're not debugging a full investigation to discover the
connection is down.

    uv run python -m signoz_mcp.smoke

Exit code 0 = live MCP connection established; 1 = fell back to mock (not connected).
"""

from __future__ import annotations

import asyncio
import sys

from config import (
    SIGNOZ_URL,
    SIGNOZ_MCP_MODE,
    SIGNOZ_MCP_IMAGE,
    signoz_mcp_launch,
)
from signoz_mcp import SigNozMCP


async def main() -> int:
    command, args, _ = signoz_mcp_launch()
    print("SigNoz MCP preflight")
    print("-" * 60)
    print(f"  mode        : {SIGNOZ_MCP_MODE}")
    print(f"  SIGNOZ_URL  : {SIGNOZ_URL}")
    if SIGNOZ_MCP_MODE == "docker":
        print(f"  image       : {SIGNOZ_MCP_IMAGE}")
    # Redact any API-key value in the launch line before printing it.
    safe_args = [
        "SIGNOZ_API_KEY=***redacted***" if a.startswith("SIGNOZ_API_KEY=") else a
        for a in args
    ]
    print(f"  launch      : {command} {' '.join(safe_args)}")
    print("-" * 60)
    print("Connecting (this spawns the MCP server over stdio)...\n")

    sig = SigNozMCP()
    async with sig.session() as s:
        if not s.live:
            print("x NOT connected - the agent fell back to MOCK data.")
            print("\nCheck:")
            print("  * Is SigNoz running and reachable at SIGNOZ_URL?")
            print("  * For docker mode + host SigNoz, SIGNOZ_URL should resolve from")
            print("    inside the container (localhost is auto-rewritten to")
            print("    host.docker.internal).")
            print("  * Did you `docker pull` the MCP image? Is SIGNOZ_API_KEY set?")
            print("  * Try SIGNOZ_MCP_MODE=binary with SIGNOZ_MCP_BINARY if docker is the issue.")
            return 1

        print(f"v Connected. MCP exposes {len(s.tool_names)} tools.")
        interesting = [t for t in s.tool_names if t in {
            "signoz_list_services", "signoz_search_traces", "signoz_search_logs",
            "signoz_query_metrics", "signoz_list_alerts", "signoz_get_trace_details",
        }]
        print(f"  tools we use: {', '.join(interesting) or '(none of our expected tools found!)'}")

        print("\nCalling signoz_list_services (timeRange=1h)...")
        result = await s.call("signoz_list_services", {"timeRange": "1h"})
        preview = result[:800]
        print(preview + ("\n...(truncated)" if len(result) > 800 else ""))

        # Connection can succeed while the API call is still rejected (e.g. the
        # service-account key has no role). Detect that instead of claiming success.
        lowered = result.lower()
        if any(m in lowered for m in ("unexpected status 4", "unexpected status 5",
                                       "\"error\"", "forbidden", "unauthorized",
                                       "403", "401")):
            print("\nx Connected to the MCP server, but the SigNoz API rejected the query.")
            print("  Most likely the service-account key needs a role. Set it to EDITOR")
            print("  or ADMIN (Editor+ is required for the agent's signoz_create_alert).")
            return 2

        print("\nv Live SigNoz telemetry is reachable. You're clear to run --live.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
