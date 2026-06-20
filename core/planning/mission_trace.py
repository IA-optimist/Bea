"""
core/planning/mission_trace.py — Structured mission execution trace.

Captures the full reasoning and execution path of a mission for
operator inspection and debugging.

Design:
  - Append-only trace log
  - Each entry: timestamp, phase, event, data
  - Serializable to dict for API/UI
  - Singleton per mission (no cross-mission state)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEntry:
    """Single entry in a mission trace."""
    timestamp: float
    phase: str       # planning, execution, retry, review, delivery
    event: str       # step_start, step_complete, retry_triggered, review_complete, etc.
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "phase": self.phase,
            "event": self.event,
            "data": self.data,
        }


class MissionTrace:
    """
    Structured trace of a mission execution.

    Records planning, execution, retry, review, and delivery events.
    """

    def __init__(self, mission_id: str = "", goal: str = ""):
        self.mission_id = mission_id
        self.goal = goal
        self._entries: list[TraceEntry] = []
        self._start_time = time.time()

    def record(self, phase: str, event: str, **data: Any) -> None:
        """Add a trace entry."""
        self._entries.append(TraceEntry(
            timestamp=time.time(),
            phase=phase,
            event=event,
            data=data,
        ))

    def record_planning(self, playbook_id: str, steps: int, budget_mode: str) -> None:
        self.record("planning", "plan_created",
                    playbook_id=playbook_id, steps=steps, budget_mode=budget_mode)

    def record_step_start(self, step_id: str, skill_id: str) -> None:
        self.record("execution", "step_start", step_id=step_id, skill_id=skill_id)

    def record_step_complete(self, step_id: str, ok: bool, duration_ms: float, **extra: Any) -> None:
        self.record("execution", "step_complete",
                    step_id=step_id, ok=ok, duration_ms=duration_ms, **extra)

    def record_retry(self, step_id: str, attempt: int, strategy: str) -> None:
        self.record("retry", "retry_triggered",
                    step_id=step_id, attempt=attempt, strategy=strategy)

    def record_model_selection(self, skill_id: str, model: str, budget_mode: str) -> None:
        self.record("execution", "model_selected",
                    skill_id=skill_id, model=model, budget_mode=budget_mode)

    def record_review(self, score: float, passed: bool, issues: int) -> None:
        self.record("review", "review_complete",
                    score=score, passed=passed, issues=issues)

    def record_delivery(self, ok: bool, quality: float) -> None:
        self.record("delivery", "mission_delivered",
                    ok=ok, quality=quality,
                    total_duration_ms=(time.time() - self._start_time) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal[:200],
            "entries": [e.to_dict() for e in self._entries],
            "total_entries": len(self._entries),
            "duration_ms": (time.time() - self._start_time) * 1000,
        }

    def summary(self) -> dict[str, Any]:
        """Compact summary for API responses."""
        phases: dict[str, int] = {}
        for e in self._entries:
            phases.setdefault(e.phase, 0)
            phases[e.phase] += 1

        retries = sum(1 for e in self._entries if e.event == "retry_triggered")
        errors = sum(1 for e in self._entries
                     if e.data.get("ok") is False)

        return {
            "mission_id": self.mission_id,
            "phases": phases,
            "total_events": len(self._entries),
            "retries": retries,
            "errors": errors,
            "duration_ms": (time.time() - self._start_time) * 1000,
        }
