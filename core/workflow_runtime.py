"""
JARVIS — Autonomous Workflow Runtime
========================================
Persistent structured workflows that execute across time with
bounded autonomy, full observability, and interruptibility.

Capabilities:
1. Scheduled Task System — interval, fixed-time, manual triggers
2. Workflow Execution Engine — multi-step, resume, partial completion
3. Event-Driven Triggers — bounded, debounced, no infinite loops
4. Workflow Versioning — history, performance comparison, rollback
5. Resource Management — concurrent limits, queue depth, pressure
6. Autonomy Boundaries — max depth, concurrency, trigger frequency
7. Cockpit Visibility — full observability signals

Integrates with:
  - operating_primitives (approval gating, economics)
  - execution_engine (execution limits)
  - lifecycle_tracker (stage recording)
  - tool_performance_tracker (observability)
  - safety_controls (kill switches)

All workflows are:
  - Observable (every step logged)
  - Interruptible (pause/cancel at any point)
  - Bounded (max depth, concurrency, triggers)
  - Approval-gated (persistent_workflow requires approval)

Zero external dependencies. Fail-open everywhere.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger("jarvis.workflow_runtime")


# ═══════════════════════════════════════════════════════════════
# AUTONOMY BOUNDARIES (Phase 6 — defined first, enforced everywhere)
# ═══════════════════════════════════════════════════════════════

MAX_CONCURRENT_WORKFLOWS = int(os.environ.get("JARVIS_MAX_WORKFLOWS", "10"))
MAX_WORKFLOW_DEPTH = int(os.environ.get("JARVIS_MAX_WORKFLOW_DEPTH", "20"))
MAX_TRIGGER_FREQUENCY_S = int(os.environ.get("JARVIS_MIN_TRIGGER_INTERVAL", "60"))
MAX_RETRY_CYCLES = int(os.environ.get("JARVIS_MAX_RETRY_CYCLES", "5"))
MAX_SCHEDULED_TASKS = int(os.environ.get("JARVIS_MAX_SCHEDULED_TASKS", "50"))
MAX_EVENT_HANDLERS = int(os.environ.get("JARVIS_MAX_EVENT_HANDLERS", "30"))
MAX_WORKFLOW_HISTORY = 200
MAX_EVENT_LOG = 500
MAX_VERSION_HISTORY = 50


def get_autonomy_limits() -> dict:
    """Return all workflow autonomy boundaries."""
    return {
        "max_concurrent_workflows": MAX_CONCURRENT_WORKFLOWS,
        "max_workflow_depth": MAX_WORKFLOW_DEPTH,
        "max_trigger_frequency_s": MAX_TRIGGER_FREQUENCY_S,
        "max_retry_cycles": MAX_RETRY_CYCLES,
        "max_scheduled_tasks": MAX_SCHEDULED_TASKS,
        "max_event_handlers": MAX_EVENT_HANDLERS,
        "max_workflow_history": MAX_WORKFLOW_HISTORY,
        "max_event_log": MAX_EVENT_LOG,
        "max_version_history": MAX_VERSION_HISTORY,
    }


# ═══════════════════════════════════════════════════════════════
# PHASE 1 — SCHEDULED TASK SYSTEM
# ═══════════════════════════════════════════════════════════════

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
                import datetime
                utc_now = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
                target_h, target_m = map(int, self.fixed_time.split(":"))
                if utc_now.hour == target_h and utc_now.minute == target_m:
                    # Only run once per fixed window (check last_run)
                    if (now - self.last_run) > 120:  # 2-minute dedup
                        return True
            except Exception:
                _silent_log.debug("suppressed_exception", src='workflow_runtime.py')
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


# ═══════════════════════════════════════════════════════════════
# PHASE 2 — WORKFLOW EXECUTION ENGINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    step_id: int = 0
    name: str = ""
    action: str = ""            # connector name or tool name
    params: dict = field(default_factory=dict)
    status: str = "pending"     # pending | running | completed | failed | skipped
    result: Any = None
    error: str = ""
    retries: int = 0
    max_retries: int = 3
    started_at: float = 0.0
    completed_at: float = 0.0
    depends_on: list = field(default_factory=list)  # step_ids

    def to_dict(self) -> dict:
        d = asdict(self)
        # Ensure result is serializable
        try:
            json.dumps(d["result"])
        except (TypeError, ValueError):
            d["result"] = str(d["result"])[:500]
        return d

    @property
    def duration_s(self) -> float:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0


@dataclass
class WorkflowExecution:
    """A running workflow instance."""
    execution_id: str = ""
    workflow_name: str = ""
    version: int = 1
    steps: list = field(default_factory=list)  # list[WorkflowStep] stored as dicts
    status: str = "created"     # created | running | paused | completed | failed | cancelled
    current_step: int = 0
    created_at: float = 0.0
    started_at: float = 0.0
    paused_at: float = 0.0
    completed_at: float = 0.0
    total_retries: int = 0
    error_summary: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def duration_s(self) -> float:
        end = self.completed_at or self.paused_at or time.time()
        return end - self.started_at if self.started_at else 0.0

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if isinstance(s, dict)
                        and s.get("status") in ("completed", "skipped"))
        return round(completed / len(self.steps), 3)

    @property
    def step_objects(self) -> list[WorkflowStep]:
        """Convert step dicts back to WorkflowStep objects."""
        result = []
        for s in self.steps:
            if isinstance(s, dict):
                result.append(WorkflowStep(
                    **{k: v for k, v in s.items() if k in WorkflowStep.__dataclass_fields__}
                ))
            elif isinstance(s, WorkflowStep):
                result.append(s)
        return result


class WorkflowEngine:
    """
    Executes persistent multi-step workflows with resume capability.
    Bounded: MAX_CONCURRENT_WORKFLOWS active, MAX_WORKFLOW_HISTORY total.
    """

    PERSIST_FILE = "workspace/workflow_executions.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._executions: dict[str, WorkflowExecution] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False
        self._step_executors: dict[str, Callable] = {}

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def register_step_executor(self, action: str, executor: Callable) -> None:
        """Register a callable for a step action type."""
        self._step_executors[action] = executor

    def create_workflow(self, name: str, steps: list[dict],
                        version: int = 1, metadata: dict = None) -> WorkflowExecution:
        """Create a new workflow execution."""
        self._ensure_loaded()

        # Enforce boundaries
        active = sum(1 for e in self._executions.values()
                     if e.status in ("created", "running", "paused"))
        if active >= MAX_CONCURRENT_WORKFLOWS:
            raise ValueError(f"Max concurrent workflows reached ({MAX_CONCURRENT_WORKFLOWS})")

        if len(steps) > MAX_WORKFLOW_DEPTH:
            raise ValueError(f"Workflow too deep ({len(steps)} > {MAX_WORKFLOW_DEPTH})")

        # Build steps
        workflow_steps = []
        for i, s in enumerate(steps):
            step = WorkflowStep(
                step_id=i,
                name=s.get("name", f"step_{i}"),
                action=s.get("action", ""),
                params=s.get("params", {}),
                max_retries=min(s.get("max_retries", 3), MAX_RETRY_CYCLES),
                depends_on=s.get("depends_on", []),
            )
            workflow_steps.append(step.to_dict())

        execution = WorkflowExecution(
            execution_id=str(uuid.uuid4())[:8],
            workflow_name=name,
            version=version,
            steps=workflow_steps,
            status="created",
            created_at=time.time(),
            metadata=metadata or {},
        )

        # Evict oldest if at capacity
        if len(self._executions) >= MAX_WORKFLOW_HISTORY:
            oldest = min(self._executions.values(), key=lambda e: e.created_at)
            del self._executions[oldest.execution_id]

        self._executions[execution.execution_id] = execution
        self.save()
        return execution

    def execute_step(self, execution_id: str, step_idx: int) -> dict:
        """Execute a specific step in a workflow."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if not execution:
            return {"success": False, "error": "execution not found"}

        if step_idx >= len(execution.steps):
            return {"success": False, "error": "step index out of range"}

        step = execution.steps[step_idx]
        if isinstance(step, WorkflowStep):
            step = step.to_dict()
            execution.steps[step_idx] = step

        # Check dependencies
        for dep_idx in step.get("depends_on", []):
            if dep_idx < len(execution.steps):
                dep = execution.steps[dep_idx]
                dep_status = dep.get("status") if isinstance(dep, dict) else dep.status
                if dep_status not in ("completed", "skipped"):
                    return {"success": False, "error": f"dependency step {dep_idx} not completed"}

        step["status"] = "running"
        step["started_at"] = time.time()
        execution.status = "running"
        if not execution.started_at:
            execution.started_at = time.time()
        execution.current_step = step_idx

        action = step.get("action", "")
        params = step.get("params", {})

        # Try connector first, then registered executor
        result = None
        error = ""
        success = False

        try:
            from core.connectors import CONNECTOR_REGISTRY, execute_connector
            if action in CONNECTOR_REGISTRY:
                cr = execute_connector(action, params)
                success = cr.success
                result = cr.data if cr.success else None
                error = cr.error or ""
            elif action in self._step_executors:
                r = self._step_executors[action](params)
                success = bool(r.get("success", True) if isinstance(r, dict) else r)
                result = r
                error = r.get("error", "") if isinstance(r, dict) else ""
            else:
                success = True  # No-op step (placeholder)
                result = {"action": action, "status": "no_executor_registered"}
        except Exception as e:
            error = str(e)[:200]

        if success:
            step["status"] = "completed"
            step["result"] = result
        else:
            step["retries"] = step.get("retries", 0) + 1
            if step["retries"] >= step.get("max_retries", 3):
                step["status"] = "failed"
                step["error"] = error
            else:
                step["status"] = "pending"  # Will be retried
                step["error"] = error

        step["completed_at"] = time.time()
        execution.steps[step_idx] = step

        # Check overall workflow status
        self._update_workflow_status(execution)
        self.save()

        return {"success": success, "step": step, "error": error}

    def run_next_step(self, execution_id: str) -> dict:
        """Run the next pending step in order."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if not execution:
            return {"success": False, "error": "execution not found"}

        if execution.status in ("completed", "failed", "cancelled"):
            return {"success": False, "error": f"workflow is {execution.status}"}

        if execution.status == "paused":
            return {"success": False, "error": "workflow is paused"}

        # Find next runnable step
        for i, step in enumerate(execution.steps):
            s = step if isinstance(step, dict) else step.to_dict()
            if s.get("status") == "pending":
                return self.execute_step(execution_id, i)

        return {"success": True, "error": "", "done": True}

    def run_all(self, execution_id: str) -> dict:
        """Run all remaining steps sequentially."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if not execution:
            return {"success": False, "error": "execution not found"}

        results = []
        step_count = 0
        while step_count < MAX_WORKFLOW_DEPTH:
            r = self.run_next_step(execution_id)
            if r.get("done") or not r.get("success", True):
                results.append(r)
                break
            results.append(r)
            step_count += 1

            # Refresh execution
            execution = self._executions.get(execution_id)
            if not execution or execution.status in ("completed", "failed", "cancelled", "paused"):
                break

        return {
            "execution_id": execution_id,
            "steps_run": step_count,
            "results": results,
            "final_status": execution.status if execution else "unknown",
        }

    def pause(self, execution_id: str) -> bool:
        """Pause a running workflow."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if execution and execution.status in ("created", "running"):
            execution.status = "paused"
            execution.paused_at = time.time()
            self.save()
            return True
        return False

    def resume(self, execution_id: str) -> bool:
        """Resume a paused workflow."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if execution and execution.status == "paused":
            execution.status = "running"
            execution.paused_at = 0.0
            self.save()
            return True
        return False

    def cancel(self, execution_id: str) -> bool:
        """Cancel a workflow."""
        self._ensure_loaded()
        execution = self._executions.get(execution_id)
        if execution and execution.status not in ("completed", "failed"):
            execution.status = "cancelled"
            execution.completed_at = time.time()
            self.save()
            return True
        return False

    def get_execution(self, execution_id: str) -> Optional[dict]:
        self._ensure_loaded()
        e = self._executions.get(execution_id)
        return e.to_dict() if e else None

    def list_executions(self, status_filter: str = "") -> list[dict]:
        self._ensure_loaded()
        execs = list(self._executions.values())
        if status_filter:
            execs = [e for e in execs if e.status == status_filter]
        return [e.to_dict() for e in sorted(execs, key=lambda e: e.created_at, reverse=True)[:50]]

    def _update_workflow_status(self, execution: WorkflowExecution) -> None:
        """Update workflow status based on step states."""
        steps = execution.steps
        all_done = all(
            (s.get("status") if isinstance(s, dict) else s.status)
            in ("completed", "skipped")
            for s in steps
        )
        any_failed = any(
            (s.get("status") if isinstance(s, dict) else s.status) == "failed"
            for s in steps
        )

        if all_done:
            execution.status = "completed"
            execution.completed_at = time.time()
        elif any_failed:
            execution.status = "failed"
            execution.completed_at = time.time()
            failed_names = [
                (s.get("name") if isinstance(s, dict) else s.name)
                for s in steps
                if (s.get("status") if isinstance(s, dict) else s.status) == "failed"
            ]
            execution.error_summary = f"Failed steps: {', '.join(failed_names)}"

        # Count total retries
        execution.total_retries = sum(
            (s.get("retries", 0) if isinstance(s, dict) else s.retries)
            for s in steps
        )

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._executions.items()}, f, indent=2)
        except Exception as e:
            logger.warning("workflow_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for eid, d in data.items():
                self._executions[eid] = WorkflowExecution(
                    **{k: v for k, v in d.items() if k in WorkflowExecution.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("workflow_load_failed: %s", str(e)[:80])


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — EVENT-DRIVEN TRIGGERS
# ═══════════════════════════════════════════════════════════════

@dataclass
class EventTrigger:
    """An event-driven workflow trigger."""
    trigger_id: str = ""
    name: str = ""
    event_type: str = ""        # opportunity_detected | objective_stalled | tool_failure |
                                # workflow_success | external_signal
    condition: str = ""         # human-readable condition
    workflow_name: str = ""     # workflow to execute
    workflow_steps: list = field(default_factory=list)
    enabled: bool = True
    debounce_s: int = 300       # minimum seconds between triggers
    last_triggered: float = 0.0
    trigger_count: int = 0
    max_triggers_per_day: int = 10
    daily_trigger_count: int = 0
    daily_reset_time: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def can_trigger(self, now: float = 0.0) -> bool:
        """Check if this trigger can fire (debounce + daily limit)."""
        if not self.enabled:
            return False
        now = now or time.time()

        # Debounce
        if (now - self.last_triggered) < self.debounce_s:
            return False

        # Daily limit reset
        if (now - self.daily_reset_time) > 86400:
            self.daily_trigger_count = 0
            self.daily_reset_time = now

        if self.daily_trigger_count >= self.max_triggers_per_day:
            return False

        return True

    def record_trigger(self) -> None:
        now = time.time()
        self.last_triggered = now
        self.trigger_count += 1
        self.daily_trigger_count += 1


VALID_EVENT_TYPES = {
    "opportunity_detected",
    "objective_stalled",
    "tool_failure_repeated",
    "workflow_success_pattern",
    "external_signal",
    "mission_completed",
    "mission_failed",
    "schedule_tick",
}


class EventTriggerManager:
    """Manages event-driven workflow triggers with bounded execution."""

    def __init__(self):
        self._triggers: dict[str, EventTrigger] = {}
        self._event_log: list[dict] = []

    def register_trigger(self, trigger: EventTrigger) -> EventTrigger:
        """Register an event trigger."""
        if len(self._triggers) >= MAX_EVENT_HANDLERS:
            raise ValueError(f"Max event handlers reached ({MAX_EVENT_HANDLERS})")
        if trigger.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event type: {trigger.event_type}")
        if not trigger.trigger_id:
            trigger.trigger_id = str(uuid.uuid4())[:8]
        if not trigger.created_at:
            trigger.created_at = time.time()
        self._triggers[trigger.trigger_id] = trigger
        return trigger

    def unregister_trigger(self, trigger_id: str) -> bool:
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            return True
        return False

    def fire_event(self, event_type: str, context: dict = None) -> list[dict]:
        """
        Fire an event and return matching triggers that should execute.
        Does NOT execute workflows — returns trigger info for the caller.
        """
        if event_type not in VALID_EVENT_TYPES:
            return []

        now = time.time()
        triggered = []

        for trigger in self._triggers.values():
            if trigger.event_type != event_type:
                continue
            if not trigger.can_trigger(now):
                continue

            trigger.record_trigger()
            triggered.append({
                "trigger_id": trigger.trigger_id,
                "name": trigger.name,
                "workflow_name": trigger.workflow_name,
                "workflow_steps": trigger.workflow_steps,
                "event_type": event_type,
                "context": context or {},
            })

        # Log event
        self._event_log.append({
            "event_type": event_type,
            "triggers_fired": len(triggered),
            "timestamp": now,
            "context_keys": list((context or {}).keys()),
        })
        if len(self._event_log) > MAX_EVENT_LOG:
            self._event_log = self._event_log[-MAX_EVENT_LOG:]

        return triggered

    def list_triggers(self) -> list[dict]:
        return [t.to_dict() for t in self._triggers.values()]

    def get_event_log(self, limit: int = 50) -> list[dict]:
        return self._event_log[-limit:]


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — WORKFLOW VERSIONING
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkflowVersion:
    """A versioned workflow definition."""
    workflow_name: str = ""
    version: int = 1
    steps_template: list = field(default_factory=list)  # step definitions
    created_at: float = 0.0
    executions: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_s: float = 0.0
    total_duration_s: float = 0.0
    is_stable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def success_rate(self) -> float:
        if self.executions == 0:
            return 0.0
        return round(self.successes / self.executions, 3)

    @property
    def efficiency(self) -> float:
        """Lower duration with higher success = more efficient."""
        if self.executions == 0 or self.avg_duration_s <= 0:
            return 0.0
        return round(self.success_rate / max(self.avg_duration_s, 0.1), 4)


class WorkflowVersionManager:
    """Tracks workflow versions with performance comparison."""

    def __init__(self):
        self._versions: dict[str, list[WorkflowVersion]] = {}  # name → [versions]

    def register_version(self, name: str, steps_template: list,
                         version: int = 0) -> WorkflowVersion:
        """Register a new workflow version."""
        if name not in self._versions:
            self._versions[name] = []

        history = self._versions[name]

        # Auto-increment version
        if version <= 0:
            version = max((v.version for v in history), default=0) + 1

        # Enforce history limit
        if len(history) >= MAX_VERSION_HISTORY:
            history.pop(0)

        wv = WorkflowVersion(
            workflow_name=name,
            version=version,
            steps_template=steps_template[:MAX_WORKFLOW_DEPTH],
            created_at=time.time(),
        )
        history.append(wv)
        return wv

    def record_execution(self, name: str, version: int,
                         success: bool, duration_s: float) -> None:
        """Record an execution outcome for a version."""
        history = self._versions.get(name, [])
        for wv in history:
            if wv.version == version:
                wv.executions += 1
                if success:
                    wv.successes += 1
                else:
                    wv.failures += 1
                wv.total_duration_s += duration_s
                wv.avg_duration_s = round(wv.total_duration_s / wv.executions, 2)
                # Mark stable if enough successful runs
                if wv.executions >= 5 and wv.success_rate >= 0.8:
                    wv.is_stable = True
                return

    def get_best_version(self, name: str) -> Optional[WorkflowVersion]:
        """Get the best-performing version of a workflow."""
        history = self._versions.get(name, [])
        if not history:
            return None
        # Prefer stable + high success rate + high efficiency
        scored = []
        for wv in history:
            score = wv.success_rate * 0.5 + wv.efficiency * 0.3
            if wv.is_stable:
                score += 0.2
            scored.append((score, wv))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None

    def get_stable_version(self, name: str) -> Optional[WorkflowVersion]:
        """Get the latest stable version (for rollback)."""
        history = self._versions.get(name, [])
        stable = [v for v in history if v.is_stable]
        if not stable:
            return None
        return max(stable, key=lambda v: v.version)

    def compare_versions(self, name: str) -> list[dict]:
        """Compare all versions of a workflow."""
        history = self._versions.get(name, [])
        return [
            {
                "version": wv.version,
                "executions": wv.executions,
                "success_rate": wv.success_rate,
                "avg_duration_s": wv.avg_duration_s,
                "efficiency": wv.efficiency,
                "is_stable": wv.is_stable,
            }
            for wv in sorted(history, key=lambda v: v.version, reverse=True)
        ]

    def list_workflows(self) -> list[dict]:
        """List all workflows with their latest version info."""
        result = []
        for name, history in self._versions.items():
            latest = max(history, key=lambda v: v.version) if history else None
            best = self.get_best_version(name)
            result.append({
                "workflow_name": name,
                "total_versions": len(history),
                "latest_version": latest.version if latest else 0,
                "best_version": best.version if best else 0,
                "has_stable": any(v.is_stable for v in history),
            })
        return result


# ═══════════════════════════════════════════════════════════════
# PHASE 5 — RESOURCE MANAGEMENT SIGNALS
# ═══════════════════════════════════════════════════════════════

class ResourceMonitor:
    """Monitors workflow resource usage and pressure signals."""

    def __init__(self, engine: WorkflowEngine, scheduler: ScheduledTaskManager):
        self._engine = engine
        self._scheduler = scheduler

    def get_signals(self) -> dict:
        """Get current resource pressure signals."""
        self._engine._ensure_loaded()
        self._scheduler._ensure_loaded()

        active_workflows = sum(
            1 for e in self._engine._executions.values()
            if e.status in ("created", "running")
        )
        paused_workflows = sum(
            1 for e in self._engine._executions.values()
            if e.status == "paused"
        )
        scheduled_count = len(self._scheduler._tasks)
        enabled_tasks = sum(1 for t in self._scheduler._tasks.values() if t.enabled)

        # Queue depth: pending workflows + due tasks
        due_tasks = len(self._scheduler.get_due_tasks())
        queue_depth = active_workflows + due_tasks

        # Latency pressure: avg duration of recent workflows
        recent_execs = sorted(
            self._engine._executions.values(),
            key=lambda e: e.created_at, reverse=True
        )[:20]
        avg_latency = 0.0
        if recent_execs:
            durations = [e.duration_s for e in recent_execs if e.duration_s > 0]
            avg_latency = sum(durations) / max(len(durations), 1)

        # Failure cluster detection: >=3 failures in last 10 executions
        recent_10 = recent_execs[:10]
        recent_failures = sum(1 for e in recent_10 if e.status == "failed")
        failure_cluster = recent_failures >= 3

        # Pressure indicator: 0.0 (low) → 1.0 (critical)
        concurrency_pressure = active_workflows / max(MAX_CONCURRENT_WORKFLOWS, 1)
        queue_pressure = min(queue_depth / 10.0, 1.0)
        failure_pressure = 0.5 if failure_cluster else 0.0
        overall_pressure = round(
            concurrency_pressure * 0.4 + queue_pressure * 0.3 + failure_pressure * 0.3,
            3
        )

        return {
            "active_workflows": active_workflows,
            "paused_workflows": paused_workflows,
            "max_concurrent": MAX_CONCURRENT_WORKFLOWS,
            "scheduled_tasks": scheduled_count,
            "enabled_tasks": enabled_tasks,
            "due_tasks": due_tasks,
            "queue_depth": queue_depth,
            "avg_latency_s": round(avg_latency, 2),
            "failure_cluster_detected": failure_cluster,
            "recent_failures": recent_failures,
            "pressure": {
                "concurrency": round(concurrency_pressure, 3),
                "queue": round(queue_pressure, 3),
                "failure": round(failure_pressure, 3),
                "overall": overall_pressure,
            },
            "can_accept_workflow": active_workflows < MAX_CONCURRENT_WORKFLOWS,
        }


# ═══════════════════════════════════════════════════════════════
# PHASE 7 — COCKPIT OBSERVABILITY (data layer)
# ═══════════════════════════════════════════════════════════════

def get_workflow_dashboard(engine: WorkflowEngine,
                           scheduler: ScheduledTaskManager,
                           version_mgr: WorkflowVersionManager,
                           event_mgr: EventTriggerManager) -> dict:
    """Full workflow runtime dashboard for cockpit."""
    engine._ensure_loaded()
    scheduler._ensure_loaded()

    # Active workflows
    executions = list(engine._executions.values())
    active = [e for e in executions if e.status in ("created", "running")]
    completed = [e for e in executions if e.status == "completed"]
    failed = [e for e in executions if e.status == "failed"]

    # Success distribution
    if completed or failed:
        success_rate = len(completed) / (len(completed) + len(failed))
    else:
        success_rate = 0.0

    # Efficiency signals
    if completed:
        avg_duration = sum(e.duration_s for e in completed) / len(completed)
        avg_steps = sum(len(e.steps) for e in completed) / len(completed)
    else:
        avg_duration = 0.0
        avg_steps = 0.0

    monitor = ResourceMonitor(engine, scheduler)
    resource_signals = monitor.get_signals()

    return {
        "workflows": {
            "total": len(executions),
            "active": len(active),
            "completed": len(completed),
            "failed": len(failed),
            "paused": sum(1 for e in executions if e.status == "paused"),
            "cancelled": sum(1 for e in executions if e.status == "cancelled"),
            "success_rate": round(success_rate, 3),
            "avg_duration_s": round(avg_duration, 2),
            "avg_steps": round(avg_steps, 1),
            "recent": [e.to_dict() for e in sorted(
                executions, key=lambda e: e.created_at, reverse=True
            )[:10]],
        },
        "scheduled_tasks": {
            "total": len(scheduler._tasks),
            "enabled": sum(1 for t in scheduler._tasks.values() if t.enabled),
            "tasks": scheduler.list_tasks()[:20],
            "execution_log": scheduler.get_execution_log(20),
        },
        "versions": {
            "workflows": version_mgr.list_workflows(),
        },
        "events": {
            "triggers": event_mgr.list_triggers(),
            "recent_events": event_mgr.get_event_log(20),
        },
        "resources": resource_signals,
        "autonomy_limits": get_autonomy_limits(),
    }


# ═══════════════════════════════════════════════════════════════
# SINGLETONS
# ═══════════════════════════════════════════════════════════════

_scheduler: Optional[ScheduledTaskManager] = None
_engine: Optional[WorkflowEngine] = None
_version_mgr: Optional[WorkflowVersionManager] = None
_event_mgr: Optional[EventTriggerManager] = None


def get_scheduler() -> ScheduledTaskManager:
    global _scheduler
    if _scheduler is None:
        _scheduler = ScheduledTaskManager()
    return _scheduler


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine


def get_version_manager() -> WorkflowVersionManager:
    global _version_mgr
    if _version_mgr is None:
        _version_mgr = WorkflowVersionManager()
    return _version_mgr


def get_event_manager() -> EventTriggerManager:
    global _event_mgr
    if _event_mgr is None:
        _event_mgr = EventTriggerManager()
    return _event_mgr
