"""
Centralized configuration for the Over-Watch agent brain.

Everything the agent needs to know about its environment lives here so the rest
of the codebase never touches os.getenv directly.
"""

from __future__ import annotations

import os
import shlex

from dotenv import load_dotenv

load_dotenv()


# ── LLM ───────────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")


def model_supports_temperature(model: str) -> bool:
    """
    GPT-5 / o-series / Codex reasoning models reject a custom `temperature`
    (only the default is allowed) and error out. Detect those so callers can
    omit the parameter instead of crashing.
    """
    m = (model or "").lower()
    reasoning_prefixes = ("gpt-5", "o1", "o3", "o4")
    return not (m.startswith(reasoning_prefixes) or "codex" in m)

# ── SigNoz MCP ────────────────────────────────────────────────────────────────
SIGNOZ_URL: str = os.getenv("SIGNOZ_URL", "http://localhost:3301")
SIGNOZ_API_KEY: str = os.getenv("SIGNOZ_API_KEY", "")

SIGNOZ_MCP_MODE: str = os.getenv("SIGNOZ_MCP_MODE", "docker").lower()
SIGNOZ_MCP_IMAGE: str = os.getenv("SIGNOZ_MCP_IMAGE", "signoz/signoz-mcp-server:latest")
SIGNOZ_MCP_BINARY: str = os.getenv("SIGNOZ_MCP_BINARY", "signoz-mcp-server")

# ── Infrastructure ────────────────────────────────────────────────────────────
RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

QUEUE_NAME: str = "incidents_queue"
REDIS_CHANNEL: str = "agent_updates"


def signoz_mcp_launch() -> tuple[str, list[str], dict[str, str]]:
    """
    Build the (command, args, env) used to spawn the SigNoz MCP server over stdio.

    In "docker" mode we run the official image with the API key/URL forwarded as
    env vars. In "binary" mode we exec the downloaded server directly. An explicit
    SIGNOZ_MCP_COMMAND override always wins (handy for custom wrappers).
    """
    override = os.getenv("SIGNOZ_MCP_COMMAND", "").strip()
    server_env = {
        "SIGNOZ_URL": SIGNOZ_URL,
        "SIGNOZ_API_KEY": SIGNOZ_API_KEY,
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "info"),
    }

    if override:
        parts = shlex.split(override)
        return parts[0], parts[1:], server_env

    if SIGNOZ_MCP_MODE == "binary":
        return SIGNOZ_MCP_BINARY, [], server_env

    # Default: docker stdio. Pass config through with -e so the container sees it.
    # GOTCHA: from *inside* the MCP container, "localhost" is the container itself,
    # not your host. When SigNoz runs on the host, rewrite to host.docker.internal
    # so the container can actually reach it. (No-op if you already point at a real
    # host/IP or a SigNoz Cloud URL.)
    container_url = _container_reachable_url(SIGNOZ_URL)
    args = [
        "run",
        "-i",
        "--rm",
        "--add-host", "host.docker.internal:host-gateway",  # Linux parity with Docker Desktop
        "-e", f"SIGNOZ_URL={container_url}",
        "-e", f"SIGNOZ_API_KEY={SIGNOZ_API_KEY}",
        # Force stdio transport: the image may default to HTTP mode, which would
        # leave our stdio client talking to a server that isn't listening on stdin.
        "-e", "TRANSPORT_MODE=stdio",
        "-e", f"LOG_LEVEL={server_env['LOG_LEVEL']}",
        SIGNOZ_MCP_IMAGE,
    ]
    return "docker", args, server_env


def _container_reachable_url(url: str) -> str:
    """Swap host-loopback for host.docker.internal so a container can reach the host."""
    for loopback in ("localhost", "127.0.0.1", "0.0.0.0"):
        if loopback in url:
            return url.replace(loopback, "host.docker.internal")
    return url
