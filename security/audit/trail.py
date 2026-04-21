"""
security/audit/trail.py — Immutable audit trail for JarvisMax (Pass 17).

Every security decision (allow / deny / escalate) is recorded here.
The trail is append-only: entries cannot be modified or deleted.

R10: security not decorative — every sensitive action leaves a trace.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger("security.audit")


# ══════════════════════════════════════════════════════════════════════════════
# Enumerations
# ══════════════════════════════════════════════════════════════════════════════

class AuditDecision(str, Enum):
    ALLOWED   = "allowed"
    DENIED    = "denied"
    ESCALATED = "escalated"   # forwarded to human approval
    PENDING   = "pending"     # awaiting decision


# ══════════════════════════════════════════════════════════════════════════════
# AuditEntry
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)  # frozen = immutable after creation
class AuditEntry:
    """
    A single immutable audit record.

    frozen=True enforces append-only semantics: once created,
    no field can be modified.
    """
    entry_id:    str
    timestamp:   float
    mission_id:  str
    action_type: str
    action_target: str
    risk_level:  str
    decision:    AuditDecision
    reason:      str
    decided_by:  str           # "kernel.policy" | "security.layer" | "operator"
    metadata:    str = "{}"    # JSON string (frozen dataclass can't hold mutable dict)

    def to_dict(self) -> dict:
        return {
            "entry_id":      self.entry_id,
            "timestamp":     self.timestamp,
            "mission_id":    self.mission_id,
            "action_type":   self.action_type,
            "action_target": self.action_target,
            "risk_level":    self.risk_level,
            "decision":      self.decision.value,
            "reason":        self.reason,
            "decided_by":    self.decided_by,
            "metadata":      json.loads(self.metadata) if self.metadata else {},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def make_audit_entry(
    *,
    mission_id: str = "",
    action_type: str = "",
    action_target: str = "",
    risk_level: str = "low",
    decision: AuditDecision,
    reason: str = "",
    decided_by: str = "security.layer",
    metadata: Optional[dict] = None,
) -> AuditEntry:
    """Factory function for AuditEntry (frozen dataclass constructor helper)."""
    return AuditEntry(
        entry_id=f"audit-{uuid.uuid4().hex[:10]}",
        timestamp=time.time(),
        mission_id=mission_id,
        action_type=action_type,
        action_target=action_target[:200],
        risk_level=risk_level,
        decision=decision,
        reason=reason[:500],
        decided_by=decided_by,
        metadata=json.dumps(metadata or {}, ensure_ascii=False),
    )


# ══════════════════════════════════════════════════════════════════════════════
# AuditTrail — append-only storage
# ══════════════════════════════════════════════════════════════════════════════

class AuditTrail:
    """
    Append-only audit trail with optional JSONL file persistence.

    In-memory ring buffer (default 10 000 entries) + optional file sink.
    File path is resolved from env JARVIS_AUDIT_LOG or defaults to
    logs/security_audit.jsonl relative to the project root.
    """

    DEFAULT_MAX_MEMORY = 10_000

    def __init__(
        self,
        file_path: Optional[str] = None,
        max_memory: int = DEFAULT_MAX_MEMORY,
    ) -> None:
        self._entries: list[AuditEntry] = []
        self._max_memory = max_memory

        # Resolve file path
        _env_path = os.getenv("JARVIS_AUDIT_LOG", "")
        self._file_path: Optional[Path] = None
        raw = file_path or _env_path
        if raw:
            p = Path(raw)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                self._file_path = p
            except Exception as e:
                log.warning("audit_trail_file_init_failed", path=str(p), err=str(e))

    # ── Append ────────────────────────────────────────────────────────────────

    def record(self, entry: AuditEntry) -> None:
        """Append entry to in-memory buffer and optional file sink."""
        # Memory: ring buffer
        if len(self._entries) >= self._max_memory:
            self._entries = self._entries[-(self._max_memory // 2):]
        self._entries.append(entry)

        # File: JSONL append
        if self._file_path:
            try:
                with self._file_path.open("a", encoding="utf-8") as fh:
                    fh.write(entry.to_json() + "\n")
            except Exception as e:
                log.warning("audit_trail_write_failed", err=str(e)[:100])

        log.info(
            "security_audit",
            entry_id=entry.entry_id,
            decision=entry.decision.value,
            action_type=entry.action_type,
            risk=entry.risk_level,
            mission_id=entry.mission_id,
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def recent(self, n: int = 50) -> list[AuditEntry]:
        """Return the n most recent entries (newest first)."""
        return list(reversed(self._entries[-n:]))

    def by_mission(self, mission_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.mission_id == mission_id]

    def by_decision(self, decision: AuditDecision) -> list[AuditEntry]:
        return [e for e in self._entries if e.decision == decision]

    def denied_count(self) -> int:
        return sum(1 for e in self._entries if e.decision == AuditDecision.DENIED)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"AuditTrail(entries={len(self._entries)}, file={self._file_path})"


# Module-level singleton
_trail: Optional[AuditTrail] = None


def get_audit_trail() -> AuditTrail:
    """
    Return the module-level AuditTrail singleton.

    BLOC 4 fix: default singleton now uses file persistence so the audit trail
    survives process restarts. Path resolution order:
      1. Constructor arg (if called directly with file_path)
      2. JARVIS_AUDIT_LOG env var
      3. Default: logs/security_audit.jsonl (relative to cwd / project root)

    The `logs/` directory is created on first write if missing.
    """
    global _trail
    if _trail is None:
        _default_path = os.getenv("JARVIS_AUDIT_LOG", "logs/security_audit.jsonl")
        _trail = AuditTrail(file_path=_default_path)
    return _trail
