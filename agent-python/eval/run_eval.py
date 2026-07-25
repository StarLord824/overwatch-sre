"""
Over-Watch evaluation runner.

Runs the real Investigator agent against each injected-incident scenario and
prints a scorecard: RCA accuracy, evidence recall, red-herring resistance, cost,
and efficiency. This is the number you put on stage:

    "Over-Watch root-caused 9/10 injected incidents, ignored every red herring,
     at $0.04 and 6 LLM calls each."

Usage:
    uv run python -m eval.run_eval                 # all scenarios (needs OPENAI_API_KEY)
    uv run python -m eval.run_eval --only cache-stampede
    uv run python -m eval.run_eval --list          # list scenario ids, no LLM needed
    uv run python -m eval.run_eval --dry-run       # validate fixtures/scoring, no LLM

By default SigNoz is the injected scenario telemetry (deterministic, no Docker).
Pass --live to investigate against a real SigNoz MCP server instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

from eval.scenarios import SCENARIOS, Scenario
from eval.session import ScenarioSigNoz
from eval.scorer import Scorecard, ScenarioResult, score_run

_OUT = Path(__file__).parent / "last_scorecard.json"


def _is_transient(err: str) -> bool:
    return any(s in err for s in ("RateLimit", "429", "Timeout", "APIConnection", "InternalServer"))


async def _run_one(scenario: Scenario, live: bool, use_judge: bool) -> ScenarioResult:
    # Imported lazily so --list / --dry-run work without openai installed.
    from agent.loop import Investigator

    events: list[dict] = []
    error = ""
    report: dict = {}
    agent = None

    # Retry the whole scenario a couple of times on transient (rate-limit) errors
    # so infra hiccups don't get scored as wrong root causes.
    for attempt in range(3):
        events = []
        signoz = None if live else ScenarioSigNoz(scenario.telemetry)
        agent = Investigator(emit=events.append, signoz=signoz)
        error = ""
        try:
            report = await agent.investigate(scenario.alert)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        if not error or not _is_transient(error):
            break
        wait = 15 * (attempt + 1)
        print(f"    (transient error, retrying in {wait}s: {error[:80]})", flush=True)
        await asyncio.sleep(wait)

    tool_events = [e for e in events if e.get("type") == "tool_call"]
    tool_names = [e.get("data", {}).get("tool", "") for e in tool_events]
    run_meta = {
        "llm_calls": agent.cost.call_count,
        "tool_calls": len(tool_events),
        "cost_usd": agent.cost.total_cost,
        "used_memory": any(t == "recall_similar_incidents" for t in tool_names),
        "used_runbook": any(t == "search_runbooks" for t in tool_names),
        "error": error,
    }

    verdict = None
    if use_judge and not error:
        from eval.judge import judge_report
        verdict = await judge_report(scenario, report)

    return score_run(scenario, report, run_meta, judge=verdict)


async def _run_all(scenarios: list[Scenario], live: bool, use_judge: bool,
                   trials: int, pace: float) -> list[Scorecard]:
    """Run every scenario `trials` times; return one Scorecard per trial."""
    cards: list[Scorecard] = []
    first = True
    for t in range(1, trials + 1):
        results: list[ScenarioResult] = []
        for i, sc in enumerate(scenarios, 1):
            # Pace requests to stay under low tokens-per-minute tiers.
            if not first and pace > 0:
                await asyncio.sleep(pace)
            first = False
            tag = f"trial {t}/{trials} | " if trials > 1 else ""
            print(f"[{tag}{i}/{len(scenarios)}] investigating: {sc.id} ...", flush=True)
            results.append(await _run_one(sc, live, use_judge))
        cards.append(Scorecard(results))
    return cards


# -- output --------------------------------------------------------------------

def _print_scorecard(card: Scorecard) -> None:
    print("\n" + "=" * 82)
    print(" OVER-WATCH RCA BENCHMARK - SCORECARD")
    print("=" * 82)
    print(f"{'scenario':28} {'RCA':4} {'herr':5} {'ev':5} {'rub':5} {'llm':4} {'$cost':8} {'by':7}")
    print("-" * 82)
    for r in card.results:
        rca = "PASS" if r.root_cause_correct else "FAIL"
        herr = "ok" if r.herring_resisted else "FOOL"
        print(
            f"{r.scenario_id:28} {rca:4} {herr:5} "
            f"{r.evidence_recall:<5.2f} {r.rubric_score:<5.2f} {r.llm_calls:<4} "
            f"${r.cost_usd:<7.4f} {r.scored_by:7}"
        )
        if r.error:
            print(f"    ! error: {r.error}")
        elif r.scored_by == "judge" and not r.class_correct:
            print(f"    | predicted class '{r.predicted_class}' (expected the scenario's true class)")
        elif r.scored_by == "keyword" and r.missing_expected:
            print(f"    | missing expected terms: {', '.join(r.missing_expected)}")
    print("-" * 82)
    s = card.to_dict()["summary"]
    n_correct = sum(r.root_cause_correct for r in card.results)
    print(f" Scored by          : {s['scored_by']}  (judge = closed-vocab class match; keyword = fallback)")
    print(f" RCA accuracy       : {s['rca_accuracy']*100:.0f}%  ({n_correct}/{card.n})")
    print(f" Full pass rate     : {s['pass_rate']*100:.0f}%  (correct AND herring-resistant)")
    print(f" Evidence recall    : {s['mean_evidence_recall']*100:.0f}% (mean)")
    if s["scored_by"] == "judge":
        print(f" Rubric score       : {s['mean_rubric_score']*100:.0f}% (judge rubric points satisfied)")
    print(f" Herring resistance : {s['herring_resistance']*100:.0f}%")
    print(f" Cost / incident    : ${s['mean_cost_usd']:.4f}  (total ${s['total_cost_usd']:.4f})")
    print(f" LLM calls / inc.   : {s['mean_llm_calls']}")
    print(" By category        :")
    for cat, stat in card.by_category().items():
        print(f"    {cat:24} acc {stat['accuracy']*100:.0f}%  pass {stat['pass_rate']*100:.0f}%  (n={stat['n']})")
    print("=" * 82)
    # If the judge was requested but silently fell back to keywords, say why -
    # keyword scoring is brittle, so the user should know it wasn't the judge.
    if card.scored_by == "keyword":
        reason = next((r.judge_reasoning for r in card.results if r.judge_reasoning), "")
        if reason:
            print(f" ! judge unavailable -> scored by KEYWORD fallback. Reason: {reason}")
            print("   Set EVAL_JUDGE_MODEL to a model your key can access (e.g. gpt-4.1) for robust scoring.")


def _print_variance(cards: list[Scorecard]) -> None:
    """When trials > 1, report the mean and spread - a single run isn't a number."""
    accs = [c.accuracy for c in cards]
    passes = [c.pass_rate for c in cards]
    costs = [c.total_cost for c in cards]
    mean = statistics.mean
    stdev = statistics.pstdev
    print("\n" + "#" * 82)
    print(f" VARIANCE ACROSS {len(cards)} TRIALS  (LLMs are nondeterministic - this is the honest number)")
    print("#" * 82)
    print(f" RCA accuracy : mean {mean(accs)*100:.0f}%  +/- {stdev(accs)*100:.0f}pp   per-trial {[f'{a*100:.0f}%' for a in accs]}")
    print(f" Pass rate    : mean {mean(passes)*100:.0f}%  +/- {stdev(passes)*100:.0f}pp   per-trial {[f'{p*100:.0f}%' for p in passes]}")
    print(f" Total cost   : mean ${mean(costs):.4f} per trial")
    print("#" * 82)


