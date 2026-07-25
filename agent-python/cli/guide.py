"""
In-CLI guidance - what this thing is, how to run it, and what to do when it
breaks, without leaving the terminal for the README.

Scenario list is pulled live from eval.scenarios so it can never drift from the
actual benchmark.
"""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from cli.console import console


# Single logical lines - let Rich handle wrapping to the terminal width.
_WHAT_IT_IS = (
    "Over-Watch investigates production incidents the way a senior on-call engineer would: "
    "it forms hypotheses, tests them against [info]real SigNoz telemetry[/info] (traces, logs, "
    "metrics) through the SigNoz MCP server, and writes an evidence-backed root cause "
    "analysis - citing exact trace IDs and log lines, never guessing."
    "\n\n"
    "It also checks its own [info]runbooks and incident memory[/info] first, so a failure it "
    "has seen before is recognised instantly, and delivers the finished report to Slack or "
    "Telegram."
)

_QUICKSTART = [
    ("1", "overwatch doctor", "Check your setup. Start here."),
    ("2", "overwatch eval", "Run the benchmark on built-in fixtures (no SigNoz needed)."),
    ("3", "overwatch demo", "Drive real traffic + inject a fault into the demo app."),
    ("4", "overwatch eval --live", "Investigate real SigNoz telemetry."),
    ("5", "overwatch worker", "Consume incidents from RabbitMQ (full pipeline)."),
]

_TROUBLESHOOTING = [
    ("Agent used MOCK data",
     "SigNoz MCP was unreachable. Run `overwatch doctor --deep` for the real reason."),
    ("403 / 'only viewers, editors, admins'",
     "The SigNoz service-account key has no role. Give it Editor or Admin."),
    ("MCP 'Connection closed'",
     "Docker isn't running, or the image isn't pulled: docker pull signoz/signoz-mcp-server:latest"),
    ("Rate limit (429) during eval",
     "Low tokens-per-minute tier. The runner already retries; add --pace 8 for more headroom."),
    ("Judge scored by 'keyword' not 'judge'",
     "EVAL_JUDGE_MODEL isn't a model your key can access. Set it to one that is."),
    ("Empty results / no services in SigNoz",
     "Telemetry is older than the query window. Re-run `overwatch demo`."),
]


def show_guide() -> None:
    console.print()
    console.print(Panel(_WHAT_IT_IS, title="[heading]What Over-Watch does[/heading]",
                        border_style="cyan", padding=(1, 2)))

    # Quick start
    console.print()
    console.print("[heading]Getting started[/heading]")
    qs = Table(show_header=False, box=None, padding=(0, 2))
    qs.add_column("", style="muted", width=3)
    qs.add_column("", style="info", no_wrap=True)
    qs.add_column("", style="muted")
    for step, cmd, why in _QUICKSTART:
        qs.add_row(step, cmd, why)
    console.print(qs)

    # Scenarios - pulled live so this can't drift from the benchmark.
    console.print()
    console.print("[heading]Benchmark scenarios[/heading] [muted](each has a planted red herring)[/muted]")
    try:
        from eval.scenarios import SCENARIOS
        sc = Table(show_header=True, header_style="info", box=None, padding=(0, 2))
        sc.add_column("id", style="accent", no_wrap=True)
        sc.add_column("tests", style="muted", overflow="fold")
        for s in SCENARIOS:
            sc.add_row(s.id, s.title)
        console.print(sc)
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [warning]could not load scenarios: {exc}[/warning]")

    # Troubleshooting
    console.print()
    console.print("[heading]Troubleshooting[/heading]")
    tb = Table(show_header=False, box=None, padding=(0, 2))
    tb.add_column("", style="warning", overflow="fold")
    tb.add_column("", style="muted", overflow="fold")
    for symptom, fix in _TROUBLESHOOTING:
        tb.add_row(symptom, fix)
    console.print(tb)

    console.print()
    console.print("[muted]Full docs: README.md | ARCHITECTURE.md | SETUP-LIVE.md[/muted]")
    console.print()
