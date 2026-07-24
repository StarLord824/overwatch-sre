"""
LLM judge for the RCA benchmark.

Keyword matching alone is brittle: it gives false negatives (right cause, other
words) and false positives (agent parrots the alert text). Inspired by OpenSRE's
`llm_eval_judge.py` + closed-vocabulary scoring, this judge does two robust things:

  1. **Classifies** the agent's conclusion into a fixed vocabulary of causes
     (incl. the distractor classes the red herrings point at). Correctness is
     an exact class match against ground truth — hand-wavy answers can't pass.
  2. **Grades** the conclusion against the scenario's rubric (scoring points),
     returning which points were satisfied.

The judge is a separate, cheap model call (defaults to gpt-4o-mini) and is fully
optional: if no API key or the call fails, the scorer falls back to keywords.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from eval.scenarios import CLASS_VOCAB, Scenario

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")


@dataclass
class JudgeVerdict:
    predicted_class: str
    class_correct: bool
    rubric_hits: list[str] = field(default_factory=list)
    rubric_total: int = 0
    reasoning: str = ""
    available: bool = True  # False when the judge couldn't run (fallback to keywords)

    @property
    def rubric_score(self) -> float:
        return len(self.rubric_hits) / self.rubric_total if self.rubric_total else 0.0


_JUDGE_SYSTEM = """You are a strict grader for an SRE root-cause-analysis benchmark.
You are given (a) an incident, (b) a closed list of possible cause CLASSES, (c) a
grading RUBRIC, and (d) the agent's investigation report. Judge only what the
report actually concludes — do not use your own outside knowledge of the incident.

Return ONLY a JSON object (no prose, no code fences) with keys:
  "predicted_class": one string EXACTLY from the provided class list — the class
      the agent's CONCLUDED root cause best matches. If the report is vague or
      concludes nothing specific, pick the closest class but note it in reasoning.
  "rubric_hits": array of the rubric points (verbatim strings) the report satisfies.
  "reasoning": one or two sentences.
"""


def _build_user_prompt(scenario: Scenario, report: dict) -> str:
    report_text = report.get("report_md") or report.get("root_cause", "")
    return (
        f"INCIDENT: {scenario.title}\n"
        f"ALERT: {json.dumps(scenario.alert)}\n\n"
        f"CLASS LIST (choose exactly one): {list(CLASS_VOCAB)}\n\n"
        f"RUBRIC (grade each point):\n"
        + "\n".join(f"- {p}" for p in scenario.rubric)
        + "\n\nAGENT REPORT:\n"
        + report_text[:6000]
        + "\n\nReturn the JSON object now."
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    fences = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    for cand in reversed(fences):
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("judge returned no JSON object")


async def judge_report(scenario: Scenario, report: dict) -> JudgeVerdict:
    """Grade one report. Returns a fallback (available=False) if the judge can't run."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return JudgeVerdict(predicted_class="", class_correct=False, available=False,
                            reasoning="no OPENAI_API_KEY; used keyword fallback")
    try:
        from openai import AsyncOpenAI

        from config import model_supports_temperature

        client = AsyncOpenAI(api_key=api_key, max_retries=4)
        kwargs: dict = {
            "model": JUDGE_MODEL,
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": _build_user_prompt(scenario, report)},
            ],
        }
        if model_supports_temperature(JUDGE_MODEL):
            kwargs["temperature"] = 0.0
        resp = await client.chat.completions.create(**kwargs)
        data = _extract_json(resp.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        return JudgeVerdict(predicted_class="", class_correct=False, available=False,
                            reasoning=f"judge error, keyword fallback: {exc}")

    predicted = str(data.get("predicted_class", "")).strip()
    hits = [str(h) for h in data.get("rubric_hits", []) if isinstance(h, (str,))]
    # Only count rubric hits that are actually rubric points (guard against drift).
    hits = [h for h in hits if any(h.strip() == p.strip() for p in scenario.rubric)]
    return JudgeVerdict(
        predicted_class=predicted,
        class_correct=(predicted == scenario.root_cause_class),
        rubric_hits=hits,
        rubric_total=len(scenario.rubric),
        reasoning=str(data.get("reasoning", "")),
        available=True,
    )
