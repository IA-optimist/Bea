"""Mission state compatibility layer for MetaOrchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.state import MissionStatus

try:
    from kernel.state.mission_state import (
        MissionContext,
        VALID_TRANSITIONS as _VALID_TRANSITIONS,
        get_state_machine as _get_kernel_sm,
    )
    _KERNEL_STATE_AVAILABLE = True
except ImportError:
    _KERNEL_STATE_AVAILABLE = False
    _get_kernel_sm = None  # type: ignore[assignment]

    _VALID_TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
        MissionStatus.CREATED: {MissionStatus.PLANNED, MissionStatus.FAILED},
        MissionStatus.PLANNED: {MissionStatus.RUNNING, MissionStatus.FAILED},
        MissionStatus.RUNNING: {
            MissionStatus.REVIEW,
            MissionStatus.FAILED,
            MissionStatus.AWAITING_APPROVAL,
        },
        MissionStatus.AWAITING_APPROVAL: {
            MissionStatus.RUNNING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        },
        MissionStatus.REVIEW: {
            MissionStatus.DONE,
            MissionStatus.RUNNING,
            MissionStatus.FAILED,
        },
        MissionStatus.DONE: set(),
        MissionStatus.FAILED: set(),
    }

    @dataclass
    class MissionContext:  # type: ignore[no-redef]
        """Fallback matching the kernel MissionContext contract."""

        mission_id: str
        goal: str
        mode: str
        status: MissionStatus
        created_at: float
        updated_at: float
        result: str | None = None
        error: str | None = None
        metadata: dict = field(default_factory=dict)
        project_id: str | None = None

        def get_output(self, agent: str) -> str:
            outputs = self.metadata.get("agent_outputs", {})
            if isinstance(outputs, dict):
                out = outputs.get(agent, "")
                return out if isinstance(out, str) else str(out) if out else ""
            return ""

        def to_dict(self) -> dict:
            return {
                "mission_id": self.mission_id,
                "goal": self.goal[:200],
                "mode": self.mode,
                "status": self.status.value,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "result": (self.result or "")[:500],
                "error": self.error,
                "metadata": self.metadata,
            }


__all__ = [
    "MissionContext",
    "MissionStatus",
    "_KERNEL_STATE_AVAILABLE",
    "_VALID_TRANSITIONS",
    "_get_kernel_sm",
]
