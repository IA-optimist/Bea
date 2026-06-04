"""
core/planning/run_state.py — Plan run state management.

Tracks active runs, persists run snapshots for resume, manages run lifecycle.
"""
from __future__ import annotations

import json
import os
import threading
import time
import structlog
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from core.planning.step_context import StepContext

log = structlog.get_logger("planning.run_state")

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_RUNS_DIR = _WORKSPACE / "plan_runs"


class RunStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class PlanRun:
    """A single execution run of a plan."""
    run_id: str = ""
    plan_id: str = ""
    status: RunStatus = RunStatus.RUNNING
    context: StepContext = field(default_factory=StepContext)
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    current_step_id: str = ""
    error: str = ""
    started_at: float = 0
    completed_at: float = 0

    def __post_init__(self):
        if not self.started_at:
            self.started_at = time.time()
        if not self.run_id and self.context:
            self.run_id = self.context.run_id

    @property
    def progress(self) -> float:
        if self.steps_total == 0:
            return 0
        return round(self.steps_completed / self.steps_total, 3)

    @property
    def duration_ms(self) -> float:
        end = self.completed_at or time.time()
        return round((end - self.started_at) * 1000) if self.started_at else 0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "status": self.status.value,
            "steps_total": self.steps_total,
            "steps_completed": self.steps_completed,
            "steps_failed": self.steps_failed,
            "current_step_id": self.current_step_id,
            "progress": self.progress,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "context": self.context.to_dict(),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class RunStateStore:
    """Thread-safe store for active and completed plan runs."""

    def __init__(self, persist_dir: str | Path | None = None):
        self._lock = threading.RLock()
        self._runs: dict[str, PlanRun] = {}
        self._dir = Path(persist_dir) if persist_dir else _RUNS_DIR

    def save(self, run: PlanRun) -> None:
        with self._lock:
            self._runs[run.run_id] = run
        self._persist(run)

    def get(self, run_id: str) -> PlanRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_all(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in sorted(
                self._runs.values(), key=lambda x: x.started_at, reverse=True
            )]

    def list_active(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._runs.values()
                    if r.status in {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.AWAITING_APPROVAL}]

    def _persist(self, run: PlanRun) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{run.run_id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(run.to_dict(), indent=2, default=str), "utf-8")
            tmp.replace(path)
        except Exception as e:
            log.debug("run_persist_failed", run_id=run.run_id, err=str(e)[:80])

    def load_from_disk(self) -> int:
        """Load persisted runs from disk."""
        count = 0
        if not self._dir.is_dir():
            return 0
        for f in self._dir.glob("run-*.json"):
            try:
                data = json.loads(f.read_text("utf-8"))
                ctx = StepContext.from_dict(data.get("context", {}))
                run = PlanRun(
                    run_id=data.get("run_id", ""),
                    plan_id=data.get("plan_id", ""),
                    status=RunStatus(data.get("status", "failed")),
                    context=ctx,
                    steps_total=data.get("steps_total", 0),
                    steps_completed=data.get("steps_completed", 0),
                    steps_failed=data.get("steps_failed", 0),
                    current_step_id=data.get("current_step_id", ""),
                    error=data.get("error", ""),
                    started_at=data.get("started_at", 0),
                    completed_at=data.get("completed_at", 0),
                )
                with self._lock:
                    self._runs[run.run_id] = run
                count += 1
            except Exception as e:
                log.debug("run_load_failed", path=str(f), err=str(e)[:80])
        return count


# ── Singleton ─────────────────────────────────────────────────

_store: RunStateStore | None = None
_store_lock = threading.Lock()


def get_run_store() -> RunStateStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RunStateStore()
    return _store
