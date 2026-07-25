"""`overwatch worker` - consume incidents from RabbitMQ and investigate them."""

from __future__ import annotations

from cli.console import console, banner


def run_worker_command() -> int:
    from config import RABBITMQ_URL, REDIS_URL, QUEUE_NAME

    banner("worker | consuming incidents from RabbitMQ")
    console.print(f"[muted]RabbitMQ  {RABBITMQ_URL}[/muted]")
    console.print(f"[muted]Redis     {REDIS_URL}[/muted]")
    console.print(f"[muted]Queue     {QUEUE_NAME}[/muted]\n")

    try:
        from main import run_worker
        run_worker()
    except KeyboardInterrupt:
        console.print("\n[muted]Worker stopped.[/muted]")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"\n[error]Worker failed:[/error] [muted]{type(exc).__name__}: {exc}[/muted]")
        console.print("[muted]Is RabbitMQ up?  docker compose up -d   (or run: overwatch doctor)[/muted]")
        return 1
    return 0
