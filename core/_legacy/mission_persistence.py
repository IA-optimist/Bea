"""
core/mission_persistence.py — Durable mission state persistence.

Bridges MetaOrchestrator's in-memory MissionContext with a JSON-file store
so that mission state survives process restarts.

Architecture:
  - MetaOrchestrator remains authoritative for ACTIVE mission logic
  - This store is authoritative for PERSISTED mission history
  - On restart, MetaOrchestrator recovers non-terminal missions from here
  - All writes are fail-open (journal, not gate)

Not a second mission system. Not a replacement for MetaOrchestrator.
"""
from __future__ import annotations

import json
import os
import threading
import time
import structlog
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = structlog.get_logger("mission_persistence")

_PERSIST_DIR = Path(os.environ.get("WORKSPACE_DIR", "workspace")) / "missions"
_PERSIST_FILE = _PERSIST_DIR / "mission_state.json"
_MAX_MISSIONS = 500


# ── Persisted mission record ──────────────────────────────────

@dataclass
class PersistedMission:
    """Flat record of a mission's state for durable storage."""
    mission_id: str
    goal: str
    mode: str = "auto"
    status: str = "CREATED"
    created_at: float = 0.0
    updated_at: float = 0.0
    result: str = ""
    error: str = ""
    phase: str = ""
    routed_capability: str = ""
    routed_provider: str = ""
    approval_item_id: str = ""
    approval_status: str = ""  # "", "pending", "granted", "denied"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal": self.goal[:500],
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": (self.result or "")[:1000],
            "error": (self.error or "")[:500],
            "phase": self.phase,
            "routed_capability": self.routed_capability,
            "routed_provider": self.routed_provider,
            "approval_item_id": self.approval_item_id,
            "approval_status": self.approval_status,
            "metadata": {k: str(v)[:200] for k, v in (self.metadata or {}).items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PersistedMission":
        return cls(
            mission_id=d.get("mission_id", ""),
            goal=d.get("goal", ""),
            mode=d.get("mode", "auto"),
            status=d.get("status", "CREATED"),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            result=d.get("result", ""),
            error=d.get("error", ""),
            phase=d.get("phase", ""),
            routed_capability=d.get("routed_capability", ""),
            routed_provider=d.get("routed_provider", ""),
            approval_item_id=d.get("approval_item_id", ""),
            approval_status=d.get("approval_status", ""),
            metadata=d.get("metadata", {}),
        )

    @classmethod
    def from_mission_context(cls, ctx) -> "PersistedMission":
        """Convert a MetaOrchestrator MissionContext to a persisted record."""
        meta = getattr(ctx, "metadata", {}) or {}
        routing = meta.get("routing_decision", {})
        return cls(
            mission_id=ctx.mission_id,
            goal=ctx.goal,
            mode=ctx.mode,
            status=ctx.status.value if hasattr(ctx.status, "value") else str(ctx.status),
            created_at=ctx.created_at,
            updated_at=ctx.updated_at,
            result=ctx.result or "",
            error=ctx.error or "",
            phase=meta.get("current_phase", ""),
            routed_capability=routing.get("capability_id", ""),
            routed_provider=routing.get("provider_id", ""),
            approval_item_id=meta.get("approval_item_id", ""),
            approval_status=meta.get("approval_status", ""),
            metadata={
                k: v for k, v in meta.items()
                if k not in ("routing_decision", "approval_item_id", "approval_status")
                and not isinstance(v, (list, dict))
            },
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in ("DONE", "FAILED", "CANCELLED", "REJECTED")

    @property
    def is_awaiting_approval(self) -> bool:
        return self.status == "AWAITING_APPROVAL" or self.approval_status == "pending"


# ── Persistence store ─────────────────────────────────────────

class MissionPersistenceStore:
    """
    Thread-safe JSON-backed mission state store.

    Provides:
      - persist(ctx) — save/update mission from MissionContext
      - load_all() — reload from disk
      - get(mid) — single mission lookup
      - list_by_status(status) — filtered query
      - recover_non_terminal() — missions to resume after restart
      - resolve_approval(mid, granted) — mark approval outcome
    """

    def __init__(self, persist_dir: str | Path | None = None):
        self._lock = threading.RLock()  # Reentrant — _save() called while lock held
        self._missions: dict[str, PersistedMission] = {}
        self._persist_dir = Path(persist_dir) if persist_dir else _PERSIST_DIR
        self._persist_file = self._persist_dir / "mission_state.json"
        self._load()

    # ── Write operations ──────────────────────────────────────

    def persist(self, ctx_or_record) -> PersistedMission:
        """Persist a MissionContext or PersistedMission. Returns the record."""
        if isinstance(ctx_or_record, PersistedMission):
            record = ctx_or_record
        else:
            record = PersistedMission.from_mission_context(ctx_or_record)
        record.updated_at = time.time()

        with self._lock:
            self._missions[record.mission_id] = record
            self._evict_if_needed()

        self._save()
        return record

    def update_status(self, mission_id: str, status: str, **kwargs) -> PersistedMission | None:
        """Update status + optional fields for a mission."""
        with self._lock:
            record = self._missions.get(mission_id)
            if not record:
                return None
            record.status = status
            record.updated_at = time.time()
            for k, v in kwargs.items():
                if hasattr(record, k):
                    setattr(record, k, v)
        self._save()
        return record

    def resolve_approval(
        self, mission_id: str, granted: bool, reason: str = ""
    ) -> PersistedMission | None:
        """
        Mark approval outcome for a paused mission.

        granted=True  → status=RUNNING, approval_status=granted
        granted=False → status=FAILED,  approval_status=denied
        """
        with self._lock:
            record = self._missions.get(mission_id)
            if not record:
                log.warning("approval_resolve.mission_not_found", mission_id=mission_id)
                return None
            if not record.is_awaiting_approval:
                log.warning("approval_resolve.not_awaiting",
                           mission_id=mission_id, status=record.status)
                return None

            record.approval_status = "granted" if granted else "denied"
            record.updated_at = time.time()
            if granted:
                record.status = "RUNNING"
                record.error = ""
            else:
                record.status = "FAILED"
                record.error = f"Approval denied: {reason}" if reason else "Approval denied"

        self._save()
        log.info("approval_resolved", mission_id=mission_id,
                 granted=granted, status=record.status)
        return record

    def delete(self, mission_id: str) -> bool:
        """Remove a mission from the store."""
        with self._lock:
            if mission_id in self._missions:
                del self._missions[mission_id]
                self._save()
                return True
        return False

    # ── Read operations ───────────────────────────────────────

    def get(self, mission_id: str) -> PersistedMission | None:
        with self._lock:
            return self._missions.get(mission_id)

    def list_all(self, limit: int = 100) -> list[PersistedMission]:
        with self._lock:
            missions = sorted(
                self._missions.values(),
                key=lambda m: m.updated_at,
                reverse=True,
            )
            return missions[:limit]

    def list_by_status(self, status: str, limit: int = 50) -> list[PersistedMission]:
        with self._lock:
            return sorted(
                [m for m in self._missions.values() if m.status == status],
                key=lambda m: m.updated_at,
                reverse=True,
            )[:limit]

    def list_active(self) -> list[PersistedMission]:
        """Non-terminal missions."""
        with self._lock:
            return [m for m in self._missions.values() if not m.is_terminal]

    def list_awaiting_approval(self) -> list[PersistedMission]:
        with self._lock:
            return [m for m in self._missions.values() if m.is_awaiting_approval]

    def recover_non_terminal(self) -> list[PersistedMission]:
        """
        Return missions that were active at last shutdown.
        Used by startup recovery to decide what to resume.

        Returns only RUNNING or AWAITING_APPROVAL missions,
        NOT CREATED/PLANNED (those haven't started execution).
        """
        with self._lock:
            return [
                m for m in self._missions.values()
                if m.status in ("RUNNING", "AWAITING_APPROVAL", "REVIEW", "PLANNED")
            ]

    def stats(self) -> dict:
        with self._lock:
            by_status: dict[str, int] = {}
            for m in self._missions.values():
                by_status[m.status] = by_status.get(m.status, 0) + 1
            return {
                "total": len(self._missions),
                "by_status": by_status,
                "awaiting_approval": sum(
                    1 for m in self._missions.values() if m.is_awaiting_approval
                ),
                "persist_file": str(self._persist_file),
            }

    # ── Disk I/O ──────────────────────────────────────────────

    def _save(self) -> None:
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "version": 1,
                    "saved_at": time.time(),
                    "missions": {
                        mid: m.to_dict()
                        for mid, m in self._missions.items()
                    },
                }
            # Atomic write: write to temp then rename
            tmp = self._persist_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
            tmp.rename(self._persist_file)
        except Exception as e:
            log.warning("mission_persist_save_failed", err=str(e)[:100])

    def _load(self) -> None:
        try:
            if not self._persist_file.exists():
                return
            data = json.loads(self._persist_file.read_text("utf-8"))
            missions = data.get("missions", {})
            for mid, d in missions.items():
                try:
                    self._missions[mid] = PersistedMission.from_dict(d)
                except Exception:
                    continue
            log.info("mission_persist_loaded", count=len(self._missions))
        except Exception as e:
            log.warning("mission_persist_load_failed", err=str(e)[:100])

    def _evict_if_needed(self) -> None:
        """Evict oldest terminal missions if over capacity."""
        if len(self._missions) <= _MAX_MISSIONS:
            return
        terminal = sorted(
            [m for m in self._missions.values() if m.is_terminal],
            key=lambda m: m.updated_at,
        )
        while len(self._missions) > _MAX_MISSIONS and terminal:
            oldest = terminal.pop(0)
            del self._missions[oldest.mission_id]


# ── Singleton ─────────────────────────────────────────────────

_store: MissionPersistenceStore | None = None
_store_lock = threading.Lock()


def get_mission_persistence() -> MissionPersistenceStore:
    """Get or create the singleton mission persistence store."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = MissionPersistenceStore()
    return _store