def main() -> None:
    parser = argparse.ArgumentParser(description="Over-Watch RCA benchmark")
    parser.add_argument("--only", help="run a single scenario by id")
    parser.add_argument("--list", action="store_true", help="list scenario ids and exit")
    parser.add_argument("--dry-run", action="store_true", help="validate fixtures + scoring wiring without calling the LLM")
    parser.add_argument("--live", action="store_true", help="investigate against a real SigNoz MCP server instead of injected fixtures")
    parser.add_argument("--trials", type=int, default=1, help="run each scenario N times and report variance (default 1)")
    parser.add_argument("--no-judge", action="store_true", help="disable the LLM judge; score by keywords only")
    parser.add_argument("--pace", type=float, default=6.0, help="seconds to wait between scenarios to avoid rate limits (default 6)")
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.only:
        scenarios = [s for s in SCENARIOS if s.id == args.only]
        if not scenarios:
            print(f"No scenario '{args.only}'. Known: {[s.id for s in SCENARIOS]}")
            sys.exit(1)

    if args.list:
        for s in SCENARIOS:
            print(f"{s.id:28} - {s.title}")
        return

    if args.dry_run:
        _dry_run(scenarios)
        return

    cards = asyncio.run(_run_all(
        scenarios, live=args.live, use_judge=not args.no_judge,
        trials=max(1, args.trials), pace=args.pace,
    ))

    # Persist the last trial's full detail; print each trial + variance.
    _OUT.write_text(json.dumps(cards[-1].to_dict(), indent=2), encoding="utf-8")
    for i, card in enumerate(cards, 1):
        if len(cards) > 1:
            print(f"\n----- trial {i}/{len(cards)} -----")
        _print_scorecard(card)
    if len(cards) > 1:
        _print_variance(cards)
    print(f"\nscorecard (last trial) written to {_OUT}")


def _dry_run(scenarios: list[Scenario]) -> None:
    """
    Validate the harness without any LLM: feed each scenario's own ground-truth
    'evidence' text through the scorer as a perfect report, and confirm it scores
    as PASS. Also sanity-check that a report naming the red herring is caught.
    """
    print("DRY RUN - validating fixtures + scorer (no LLM calls)\n")
    ok = True
    for sc in scenarios:
        perfect = {
            "root_cause": " ".join(sc.expected_keywords),
            "summary": "",
            "report_md": " ".join(sc.expected_keywords + sc.required_evidence),
            "evidence": sc.required_evidence,
            "confidence": "HIGH",
            "signoz_live": True,
        }
        good = score_run(sc, perfect, {"llm_calls": 0, "tool_calls": 0, "cost_usd": 0.0})

        herring_report = dict(perfect)
        if sc.forbidden_keywords:
            herring_report["root_cause"] = sc.forbidden_keywords[0]
        fooled = score_run(sc, herring_report, {})

        status = "OK" if (good.passed and good.evidence_recall == 1.0) else "BROKEN"
        herr_status = "OK" if (not sc.forbidden_keywords or not fooled.herring_resisted) else "BROKEN"
        if status != "OK" or herr_status != "OK":
            ok = False
        print(f"  {sc.id:28} perfect->{status:6} herring-detect->{herr_status}")
    print("\n" + ("PASS: harness wiring is sound." if ok else "FAIL: harness has a scoring bug."))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
