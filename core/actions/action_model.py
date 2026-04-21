"""
core/actions/action_model.py — Canonical Action model.

Single source of truth for the execution lifecycle.
Maps legacy Action (action_queue) and BackgroundTask (task_queue) states
to a unified status model.
"""
from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional
_silent_log = __import__("structlog").get_logger(__name__)

log = logging.getLogger("jarvis.actions")


# ── Canonical status ──────────────────────────────────────────────────────────

ActionStatus = Literal[
    "PENDING",
    "APPROVAL_REQUIRED",
    "APPROVED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]

# Legacy → Canonical mapping
_LEGACY_STATUS_MAP: dict[str, ActionStatus] = {
    # From action_queue.ActionStatus
    "PENDING":  "PENDING",
    "APPROVED": "APPROVED",
    "REJECTED": "CANCELLED",
    "EXECUTED": "COMPLETED",
    "FAILED":   "FAILED",
    # From task_queue.TaskState
    "pending":   "PENDING",
    "running":   "RUNNING",
    "done":      "COMPLETED",
    "failed":    "FAILED",
    "cancelled": "CANCELLED",
}


def canonicalize_status(legacy_status: str) -> ActionStatus:
    """Map any legacy status to canonical. Defaults to PENDING."""
    return _LEGACY_STATUS_MAP.get(legacy_status, _LEGACY_STATUS_MAP.get(legacy_status.upper(), "PENDING"))


# ── Canonical Action ──────────────────────────────────────────────────────────

@dataclass
class CanonicalAction:
    """
    Unified action model for all execution lifecycle operations.

    Replaces the need to reason about Action (action_queue) vs
    BackgroundTask (task_queue) separately.
    """
    action_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    mission_id: str = ""
    trace_id: str = ""
    status: str = "PENDING"  # ActionStatus

    # What to do
    tool_name: str = ""
    description: str = ""
    input_payload: dict = field(default_factory=dict)

    # Result
    result_payload: Optional[dict] = None
    result_text: str = ""
    error: str = ""

    # Risk/approval
    risk_level: str = "MEDIUM"
    requires_approval: bool = False

    # Timing
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # ── Lifecycle transitions ─────────────────────────────────────────────

    def request_approval(self) -> None:
        if self.status == "PENDING":
            self.status = "APPROVAL_REQUIRED"
            self._emit("approval_requested")

    def approve(self, note: str = "") -> None:
        if self.status in ("PENDING", "APPROVAL_REQUIRED"):
            self.status = "APPROVED"
            self._emit("action_approved", {"note": note})

    def start(self) -> None:
        if self.status in ("APPROVED", "PENDING"):
            self.status = "RUNNING"
            self.started_at = time.time()
            self._emit("action_started")

    def complete(self, result_text: str = "", result_payload: dict = None) -> None:
        if self.status in ("RUNNING", "APPROVED", "PENDING"):
            self.status = "COMPLETED"
            self.completed_at = time.time()
            self.result_text = result_text
            if result_payload:
                self.result_payload = result_payload
            self._emit("action_completed", {"result_length": len(result_text)})

    def fail(self, error: str = "") -> None:
        if self.status not in ("COMPLETED", "CANCELLED"):
            self.status = "FAILED"
            self.completed_at = time.time()
            self.error = error
            self._emit("action_failed", {"error": error[:200]})

    def cancel(self, reason: str = "") -> None:
        if self.status not in ("COMPLETED", "FAILED"):
            self.status = "CANCELLED"
            self.completed_at = time.time()
            self.error = reason
            self._emit("action_cancelled", {"reason": reason[:200]})

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def is_terminal(self) -> bool:
        return self.status in ("COMPLETED", "FAILED", "CANCELLED")

    @property
    def is_pending_approval(self) -> bool:
        return self.status == "APPROVAL_REQUIRED"

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return round(self.completed_at - self.started_at, 2)
        return None

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_terminal"] = self.is_terminal
        d["duration_seconds"] = self.duration_seconds
        return d

    # ── From legacy ───────────────────────────────────────────────────────

    @classmethod
    def from_legacy_action(cls, action) -> "CanonicalAction":
        """Build from core.action_queue.Action."""
        return cls(
            action_id=getattr(action, "id", ""),
            mission_id=getattr(action, "mission_id", ""),
            status=canonicalize_status(getattr(action, "status", "PENDING")),
            description=getattr(action, "description", ""),
            tool_name=getattr(action, "target", ""),
            risk_level=getattr(action, "risk", "MEDIUM"),
            requires_approval=getattr(action, "risk", "").upper() in ("HIGH", "CRITICAL"),
            result_text=getattr(action, "result", ""),
            created_at=getattr(action, "created_at", time.time()),
            started_at=getattr(action, "approved_at", None),
            completed_at=getattr(action, "executed_at", None),
        )

    @classmethod
    def from_legacy_task(cls, task) -> "CanonicalAction":
        """Build from core.task_queue.BackgroundTask."""
        return cls(
            action_id=getattr(task, "id", ""),
            mission_id=getattr(task, "mission_id", ""),
            status=canonicalize_status(getattr(task, "state", "pending")),
            description=getattr(task, "name", ""),
            input_payload=getattr(task, "payload", {}),
            result_text=str(getattr(task, "result", "") or ""),
            error=getattr(task, "error", ""),
            created_at=getattr(task, "created_at", time.time()),
        )

    # ── Event emission ────────────────────────────────────────────────────

    def _emit(self, event_name: str, extra: dict = None) -> None:
        try:
            from core.observability.event_envelope import get_event_collector, EventEnvelope
            collector = get_event_collector()
            collector.emit(EventEnvelope(
                trace_id=self.trace_id or "",
                mission_id=self.mission_id,
                component="executor",
                event_type="status_update",
                payload={
                    "event": event_name,
                    "action_id": self.action_id,
                    "status": self.status,
                    **(extra or {}),
                },
            ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='action_model.py')


# ── Facade for legacy queue access ────────────────────────────────────────────

def get_canonical_actions(mission_id: str) -> list[CanonicalAction]:
    """Get all actions for a mission from both legacy queues, as canonical."""
    actions: list[CanonicalAction] = []

    # From action_queue
    try:
        from core.action_queue import get_action_queue
        aq = get_action_queue()
        for a in aq.for_mission(mission_id):
            actions.append(CanonicalAction.from_legacy_action(a))
    except Exception:
        _silent_log.debug("suppressed_exception", src='action_model.py')

    # From task_queue (if different tasks exist)
    try:
        from core.task_queue import get_core_task_queue
        tq = get_core_task_queue()
        existing_ids = {a.action_id for a in actions}
        for t in tq.list_tasks():
            if getattr(t, "mission_id", "") == mission_id and t.id not in existing_ids:
                actions.append(CanonicalAction.from_legacy_task(t))
    except Exception:
        _silent_log.debug("suppressed_exception", src='action_model.py')

    actions.sort(key=lambda a: a.created_at)
    return actions
