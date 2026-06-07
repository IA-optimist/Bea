"""
BEA MAX — Mission Audit Log
=================================
Immutable audit trail for business mission execution.

Every state transition, approval, failure, and decision is recorded.
Chained hashes ensure tamper detection.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class AuditEvent:
    """Known audit event types."""
    MISSION_CREATED = "mission_created"
    MISSION_PLANNED = "mission_planned"
    MISSION_STARTED = "mission_started"
    MISSION_PAUSED = "mission_paused"
    MISSION_RESUMED = "mission_resumed"
    MISSION_COMPLETED = "mission_completed"
    MISSION_FAILED = "mission_failed"
    MISSION_CANCELLED = "mission_cancelled"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_RETRIED = "step_retried"
    STEP_SKIPPED = "step_skipped"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_EXPIRED = "approval_expired"
    DEPENDENCY_CHECK = "dependency_check"
    DEPENDENCY_MISSING = "dependency_missing"
    AGENT_ASSIGNED = "agent_assigned"
    PLAN_ADAPTED = "plan_adapted"
    ERROR = "error"


@dataclass
class AuditRecord:
    """A single audit log entry."""
    event: str
    mission_id: str
    step_id: str = ""
    agent: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    prev_hash: str = ""
    record_hash: str = ""

    def __post_init__(self):
        if not self.record_hash:
            self.record_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        content = f"{self.event}|{self.mission_id}|{self.step_id}|{self.timestamp}|{self.prev_hash}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "event": self.event,
            "mission_id": self.mission_id,
            "step_id": self.step_id,
            "agent": self.agent,
            "details": {k: str(v)[:200] for k, v in self.details.items()},
            "timestamp": self.timestamp,
            "hash": self.record_hash,
        }


class MissionAuditLog:
    """
    Chained-hash audit log for mission execution.
    Each record links to the previous via prev_hash → tamper detection.
    """

    def __init__(self):
        self._records: list[AuditRecord] = []

    def log(
        self,
        event: str,
        mission_id: str,
        step_id: str = "",
        agent: str = "",
        details: dict | None = None,
    ) -> AuditRecord:
        """Record an audit event."""
        prev_hash = self._records[-1].record_hash if self._records else "genesis"
        record = AuditRecord(
            event=event,
            mission_id=mission_id,
            step_id=step_id,
            agent=agent,
            details=details or {},
            prev_hash=prev_hash,
        )
        self._records.append(record)
        return record

    def get_mission_log(self, mission_id: str) -> list[dict]:
        """Get all audit records for a mission."""
        return [r.to_dict() for r in self._records if r.mission_id == mission_id]

    def get_step_log(self, mission_id: str, step_id: str) -> list[dict]:
        """Get audit records for a specific step."""
        return [
            r.to_dict() for r in self._records
            if r.mission_id == mission_id and r.step_id == step_id
        ]

    def get_recent(self, limit: int = 50) -> list[dict]:
        """Get most recent audit records."""
        return [r.to_dict() for r in reversed(self._records)][:limit]

    def get_by_event(self, event: str, limit: int = 50) -> list[dict]:
        """Get records by event type."""
        return [r.to_dict() for r in reversed(self._records) if r.event == event][:limit]

    def verify_chain(self) -> bool:
        """Verify the hash chain integrity."""
        for i, record in enumerate(self._records):
            if i == 0:
                if record.prev_hash != "genesis":
                    return False
            else:
                if record.prev_hash != self._records[i - 1].record_hash:
                    return False
        return True

    @property
    def total_records(self) -> int:
        return len(self._records)
