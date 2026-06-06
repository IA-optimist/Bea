"""
core/planning/execution_memory.py — Persistent execution history.

Records every plan execution with goal, tools, results, artifacts.
Enables Jarvis to reuse successful patterns.
"""
from __future__ import annotations

import json
import os
import threading
import time
import structlog
from dataclasses import dataclass, field
from pathlib import Path

log = structlog.get_logger("planning.execution_memory")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_HISTORY_PATH = _WORKSPACE / "execution_history.json"


@dataclass
class ExecutionRecord:
    """A single execution history entry."""
    record_id: str = ""
    plan_id: str = ""
    goal: str = ""
    template_id: str = ""
    tools_used: list[str] = field(default_factory=list)
    actions_used: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    success: bool = False
    duration_ms: float = 0
    step_count: int = 0
    steps_completed: int = 0
    artifacts: list[str] = field(default_factory=list)
    error: str = ""
    timestamp: float = 0

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "plan_id": self.plan_id,
            "goal": self.goal,
            "template_id": self.template_id,
            "tools_used": self.tools_used,
            "actions_used": self.actions_used,
            "skills_used": self.skills_used,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "step_count": self.step_count,
            "steps_completed": self.steps_completed,
            "artifacts": self.artifacts,
            "error": self.error[:200],
            "timestamp": self.timestamp or time.time(),
        }


class ExecutionMemory:
    """Thread-safe execution history store."""

    def __init__(self, persist_path: str | Path | None = None):
        self._lock = threading.Lock()
        self._records: list[ExecutionRecord] = []
        self._path = Path(persist_path) if persist_path else _HISTORY_PATH
        self._max_records = 500
        self._loaded = False

    def record(self, entry: ExecutionRecord) -> None:
        """Record a completed execution."""
        entry.timestamp = entry.timestamp or time.time()
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
        self._persist()

    def get_history(self, limit: int = 50) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            return [r.to_dict() for r in reversed(self._records)][:limit]

    def get_by_template(self, template_id: str) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            return [r.to_dict() for r in self._records if r.template_id == template_id]

    def get_successful_patterns(self) -> list[dict]:
        """Get successful execution patterns for reuse."""
        self._ensure_loaded()
        with self._lock:
            successes = [r for r in self._records if r.success]
        patterns = {}
        for r in successes:
            key = r.template_id or r.goal[:50]
            if key not in patterns:
                patterns[key] = {
                    "pattern": key,
                    "count": 0,
                    "avg_duration_ms": 0,
                    "tools": set(),
                    "actions": set(),
                }
            p = patterns[key]
            p["count"] += 1
            p["avg_duration_ms"] += r.duration_ms
            p["tools"].update(r.tools_used)
            p["actions"].update(r.actions_used)

        result = []
        for p in patterns.values():
            if p["count"] > 0:
                p["avg_duration_ms"] = round(p["avg_duration_ms"] / p["count"])
            p["tools"] = list(p["tools"])
            p["actions"] = list(p["actions"])
            result.append(p)
        return sorted(result, key=lambda x: x["count"], reverse=True)

    def stats(self) -> dict:
        self._ensure_loaded()
        with self._lock:
            records = list(self._records)
        return {
            "total": len(records),
            "successes": sum(1 for r in records if r.success),
            "failures": sum(1 for r in records if not r.success),
            "success_rate": round(
                sum(1 for r in records if r.success) / max(len(records), 1), 3
            ),
        }

    def _ensure_loaded(self):
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        try:
            if self._path.is_file():
                data = json.loads(self._path.read_text("utf-8"))
                for d in data.get("records", []):
                    self._records.append(ExecutionRecord(**{
                        k: v for k, v in d.items() if k in ExecutionRecord.__dataclass_fields__
                    }))
        except Exception as e:
            log.debug("execution_memory_load_failed", err=str(e)[:80])

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {"records": [r.to_dict() for r in self._records[-self._max_records:]]}
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), "utf-8")
            tmp.replace(self._path)
        except Exception as e:
            log.debug("execution_memory_persist_failed", err=str(e)[:80])


# ── Singleton ─────────────────────────────────────────────────

_memory: ExecutionMemory | None = None
_lock = threading.Lock()


def get_execution_memory() -> ExecutionMemory:
    global _memory
    if _memory is None:
        with _lock:
            if _memory is None:
                _memory = ExecutionMemory()
    return _memory
