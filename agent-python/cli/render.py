"""
Rich rendering for benchmark results.

The eval package keeps its plain-text output (so `python -m eval.run_eval` is
unchanged); this module renders the same Scorecard objects for the CLI.
"""

from __future__ import annotations

import statistics

from rich.panel import Panel
from rich.table import Table

from cli.console import console


def render_scorecard(card, title: str = "RCA Benchmark") -> None:
    table = Table(show_header=True, header_style="info", box=None, padding=(0, 2))
    table.add_column("scenario", style="heading", no_wrap=True)
    table.add_column("RCA", justify="center")
    table.add_column("herring", justify="center")
    table.add_column("evidence", justify="right")
    table.add_column("rubric", justify="right")
    table.add_column("llm", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("by", style="muted")

    for r in card.results:
        rca = "[success]PASS[/success]" if r.root_cause_correct else "[error]FAIL[/error]"
        herr = "[success]ok[/success]" if r.herring_resisted else "[error]FOOLED[/error]"
        table.add_row(
            r.scenario_id, rca, herr,
            f"{r.evidence_recall:.2f}",
            f"{r.rubric_score:.2f}",
            str(r.llm_calls),
            f"${r.cost_usd:.4f}",
            r.scored_by,
        )
    console.print()
    console.print(table)

    # Per-scenario notes (errors, wrong class, missing terms).
    for r in card.results:
        if r.error:
            console.print(f"  [error]{r.scenario_id}[/error] [muted]{r.error}[/muted]")
        elif r.scored_by == "judge" and not r.class_correct:
            console.print(f"  [warning]{r.scenario_id}[/warning] [muted]predicted class '{r.predicted_class}'[/muted]")
        elif r.scored_by == "keyword" and r.missing_expected:
            console.print(f"  [warning]{r.scenario_id}[/warning] [muted]missing: {', '.join(r.missing_expected)}[/muted]")

    s = card.to_dict()["summary"]
    n_correct = sum(r.root_cause_correct for r in card.results)

    def pct(v: float) -> str:
        colour = "success" if v >= 0.999 else ("warning" if v >= 0.5 else "error")
        return f"[{colour}]{v * 100:.0f}%[/{colour}]"

    lines = [
        f"RCA accuracy        {pct(s['rca_accuracy'])}   [muted]({n_correct}/{card.n})[/muted]",
        f"Full pass rate      {pct(s['pass_rate'])}   [muted](correct AND herring-resistant)[/muted]",
        f"Evidence recall     {pct(s['mean_evidence_recall'])}",
    ]
    if s["scored_by"] == "judge":
        lines.append(f"Rubric score        {pct(s['mean_rubric_score'])}")
    lines += [
        f"Herring resistance  {pct(s['herring_resistance'])}",
        f"Cost per incident   [info]${s['mean_cost_usd']:.4f}[/info]   [muted](total ${s['total_cost_usd']:.4f})[/muted]",
        f"LLM calls per inc.  [info]{s['mean_llm_calls']}[/info]",
        f"Scored by           [info]{s['scored_by']}[/info]",
    ]
    console.print()
    console.print(Panel("\n".join(lines), title=f"[heading]{title}[/heading]",
                        border_style="cyan", padding=(1, 2)))

    by_cat = card.by_category()
    if len(by_cat) > 1:
        ct = Table(show_header=True, header_style="info", box=None, padding=(0, 2))
        ct.add_column("category", style="accent")
        ct.add_column("accuracy", justify="right")
        ct.add_column("pass", justify="right")
        ct.add_column("n", justify="right", style="muted")
        for cat, stat in by_cat.items():
            ct.add_row(cat, f"{stat['accuracy']*100:.0f}%", f"{stat['pass_rate']*100:.0f}%", str(stat["n"]))
        console.print(ct)

    if card.scored_by == "keyword":
        reason = next((r.judge_reasoning for r in card.results if r.judge_reasoning), "")
        if reason:
            console.print()
            console.print(f"[warning]Judge unavailable - scored by keyword fallback.[/warning] [muted]{reason}[/muted]")
            console.print("[muted]Set EVAL_JUDGE_MODEL to a model your key can access for robust scoring.[/muted]")


def render_variance(cards: list) -> None:
    """Mean +/- spread across trials - a single LLM run is not a number."""
    accs = [c.accuracy for c in cards]
    passes = [c.pass_rate for c in cards]
    costs = [c.total_cost for c in cards]
    body = (
        f"RCA accuracy   [info]{statistics.mean(accs)*100:.0f}%[/info] "
        f"[muted]+/- {statistics.pstdev(accs)*100:.0f}pp[/muted]   "
        f"[muted]{[f'{a*100:.0f}%' for a in accs]}[/muted]\n"
        f"Pass rate      [info]{statistics.mean(passes)*100:.0f}%[/info] "
        f"[muted]+/- {statistics.pstdev(passes)*100:.0f}pp[/muted]   "
        f"[muted]{[f'{p*100:.0f}%' for p in passes]}[/muted]\n"
        f"Cost / trial   [info]${statistics.mean(costs):.4f}[/info]"
    )
    console.print()
    console.print(Panel(
        body,
        title=f"[heading]Variance across {len(cards)} trials[/heading]",
        subtitle="[muted]LLMs are nondeterministic - this is the honest number[/muted]",
        border_style="magenta", padding=(1, 2),
    ))
