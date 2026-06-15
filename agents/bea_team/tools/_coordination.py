"""Agent coordination tools for bea-team agents."""
from __future__ import annotations

import time

from ._base import ToolResult, _timed


@_timed
def tool_create_task(agent: str, description: str, priority: int = 2,
                     depends_on: list[str] | None = None) -> ToolResult:
    """Create a task description for an agent."""
    task = {
        "agent": agent,
        "description": description[:500],
        "priority": max(1, min(4, priority)),
        "depends_on": depends_on or [],
        "created_at": time.time(),
        "status": "pending",
    }
    return ToolResult(success=True, tool="create_task", data=task)


@_timed
def tool_report_status(agent: str, task: str, status: str,
                       output: str = "", error: str = "") -> ToolResult:
    """Report status from an agent on a task."""
    valid_statuses = {"pending", "running", "completed", "failed", "blocked"}
    if status not in valid_statuses:
        return ToolResult(
            success=False, tool="report_status",
            error=f"Invalid status: {status}. Must be one of {valid_statuses}",
        )
    return ToolResult(
        success=True, tool="report_status",
        data={
            "agent": agent, "task": task[:200], "status": status,
            "output": output[:1000], "error": error[:500],
            "timestamp": time.time(),
        },
    )
