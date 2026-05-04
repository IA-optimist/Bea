"""
core/skills/skill_feedback.py — Skill improvement feedback loop.

Records success/failure signals, user corrections, and refinement proposals.
Skills are NEVER auto-modified — only proposals stored for review.
"""
from __future__ import annotations

import json
import os
import threading
import time
import structlog
from dataclasses import dataclass
from pathlib import Path

log = structlog.get_logger("skills.feedback")

_FEEDBACK_DIR = Path(os.environ.get("WORKSPACE_DIR", "workspace")) / "skill_feedback"


@dataclass
class SkillFeedback:
    """A single feedback entry for a skill execution."""
    skill_id: str
    signal: str  # success, failure, correction, improvement_proposal
    quality_score: float = 0.0
    details: str = ""
    timestamp: float = 0.0
    mission_id: str = ""

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "signal": self.signal,
            "quality_score": self.quality_score,
            "details": self.details[:500],
            "timestamp": self.timestamp or time.time(),
            "mission_id": self.mission_id,
        }


class SkillFeedbackStore:
    """Thread-safe JSONL-backed feedback store."""

    def __init__(self, persist_dir: str | Path | None = None):
        self._lock = threading.Lock()
        self._dir = Path(persist_dir) if persist_dir else _FEEDBACK_DIR
        self._entries: list[SkillFeedback] = []
        self._max_entries = 1000

    def record(self, feedback: SkillFeedback) -> None:
        """Record a feedback entry."""
        feedback.timestamp = feedback.timestamp or time.time()
        with self._lock:
            self._entries.append(feedback)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]
        self._persist(feedback)

    def get_for_skill(self, skill_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            return [
                e.to_dict() for e in reversed(self._entries)
                if e.skill_id == skill_id
            ][:limit]

    def get_summary(self, skill_id: str) -> dict:
        """Get aggregated stats for a skill."""
        entries = [e for e in self._entries if e.skill_id == skill_id]
        if not entries:
            return {"skill_id": skill_id, "executions": 0}
        successes = sum(1 for e in entries if e.signal == "success")
        failures = sum(1 for e in entries if e.signal == "failure")
        avg_score = sum(e.quality_score for e in entries) / len(entries) if entries else 0
        return {
            "skill_id": skill_id,
            "executions": len(entries),
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / len(entries), 3) if entries else 0,
            "avg_quality_score": round(avg_score, 3),
            "proposals": sum(1 for e in entries if e.signal == "improvement_proposal"),
        }

    def _persist(self, entry: SkillFeedback) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / "feedback.jsonl"
            with open(path, "a") as f:
                f.write(json.dumps(entry.to_dict(), default=str) + "\n")
        except Exception as e:
            log.debug("skill_feedback_persist_failed", err=str(e)[:80])


_store: SkillFeedbackStore | None = None
_store_lock = threading.Lock()


def get_feedback_store() -> SkillFeedbackStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SkillFeedbackStore()
    return _store
