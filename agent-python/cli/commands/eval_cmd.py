"""`overwatch eval` - run the RCA benchmark with Rich output."""

from __future__ import annotations

import asyncio
import json

from cli.console import console, banner
from cli.render import render_scorecard, render_variance


def run_eval_command(
    only: str | None = None,
    live: bool = False,
    trials: int = 1,
    no_judge: bool = False,
    pace: float = 6.0,
    list_only: bool = False,
    dry_run: bool = False,
) -> int:
    from eval.scenarios import SCENARIOS
    from eval.run_eval import _run_all, _dry_run, _OUT
    from eval.scorer import Scorecard  # noqa: F401  (type clarity)

    scenarios = SCENARIOS
    if only:
        scenarios = [s for s in SCENARIOS if s.id == only]
        if not scenarios:
            console.print(f"[error]No scenario '{only}'.[/error]")
            console.print(f"[muted]Known: {', '.join(s.id for s in SCENARIOS)}[/muted]")
            return 1

    if list_only:
        from rich.table import Table
        t = Table(show_header=True, header_style="info", box=None, padding=(0, 2))
        t.add_column("id", style="accent", no_wrap=True)
        t.add_column("tests", style="muted", overflow="fold")
        for s in SCENARIOS:
            t.add_row(s.id, s.title)
        console.print()
        console.print(t)
        console.print()
        return 0

    if dry_run:
        console.print("[muted]Validating fixtures and scorer (no LLM calls)...[/muted]\n")
        _dry_run(scenarios)
        return 0

    mode = "[warning]LIVE SigNoz[/warning]" if live else "[info]injected fixtures[/info]"
    banner(f"benchmark | {len(scenarios)} scenario(s) | {trials} trial(s) | {mode}")

    with console.status("[info]investigating...[/info]", spinner="dots"):
        cards = asyncio.run(_run_all(
            scenarios, live=live, use_judge=not no_judge,
            trials=max(1, trials), pace=pace,
        ))

    _OUT.write_text(json.dumps(cards[-1].to_dict(), indent=2), encoding="utf-8")

    for i, card in enumerate(cards, 1):
        title = "RCA Benchmark" if len(cards) == 1 else f"RCA Benchmark - trial {i}/{len(cards)}"
        render_scorecard(card, title=title)
    if len(cards) > 1:
        render_variance(cards)

    console.print(f"\n[muted]Scorecard written to {_OUT}[/muted]")
    return 0
