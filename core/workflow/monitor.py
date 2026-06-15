"""
BEA Workflow — Resource Monitor & Cockpit Dashboard (Phases 5+7)
=================================================================
ResourceMonitor: concurrency/queue pressure signals.
get_workflow_dashboard: full cockpit observability snapshot.
"""
from __future__ import annotations

from .boundaries import MAX_CONCURRENT_WORKFLOWS, get_autonomy_limits
from .executor import WorkflowEngine
from .events import EventTriggerManager, WorkflowVersionManager
from .scheduler import ScheduledTaskManager


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

        due_tasks = len(self._scheduler.get_due_tasks())
        queue_depth = active_workflows + due_tasks

        recent_execs = sorted(
            self._engine._executions.values(),
            key=lambda e: e.created_at, reverse=True
        )[:20]
        avg_latency = 0.0
        if recent_execs:
            durations = [e.duration_s for e in recent_execs if e.duration_s > 0]
            avg_latency = sum(durations) / max(len(durations), 1)

        recent_10 = recent_execs[:10]
        recent_failures = sum(1 for e in recent_10 if e.status == "failed")
        failure_cluster = recent_failures >= 3

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


def get_workflow_dashboard(engine: WorkflowEngine,
                           scheduler: ScheduledTaskManager,
                           version_mgr: WorkflowVersionManager,
                           event_mgr: EventTriggerManager) -> dict:
    """Full workflow runtime dashboard for cockpit."""
    engine._ensure_loaded()
    scheduler._ensure_loaded()

    executions = list(engine._executions.values())
    active = [e for e in executions if e.status in ("created", "running")]
    completed = [e for e in executions if e.status == "completed"]
    failed = [e for e in executions if e.status == "failed"]

    if completed or failed:
        success_rate = len(completed) / (len(completed) + len(failed))
    else:
        success_rate = 0.0

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
