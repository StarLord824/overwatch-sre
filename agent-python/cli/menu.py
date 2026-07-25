"""
Interactive menu shown when `overwatch` is run with no arguments.

Every entry dispatches to the exact same function the corresponding subcommand
calls, so there is no second code path to keep in sync.
"""

from __future__ import annotations

from rich.panel import Panel
from rich.prompt import Prompt

from cli.console import console, banner

_ENTRIES = [
    ("1", "Run the benchmark", "Score the agent on built-in fixtures (no SigNoz needed)"),
    ("2", "Trigger a demo incident", "Real traffic + fault injection into the demo app"),
    ("3", "Start the worker", "Consume incidents from RabbitMQ (full pipeline)"),
    ("4", "Doctor", "Check my setup and tell me what's broken"),
    ("5", "Guide", "How this all fits together"),
    ("0", "Exit", ""),
]


def _render_menu() -> None:
    lines = []
    for key, label, desc in _ENTRIES:
        if key == "0":
            lines.append(f"  [muted]{key}[/muted]  [muted]{label}[/muted]")
        else:
            lines.append(f"  [info]{key}[/info]  [heading]{label}[/heading]\n     [muted]{desc}[/muted]")
    console.print(Panel("\n".join(lines), border_style="cyan", padding=(1, 2)))


def run_menu() -> int:
    banner("interactive mode | run `overwatch --help` for flags")

    while True:
        _render_menu()
        choice = Prompt.ask(
            "[info]Select[/info]",
            choices=[k for k, _, _ in _ENTRIES],
            default="1",
            show_choices=False,
        )

        if choice == "0":
            console.print("[muted]Bye.[/muted]")
            return 0

        try:
            if choice == "1":
                from cli.commands.eval_cmd import run_eval_command
                run_eval_command()
            elif choice == "2":
                from cli.commands.demo_cmd import run_demo_command
                run_demo_command()
            elif choice == "3":
                from cli.commands.worker_cmd import run_worker_command
                run_worker_command()
            elif choice == "4":
                from cli.doctor import run_checks, render
                render(run_checks(deep=False))
            elif choice == "5":
                from cli.guide import show_guide
                show_guide()
        except KeyboardInterrupt:
            console.print("\n[muted]Interrupted.[/muted]")

        console.print()
        again = Prompt.ask("[muted]Back to menu?[/muted]", choices=["y", "n"], default="y")
        if again == "n":
            return 0
        console.print()
