"""
Dump the REAL input schemas the SigNoz MCP server exposes for its tools, so our
tool definitions match what the server actually expects.

    uv run python -m signoz_mcp.inspect            # all 41 tools (names only)
    uv run python -m signoz_mcp.inspect alert      # full schema for alert tools
    uv run python -m signoz_mcp.inspect create     # full schema for create_* tools

Use this when a tool call silently does nothing (e.g. signoz_create_alert not
actually creating an alert) - the printed inputSchema tells us the true params.
"""

from __future__ import annotations

import asyncio
import json
import sys

from config import signoz_mcp_launch


async def main() -> None:
    filt = (sys.argv[1] if len(sys.argv) > 1 else "").lower()

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cmd, args, env = signoz_mcp_launch()
    params = StdioServerParameters(command=cmd, args=args, env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            matches = [t for t in tools.tools if not filt or filt in t.name.lower()]

            if not filt:
                print(f"{len(tools.tools)} tools available:\n")
                for t in tools.tools:
                    print(f"  {t.name}")
                print("\nRe-run with a filter (e.g. 'alert') to see full schemas.")
                return

            print(f"{len(matches)} tool(s) matching '{filt}':\n")
            for t in matches:
                print("=" * 70)
                print(t.name)
                if t.description:
                    print(t.description.strip()[:300])
                print("-" * 70)
                print(json.dumps(t.inputSchema, indent=2))
                print()


if __name__ == "__main__":
    asyncio.run(main())
