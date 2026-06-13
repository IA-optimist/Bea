"""
BEA — Autonomous Workflow Runtime  (thin wrapper — backward compat)
====================================================================
This module is kept for backward compatibility.
All implementation has been split into ``core/workflow/``:

  core.workflow.boundaries  — autonomy constants
  core.workflow.scheduler   — ScheduledTask / ScheduledTaskManager
  core.workflow.state       — WorkflowStep / WorkflowExecution (pure data)
  core.workflow.executor    — WorkflowEngine (I/O + execution logic)
  core.workflow.events      — EventTrigger / EventTriggerManager /
                              WorkflowVersion / WorkflowVersionManager
  core.workflow.monitor     — ResourceMonitor / get_workflow_dashboard

Existing imports ``from core.workflow_runtime import X`` continue to work.
"""
from __future__ import annotations

from typing import Optional

# ── Re-export everything from sub-package ──────────────────────────────────

from core.workflow.boundaries import (  # noqa: F401
    MAX_CONCURRENT_WORKFLOWS,
    MAX_WORKFLOW_DEPTH,
    MAX_TRIGGER_FREQUENCY_S,
    MAX_RETRY_CYCLES,
    MAX_SCHEDULED_TASKS,
    MAX_EVENT_HANDLERS,
    MAX_WORKFLOW_HISTORY,
    MAX_EVENT_LOG,
    MAX_VERSION_HISTORY,
    get_autonomy_limits,
)

from core.workflow.scheduler import (  # noqa: F401
    ScheduledTask,
    ScheduledTaskManager,
)

from core.workflow.state import (  # noqa: F401
    WorkflowStep,
    WorkflowExecution,
)

from core.workflow.executor import (  # noqa: F401
    WorkflowEngine,
)

from core.workflow.events import (  # noqa: F401
    EventTrigger,
    EventTriggerManager,
    VALID_EVENT_TYPES,
    WorkflowVersion,
    WorkflowVersionManager,
)

from core.workflow.monitor import (  # noqa: F401
    ResourceMonitor,
    get_workflow_dashboard,
)

# ── Singletons (kept here for global state coherence) ─────────────────────

import structlog

logger = structlog.get_logger("bea.workflow_runtime")
log = logger  # M3 emitter alias

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
