"""`overwatch demo` - drive real traffic and inject a fault into the demo app."""

from __future__ import annotations

from cli.console import console, banner


def run_demo_command(baseline: int = 20, faulted: int = 30) -> int:
    try:
        from demo.trigger_incident import run_demo, DEMO_APP
    except ModuleNotFoundError as exc:
        console.print(f"[error]Demo dependencies are not installed.[/error] [muted]({exc.name})[/muted]")
        console.print("[muted]Install them with:  uv sync --group demo[/muted]")
        return 1

    banner("demo incident | checkout-service -> payment-gateway pool exhaustion")
    console.print(f"[muted]Target demo app: {DEMO_APP}[/muted]\n")

    try:
        delivered = run_demo(baseline=baseline, faulted=faulted)
    except Exception as exc:  # noqa: BLE001 - surface a helpful message, not a traceback
        console.print(f"\n[error]Could not reach the demo app.[/error] [muted]{type(exc).__name__}[/muted]")
        console.print("[muted]Start it first, in another terminal:  uv run python demo/sample_app.py[/muted]")
        return 1

    console.print()
    if delivered:
        console.print("[success]Webhook accepted - the agent is investigating.[/success]")
        console.print("[muted]Watch the dashboard at http://localhost:3000[/muted]")
    else:
        console.print("[warning]Gateway not running - webhook skipped.[/warning]")
        console.print("[muted]Telemetry still reached SigNoz. In 1-2 min, investigate it live:[/muted]")
        console.print("[info]  overwatch eval --live --only checkout-pool-exhaustion[/info]")
    return 0
