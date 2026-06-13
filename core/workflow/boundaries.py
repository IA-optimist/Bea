"""
BEA Workflow — Autonomy Boundaries
===================================
Constants and limits enforced across the entire workflow runtime.
All values are configurable via environment variables.
"""
from __future__ import annotations

import os

MAX_CONCURRENT_WORKFLOWS = int(os.environ.get("BEA_MAX_WORKFLOWS", "10"))
MAX_WORKFLOW_DEPTH = int(os.environ.get("BEA_MAX_WORKFLOW_DEPTH", "20"))
MAX_TRIGGER_FREQUENCY_S = int(os.environ.get("BEA_MIN_TRIGGER_INTERVAL", "60"))
MAX_RETRY_CYCLES = int(os.environ.get("BEA_MAX_RETRY_CYCLES", "5"))
MAX_SCHEDULED_TASKS = int(os.environ.get("BEA_MAX_SCHEDULED_TASKS", "50"))
MAX_EVENT_HANDLERS = int(os.environ.get("BEA_MAX_EVENT_HANDLERS", "30"))
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
