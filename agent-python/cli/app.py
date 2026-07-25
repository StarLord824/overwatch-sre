"""
Over-Watch CLI - one entry point for the whole system.

    overwatch                 interactive menu
    overwatch doctor          check the setup
    overwatch eval            run the RCA benchmark
    overwatch demo            trigger a demo incident
    overwatch worker          consume incidents from RabbitMQ
    overwatch guide           how it all fits together

Each subcommand is a thin wrapper over the same functions the underlying
scripts use, so `python -m eval.run_eval` and friends keep working unchanged.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
    # ASCII-only: Typer help bypasses Rich's encoding handling and mangles
    # non-ASCII punctuation on Windows terminals (cp1252).
    help="Over-Watch - autonomous SRE investigation agent for SigNoz.",
)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Run with no arguments for an interactive menu."""
    if ctx.invoked_subcommand is None:
        from cli.menu import run_menu
        raise typer.Exit(run_menu())


@app.command()
def doctor(
    deep: bool = typer.Option(
        False, "--deep",
        help="Also spawn the SigNoz MCP server and run a live query (slower).",
    ),
) -> None:
    """Check your environment and report exactly what's broken."""
    from cli.console import banner
    from cli.doctor import run_checks, render

    banner("preflight diagnostics")
    raise typer.Exit(render(run_checks(deep=deep)))


@app.command("eval")
def eval_cmd(
    only: str = typer.Option(None, "--only", help="Run a single scenario by id."),
    live: bool = typer.Option(False, "--live", help="Investigate real SigNoz telemetry instead of fixtures."),
    trials: int = typer.Option(1, "--trials", help="Repeat the suite N times and report variance."),
    no_judge: bool = typer.Option(False, "--no-judge", help="Score by keywords only, skipping the LLM judge."),
    pace: float = typer.Option(6.0, "--pace", help="Seconds between scenarios (avoids rate limits)."),
    list_scenarios: bool = typer.Option(False, "--list", help="List the scenarios and exit."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate fixtures and scoring without calling the LLM."),
) -> None:
    """Run the RCA benchmark and print a scorecard."""
    from cli.commands.eval_cmd import run_eval_command
    raise typer.Exit(run_eval_command(
        only=only, live=live, trials=trials, no_judge=no_judge,
        pace=pace, list_only=list_scenarios, dry_run=dry_run,
    ))


@app.command()
def demo(
    baseline: int = typer.Option(20, "--baseline", help="Healthy requests to send first."),
    faulted: int = typer.Option(30, "--faulted", help="Requests to send after injecting the fault."),
) -> None:
    """Drive real traffic through the demo app and inject a fault."""
    from cli.commands.demo_cmd import run_demo_command
    raise typer.Exit(run_demo_command(baseline=baseline, faulted=faulted))


@app.command()
def worker() -> None:
    """Consume incidents from RabbitMQ and investigate them."""
    from cli.commands.worker_cmd import run_worker_command
    raise typer.Exit(run_worker_command())


@app.command()
def guide() -> None:
    """Explain what Over-Watch does, how to run it, and how to fix problems."""
    from cli.guide import show_guide
    show_guide()


if __name__ == "__main__":
    app()
