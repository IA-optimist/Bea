"""
JARVIS MAX — Mission Memory
===============================
Stores results, lessons, failures, durations, and decisions
from business mission execution.

Provides structured traces for future optimization.
Persistence: JSON file storage.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MissionMemoryEntry:
    """A memory record from a mission execution."""
    mission_id: str
    mission_title: str = ""
    template_id: str = ""
    status: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    duration_seconds: float = 0
    lessons: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)  # [{step, error, retry_count}]
    decisions: list[dict] = field(default_factory=list)  # [{step, decision, reason}]
    agent_performance: dict[str, dict] = field(default_factory=dict)  # agent → {steps, success, avg_duration}
    cost_estimate: float = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "title": self.mission_title,
            "template_id": self.template_id,
            "status": self.status,
            "steps": f"{self.completed_steps}/{self.total_steps}",
            "failed": self.failed_steps,
            "duration_s": round(self.duration_seconds, 1),
            "lessons": self.lessons[:10],
            "failures": self.failures[:10],
            "decisions": self.decisions[:10],
            "agent_performance": self.agent_performance,
            "created_at": self.created_at,
        }


class MissionMemory:
    """
    Persistent mission memory store.
    
    Stores:
    - Mission results (success/failure)
    - Lessons learned per template
    - Step failure patterns
    - Agent performance per mission type
    - Duration baselines for estimation
    """

    MAX_ENTRIES = 200

    def __init__(self, storage_path: str = ""):
        self._path = Path(storage_path) if storage_path else None
        self._entries: list[MissionMemoryEntry] = []
        self._load()

    # ── Store ──

    def record(self, entry: MissionMemoryEntry) -> None:
        """Record a mission execution result."""
        self._entries.append(entry)
        # Trim oldest
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES:]
        self._save()

    def add_lesson(self, mission_id: str, lesson: str) -> None:
        """Add a lesson to an existing entry."""
        for e in reversed(self._entries):
            if e.mission_id == mission_id:
                e.lessons.append(lesson)
                self._save()
                return

    def add_decision(self, mission_id: str, step: str, decision: str, reason: str = "") -> None:
        """Record a decision made during execution."""
        for e in reversed(self._entries):
            if e.mission_id == mission_id:
                e.decisions.append({"step": step, "decision": decision, "reason": reason})
                self._save()
                return

    # ── Query ──

    def get_by_mission(self, mission_id: str) -> MissionMemoryEntry | None:
        for e in reversed(self._entries):
            if e.mission_id == mission_id:
                return e
        return None

    def get_by_template(self, template_id: str, limit: int = 10) -> list[MissionMemoryEntry]:
        """Get past executions of a template for learning."""
        results = [e for e in reversed(self._entries) if e.template_id == template_id]
        return results[:limit]

    def get_recent(self, limit: int = 20) -> list[dict]:
        return [e.to_dict() for e in reversed(self._entries)][:limit]

    def get_failure_patterns(self, template_id: str = "") -> list[dict]:
        """Get common failure patterns for optimization."""
        failures: dict[str, int] = {}
        entries = self._entries
        if template_id:
            entries = [e for e in entries if e.template_id == template_id]
        for e in entries:
            for f in e.failures:
                key = f.get("error", "unknown")[:80]
                failures[key] = failures.get(key, 0) + 1
        return [{"error": k, "count": v} for k, v in sorted(failures.items(), key=lambda x: -x[1])][:20]

    def get_template_stats(self, template_id: str) -> dict:
        """Get aggregate stats for a template."""
        entries = [e for e in self._entries if e.template_id == template_id]
        if not entries:
            return {"runs": 0, "success_rate": 0, "avg_duration": 0}
        successes = sum(1 for e in entries if e.status == "completed")
        durations = [e.duration_seconds for e in entries if e.duration_seconds > 0]
        return {
            "runs": len(entries),
            "success_rate": round(successes / len(entries) * 100, 1),
            "avg_duration": round(sum(durations) / max(len(durations), 1), 1),
            "lessons_count": sum(len(e.lessons) for e in entries),
            "common_failures": self.get_failure_patterns(template_id)[:5],
        }

    def get_agent_stats(self) -> dict[str, dict]:
        """Aggregate agent performance across all missions."""
        agents: dict[str, dict] = {}
        for e in self._entries:
            for agent, perf in e.agent_performance.items():
                if agent not in agents:
                    agents[agent] = {"total_steps": 0, "successes": 0, "total_duration": 0}
                agents[agent]["total_steps"] += perf.get("steps", 0)
                agents[agent]["successes"] += perf.get("success", 0)
                agents[agent]["total_duration"] += perf.get("avg_duration", 0) * perf.get("steps", 1)
        # Compute rates
        for agent, stats in agents.items():
            stats["success_rate"] = round(stats["successes"] / max(stats["total_steps"], 1) * 100, 1)
        return agents

    @property
    def total_missions(self) -> int:
        return len(self._entries)

    @property
    def success_rate(self) -> float:
        if not self._entries:
            return 0.0
        return round(sum(1 for e in self._entries if e.status == "completed") / len(self._entries) * 100, 1)

    # ── Persistence ──

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data:
                self._entries.append(MissionMemoryEntry(**{
                    k: v for k, v in item.items() if k in MissionMemoryEntry.__dataclass_fields__
                }))
        except Exception as e:
            logger.warning(f"Mission memory load failed: {e}")

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(
                [e.to_dict() for e in self._entries], indent=2
            ))
        except Exception as e:
            logger.warning(f"Mission memory save failed: {e}")
