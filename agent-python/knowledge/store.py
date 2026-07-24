"""
Knowledge + Memories — the right-hand side of the OpenSRE architecture.

Two file-backed stores the agent can read and write during an investigation:

  • Knowledge (runbooks)  — human-authored markdown playbooks in ./runbooks/.
                            The agent searches these to apply your team's
                            institutional knowledge instead of reasoning from
                            scratch.
  • Memories (incidents)  — ./memory/incidents.json, an append-only log of past
                            resolved incidents. The agent recalls similar past
                            incidents at the start and writes the new one back at
                            the end, so each investigation makes the next faster.

Matching is deliberately simple (keyword / token overlap scoring) — no vector DB,
no embeddings service to stand up. Good enough to be genuinely useful in a demo
and trivial to reason about.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).parent
_RUNBOOK_DIR = _HERE / "runbooks"
_MEMORY_FILE = _HERE / "memory" / "incidents.json"

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "was", "were", "with", "at", "by", "this", "that", "it", "as", "from",
    "error", "service", "alert", "high", "issue", "incident",
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_.-]{2,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


@dataclass
class Runbook:
    name: str
    text: str


class KnowledgeStore:
    """Reads runbooks and reads/writes incident memories from disk."""

    def __init__(self) -> None:
        _RUNBOOK_DIR.mkdir(parents=True, exist_ok=True)
        _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not _MEMORY_FILE.exists():
            _MEMORY_FILE.write_text("[]", encoding="utf-8")

    # ── Knowledge: runbooks ───────────────────────────────────────────────────
    def _load_runbooks(self) -> list[Runbook]:
        books: list[Runbook] = []
        for path in sorted(_RUNBOOK_DIR.glob("*.md")):
            books.append(Runbook(name=path.stem, text=path.read_text(encoding="utf-8")))
        return books

    def search_runbooks(self, query: str, limit: int = 2) -> dict:
        """Return the runbooks most relevant to the query by token overlap."""
        q = _tokenize(query)
        scored: list[tuple[float, Runbook]] = []
        for book in self._load_runbooks():
            overlap = len(q & _tokenize(book.text))
            if overlap:
                scored.append((overlap, book))
        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            return {"matches": [], "note": "No matching runbook found."}
        return {
            "matches": [
                {"runbook": b.name, "relevance": score, "content": b.text}
                for score, b in scored[:limit]
            ]
        }

    # ── Memories: past incidents ──────────────────────────────────────────────
    def _load_memories(self) -> list[dict]:
        try:
            return json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []

    def recall_similar_incidents(self, description: str, limit: int = 3) -> dict:
        """Find past resolved incidents whose signature overlaps the description."""
        q = _tokenize(description)
        scored: list[tuple[float, dict]] = []
        for mem in self._load_memories():
            signature = f"{mem.get('title', '')} {mem.get('root_cause', '')} {mem.get('summary', '')}"
            overlap = len(q & _tokenize(signature))
            if overlap:
                scored.append((overlap, mem))
        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            return {"matches": [], "note": "No similar past incidents on record."}
        return {
            "matches": [
                {
                    "title": m.get("title"),
                    "root_cause": m.get("root_cause"),
                    "summary": m.get("summary"),
                    "resolved_at": m.get("resolved_at"),
                    "relevance": score,
                }
                for score, m in scored[:limit]
            ]
        }

    def save_incident_memory(
        self,
        title: str,
        root_cause: str,
        summary: str,
        confidence: str = "",
    ) -> dict:
        """Append a resolved incident so future investigations can recall it."""
        memories = self._load_memories()
        entry = {
            "title": title,
            "root_cause": root_cause,
            "summary": summary,
            "confidence": confidence,
            "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        memories.append(entry)
        _MEMORY_FILE.write_text(json.dumps(memories, indent=2), encoding="utf-8")
        return {"saved": True, "total_memories": len(memories)}


# ── OpenAI tool schemas for the knowledge/memory tools ────────────────────────
KNOWLEDGE_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_runbooks",
            "description": "Search the team's runbooks (institutional knowledge) for a documented playbook matching this incident. Do this EARLY — a runbook may already describe the exact failure and its fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Symptoms/keywords, e.g. 'checkout 5xx connection pool timeout'."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_similar_incidents",
            "description": "Recall past resolved incidents similar to this one. Do this EARLY — if we've seen this before, reuse the known root cause instead of re-investigating.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "The incident description or alert summary."},
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_incident_memory",
            "description": "Persist this incident's resolution to memory once you have a confident root cause, so future investigations of the same failure are instant. Call this as your LAST tool before the final report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short incident title, e.g. 'checkout 5xx from payment-gateway pool exhaustion'."},
                    "root_cause": {"type": "string"},
                    "summary": {"type": "string", "description": "One-line remediation summary."},
                    "confidence": {"type": "string", "description": "HIGH / MEDIUM / LOW."},
                },
                "required": ["title", "root_cause", "summary"],
            },
        },
    },
]
