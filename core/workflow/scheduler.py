"""
BEA Workflow — Scheduled Task System (Phase 1)
================================================
Persistent scheduled tasks: interval, fixed-time, and manual triggers.
"""
from __future__ import annotations

import datetime
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

import structlog

from .boundaries import MAX_SCHEDULED_TASKS, MAX_EVENT_LOG

logger = structlog.get_logger("bea.workflow_runtime")
log = logger


@dataclass
class ScheduledTask:
    """A persistently scheduled task."""
    task_id: str = ""
    name: str = ""
    description: str = ""
    schedule_type: str = "interval"  # interval | fixed_time | manual
    interval_s: int = 3600           # seconds between runs (for interval type)
    fixed_time: str = ""             # HH:MM (UTC) for fixed_time type
    enabled: bool = True
    workflow_id: str = ""            # workflow to execute (optional)
    action: str = ""                 # simple action name (if no workflow)
    params: dict = field(default_factory=dict)
    retry_policy: str = "linear"     # linear | exponential | none
    max_retries: int = 3
    created_at: float = 0.0
    last_run: float = 0.0
    next_run: float = 0.0
    run_count: int = 0
    fail_count: int = 0
    last_error: str = ""
    status: str = "idle"             # idle | running | paused | error

    def to_dict(self) -> dict:
        return asdict(self)

    def is_due(self, now: float = 0.0) -> bool:
        """Check if this task should run now."""
        if not self.enabled or self.status == "paused":
            return False
        now = now or time.time()

        if self.schedule_type == "manual":
            return False  # only triggered explicitly

        if self.schedule_type == "interval":
            if self.next_run <= 0:
                return True
            return now >= self.next_run

        if self.schedule_type == "fixed_time":
            # Check if current UTC HH:MM matches
            try:
                utc_now = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
                target_h, target_m = map(int, self.fixed_time.split(":"))
                if utc_now.hour == target_h and utc_now.minute == target_m:
                    # Only run once per fixed window (check last_run)
                    if (now - self.last_run) > 120:  # 2-minute dedup
                        return True
            except Exception as _exc:
                log.warning(
                    "swallowed_exception",
                    action="workflow_runtime_swallow",
                    exc_type=type(_exc).__name__,
                    exc_msg=str(_exc)[:200],
                )
            return False

        return False

    def compute_next_run(self, now: float = 0.0) -> float:
        """Compute the next scheduled execution time."""
        now = now or time.time()
        if self.schedule_type == "interval":
            return now + self.interval_s
        return 0.0  # fixed_time and manual don't have next_run

    def record_execution(self, success: bool, error: str = "") -> None:
        """Record that this task was executed."""
        now = time.time()
        self.last_run = now
        self.run_count += 1
        self.status = "idle"
        if success:
            self.last_error = ""
        else:
            self.fail_count += 1
            self.last_error = error[:200]
            self.status = "error"
        self.next_run = self.compute_next_run(now)


class ScheduledTaskManager:
    """Manages scheduled tasks with persistence and execution tracking."""

    PERSIST_FILE = "workspace/scheduled_tasks.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._tasks: dict[str, ScheduledTask] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._execution_log: list[dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def schedule(self, task: ScheduledTask) -> ScheduledTask:
        """Add or update a scheduled task."""
        self._ensure_loaded()
        if len(self._tasks) >= MAX_SCHEDULED_TASKS and task.task_id not in self._tasks:
            raise ValueError(f"Max scheduled tasks reached ({MAX_SCHEDULED_TASKS})")
        if not task.task_id:
            task.task_id = str(uuid.uuid4())[:8]
        if not task.created_at:
            task.created_at = time.time()
        if task.next_run <= 0 and task.schedule_type == "interval":
            task.next_run = task.compute_next_run()
        self._tasks[task.task_id] = task
        self.save()
        return task

    def unschedule(self, task_id: str) -> bool:
        """Remove a scheduled task."""
        self._ensure_loaded()
        if task_id in self._tasks:
            del self._tasks[task_id]
            self.save()
            return True
        return False

    def pause(self, task_id: str) -> bool:
        self._ensure_loaded()
        task = self._tasks.get(task_id)
        if task:
            task.status = "paused"
            task.enabled = False
            self.save()
            return True
        return False

    def resume(self, task_id: str) -> bool:
        self._ensure_loaded()
        task = self._tasks.get(task_id)
        if task:
            task.status = "idle"
            task.enabled = True
            self.save()
            return True
        return False

    def get_due_tasks(self, now: float = 0.0) -> list[ScheduledTask]:
        """Get all tasks that should run now."""
        self._ensure_loaded()
        now = now or time.time()
        return [t for t in self._tasks.values() if t.is_due(now)]

    def record_execution(self, task_id: str, success: bool, error: str = "",
                         duration_s: float = 0.0) -> None:
        """Record a task execution result."""
        self._ensure_loaded()
        task = self._tasks.get(task_id)
        if task:
            task.record_execution(success, error)
            self._execution_log.append({
                "task_id": task_id, "task_name": task.name,
                "success": success, "error": error[:100],
                "duration_s": round(duration_s, 2),
                "timestamp": time.time(),
            })
            if len(self._execution_log) > MAX_EVENT_LOG:
                self._execution_log = self._execution_log[-MAX_EVENT_LOG:]
            self.save()

    def trigger_manual(self, task_id: str) -> Optional[ScheduledTask]:
        """Manually trigger a task (for manual schedule_type)."""
        self._ensure_loaded()
        task = self._tasks.get(task_id)
        if task and task.enabled:
            task.status = "running"
            return task
        return None

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        self._ensure_loaded()
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[dict]:
        self._ensure_loaded()
        return [t.to_dict() for t in sorted(
            self._tasks.values(), key=lambda t: t.next_run or t.created_at
        )]

    def get_execution_log(self, limit: int = 50) -> list[dict]:
        return self._execution_log[-limit:]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._tasks.items()}, f, indent=2)
        except Exception as e:
            logger.warning("scheduled_tasks_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for tid, d in data.items():
                self._tasks[tid] = ScheduledTask(
                    **{k: v for k, v in d.items() if k in ScheduledTask.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("scheduled_tasks_load_failed: %s", str(e)[:80])
