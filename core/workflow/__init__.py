"""
core.workflow — BEA Workflow Runtime sub-package
=================================================
Public API re-exported for backward compatibility.
All symbols are also accessible via ``core.workflow_runtime`` (thin wrapper).

Sub-modules:
  boundaries  — autonomy constants + get_autonomy_limits()
  scheduler   — ScheduledTask / ScheduledTaskManager
  state       — WorkflowStep / WorkflowExecution (pure data)
  executor    — WorkflowEngine (I/O + execution logic)
  events      — EventTrigger / EventTriggerManager /
                WorkflowVersion / WorkflowVersionManager
  monitor     — ResourceMonitor / get_workflow_dashboard
"""

from .boundaries import (
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

from .scheduler import (
    ScheduledTask,
    ScheduledTaskManager,
)

from .state import (
    WorkflowStep,
    WorkflowExecution,
)

from .executor import (
    WorkflowEngine,
)

from .events import (
    EventTrigger,
    EventTriggerManager,
    VALID_EVENT_TYPES,
    WorkflowVersion,
    WorkflowVersionManager,
)

from .monitor import (
    ResourceMonitor,
    get_workflow_dashboard,
)

__all__ = [
    # boundaries
    "MAX_CONCURRENT_WORKFLOWS",
    "MAX_WORKFLOW_DEPTH",
    "MAX_TRIGGER_FREQUENCY_S",
    "MAX_RETRY_CYCLES",
    "MAX_SCHEDULED_TASKS",
    "MAX_EVENT_HANDLERS",
    "MAX_WORKFLOW_HISTORY",
    "MAX_EVENT_LOG",
    "MAX_VERSION_HISTORY",
    "get_autonomy_limits",
    # scheduler
    "ScheduledTask",
    "ScheduledTaskManager",
    # executor
    "WorkflowStep",
    "WorkflowExecution",
    "WorkflowEngine",
    # events
    "EventTrigger",
    "EventTriggerManager",
    "VALID_EVENT_TYPES",
    "WorkflowVersion",
    "WorkflowVersionManager",
    "ResourceMonitor",
    "get_workflow_dashboard",
]
