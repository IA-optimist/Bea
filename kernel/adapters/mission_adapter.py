"""
kernel/adapters/mission_adapter.py — Bidirectional adapter: MissionContext ↔ kernel Mission.

Handles the structural mismatch between:
  - core.meta_orchestrator.MissionContext (runtime, uppercase statuses, goal as string)
  - kernel.contracts.Mission (kernel, lowercase statuses, goal as Goal object)

Zero modifications to either source type.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.contracts.types import Mission


# ── Status mapping ────────────────────────────────────────────
# core.state.MissionStatus uses UPPERCASE strings
# kernel.contracts.MissionStatus uses lowercase strings

_CORE_TO_KERNEL_STATUS = {
    # core.state.MissionStatus → kernel MissionStatus
    "CREATED":            "pending",
    "ANALYZING":          "planning",
    "PENDING_VALIDATION": "awaiting_approval",
    "APPROVED":           "executing",
    "EXECUTING":          "executing",
    "RUNNING":            "executing",
    "DONE":               "completed",
    "REJECTED":           "cancelled",
    "BLOCKED":            "failed",
    "PLAN_ONLY":          "completed",
    "PLANNED":            "planning",
    "AWAITING_APPROVAL":  "awaiting_approval",
    "REVIEW":             "awaiting_approval",
    "FAILED":             "failed",
}

_KERNEL_TO_CORE_STATUS = {
    # kernel MissionStatus → core.state.MissionStatus (best fit)
    "pending":            "CREATED",
    "planning":           "ANALYZING",
    "executing":          "EXECUTING",
    "awaiting_approval":  "AWAITING_APPROVAL",
    "completed":          "DONE",
    "failed":             "FAILED",
    "cancelled":          "REJECTED",
}


def mission_context_to_kernel(ctx) -> "Mission":
    """
    Convert a core.meta_orchestrator.MissionContext to a kernel Mission.

    Args:
        ctx: MissionContext (or any object with mission_id, goal, status, etc.)

    Returns:
        kernel.contracts.Mission
    """
    from kernel.contracts.types import Mission, Goal, MissionStatus

    status_str = ctx.status.value if hasattr(ctx.status, "value") else str(ctx.status)
    kernel_status_str = _CORE_TO_KERNEL_STATUS.get(status_str, "pending")

    return Mission(
        mission_id=ctx.mission_id,
        goal=Goal(
            description=ctx.goal if isinstance(ctx.goal, str) else str(ctx.goal),
            source=getattr(ctx, "mode", ""),
        ),
        status=MissionStatus(kernel_status_str),
        created_at=getattr(ctx, "created_at", 0),
        updated_at=getattr(ctx, "updated_at", 0),
        metadata=getattr(ctx, "metadata", {}),
    )


def kernel_mission_to_context(mission) -> dict:
    """
    Convert a kernel Mission to a dict compatible with MissionContext construction.

    Returns a dict (not MissionContext directly) to avoid importing the class
    and to let the caller decide how to construct.
    """
    status_str = mission.status.value if hasattr(mission.status, "value") else str(mission.status)
    core_status = _KERNEL_TO_CORE_STATUS.get(status_str, "CREATED")

    return {
        "mission_id": mission.mission_id,
        "goal": mission.goal.description if hasattr(mission.goal, "description") else str(mission.goal),
        "mode": mission.goal.source if hasattr(mission.goal, "source") else "",
        "status": core_status,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
        "metadata": mission.metadata,
    }


def core_status_to_kernel(core_status_value: str) -> str:
    """Map a core MissionStatus value to kernel MissionStatus value."""
    return _CORE_TO_KERNEL_STATUS.get(core_status_value, "pending")


def kernel_status_to_core(kernel_status_value: str) -> str:
    """Map a kernel MissionStatus value to core MissionStatus value."""
    return _KERNEL_TO_CORE_STATUS.get(kernel_status_value, "CREATED")
