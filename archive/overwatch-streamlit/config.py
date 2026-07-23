"""
Overwatch configuration — single source of truth for all env vars and defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ── LLM ──────────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL: str = os.getenv("OVERWATCH_LLM_MODEL", "gpt-4o")

# ── SigNoz ───────────────────────────────────────────────────────────────────
SIGNOZ_BASE_URL: str = os.getenv("SIGNOZ_BASE_URL", "http://localhost:3301")
SIGNOZ_API_KEY: str = os.getenv("SIGNOZ_API_KEY", "")
SIGNOZ_MCP_URL: str = os.getenv("SIGNOZ_MCP_URL", "http://localhost:3001")

# ── Demo ─────────────────────────────────────────────────────────────────────
OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
)
DEMO_APP_PORT: int = int(os.getenv("DEMO_APP_PORT", "5050"))
