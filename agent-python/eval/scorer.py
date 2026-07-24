"""
Scoring for the eval harness.

Given a scenario's ground truth and the agent's produced report (+ run metrics),
compute a per-scenario score:

  root_cause_correct  — did ALL expected_keywords appear anywhere in the report?
  evidence_recall     — fraction of required_evidence tokens the report surfaced
  herring_resisted    — did the CONCLUDED root cause avoid the red-herring tokens?
  passed              — correct AND herring resisted (the headline pass/fail)

Correctness uses the LLM judge's closed-vocabulary class match when a judge
verdict is supplied (robust, hard to game); otherwise it falls back to
case-insensitive keyword matching (transparent, zero-cost, reproducible). Both
signals are always recorded so the scorecard shows how correctness was decided.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    root_cause_correct: bool
    evidence_recall: float
    herring_resisted: bool
    llm_calls: int
    tool_calls: int
    cost_usd: float
    used_memory: bool
    used_runbook: bool
    signoz_live: bool
    reported_confidence: str
    error: str = ""
    missing_expected: list[str] = field(default_factory=list)
    # Judge / classification signals.
    category: str = ""
    scored_by: str = "keyword"          # "judge" or "keyword"
    keyword_correct: bool = False       # raw keyword signal, always recorded
    predicted_class: str = ""
    class_correct: bool = False
    rubric_score: float = 0.0
    judge_reasoning: str = ""

    @property
    def passed(self) -> bool:
        return self.root_cause_correct and self.herring_resisted and not self.error


def _contains_all(haystack: str, needles: list[str]) -> tuple[bool, list[str]]:
    hay = haystack.lower()
    missing = [n for n in needles if n.lower() not in hay]
    return (len(missing) == 0, missing)


def _recall(haystack: str, needles: list[str]) -> float:
    if not needles:
        return 1.0
    hay = haystack.lower()
    hit = sum(1 for n in needles if n.lower() in hay)
    return hit / len(needles)


def score_run(scenario, report: dict, run_meta: dict, judge=None) -> ScenarioResult:
    """
    scenario  — a Scenario (ground truth)
    report    — the Investigator's final report dict (root_cause, report_md, ...)
    run_meta  — {llm_calls, tool_calls, cost_usd, used_memory, used_runbook, error}
    judge     — an optional JudgeVerdict; when available & valid it decides correctness
    """
    error = run_meta.get("error", "")
    report_text = " ".join([
        report.get("report_md", ""),
        report.get("root_cause", ""),
        report.get("summary", ""),
        " ".join(report.get("evidence", []) or []),
    ])
    conclusion = report.get("root_cause", "")

    keyword_correct, missing = _contains_all(report_text, scenario.expected_keywords)
    recall = _recall(report_text, scenario.required_evidence)
    # Fooled if any forbidden token shows up in the CONCLUDED root cause.
    fooled = any(f.lower() in conclusion.lower() for f in scenario.forbidden_keywords)

    # Decide correctness: judge (class match) when available, else keyword.
    judge_available = bool(judge and getattr(judge, "available", False))
    if judge_available:
        scored_by = "judge"
        correct = judge.class_correct
        predicted_class = judge.predicted_class
        class_correct = judge.class_correct
        rubric_score = round(judge.rubric_score, 2)
        judge_reasoning = judge.reasoning
    else:
        scored_by = "keyword"
        correct = keyword_correct
        predicted_class = ""
        class_correct = False
        rubric_score = 0.0
        judge_reasoning = getattr(judge, "reasoning", "") if judge else ""

    return ScenarioResult(
        scenario_id=scenario.id,
        title=scenario.title,
        root_cause_correct=correct and not error,
        evidence_recall=round(recall, 2),
        herring_resisted=not fooled,
        llm_calls=run_meta.get("llm_calls", 0),
        tool_calls=run_meta.get("tool_calls", 0),
        cost_usd=round(run_meta.get("cost_usd", 0.0), 5),
        used_memory=run_meta.get("used_memory", False),
        used_runbook=run_meta.get("used_runbook", False),
        signoz_live=report.get("signoz_live", False),
        reported_confidence=report.get("confidence", ""),
        error=error,
        missing_expected=missing,
        category=getattr(scenario, "category", ""),
        scored_by=scored_by,
        keyword_correct=keyword_correct,
        predicted_class=predicted_class,
        class_correct=class_correct,
        rubric_score=rubric_score,
        judge_reasoning=judge_reasoning,
    )


@dataclass
class Scorecard:
    results: list[ScenarioResult]

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.root_cause_correct for r in self.results) / self.n

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.passed for r in self.results) / self.n

    @property
    def mean_evidence_recall(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.evidence_recall for r in self.results) / self.n

    @property
    def herring_resistance(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.herring_resisted for r in self.results) / self.n

    @property
    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.results), 5)

    @property
    def mean_cost(self) -> float:
        if not self.results:
            return 0.0
        return round(self.total_cost / self.n, 5)

    @property
    def mean_llm_calls(self) -> float:
        if not self.results:
            return 0.0
        return round(sum(r.llm_calls for r in self.results) / self.n, 1)

    @property
    def mean_rubric_score(self) -> float:
        judged = [r for r in self.results if r.scored_by == "judge"]
        if not judged:
            return 0.0
        return round(sum(r.rubric_score for r in judged) / len(judged), 3)

    @property
    def scored_by(self) -> str:
        return "judge" if any(r.scored_by == "judge" for r in self.results) else "keyword"

    def by_category(self) -> dict[str, dict]:
        cats: dict[str, list[ScenarioResult]] = {}
        for r in self.results:
            cats.setdefault(r.category or "uncategorized", []).append(r)
        out: dict[str, dict] = {}
        for cat, rs in cats.items():
            out[cat] = {
                "n": len(rs),
                "accuracy": round(sum(x.root_cause_correct for x in rs) / len(rs), 3),
                "pass_rate": round(sum(x.passed for x in rs) / len(rs), 3),
            }
        return out

    def to_dict(self) -> dict:
        return {
            "summary": {
                "scenarios": self.n,
                "scored_by": self.scored_by,
                "rca_accuracy": round(self.accuracy, 3),
                "pass_rate": round(self.pass_rate, 3),
                "mean_evidence_recall": round(self.mean_evidence_recall, 3),
                "mean_rubric_score": self.mean_rubric_score,
                "herring_resistance": round(self.herring_resistance, 3),
                "mean_cost_usd": self.mean_cost,
                "total_cost_usd": self.total_cost,
                "mean_llm_calls": self.mean_llm_calls,
            },
            "by_category": self.by_category(),
            "results": [r.__dict__ for r in self.results],
        }
