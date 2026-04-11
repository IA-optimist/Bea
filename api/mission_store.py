"""
JARVIS MAX — Phase 9 MissionStateStore
Thread-safe in-memory store for mission logs and summaries.
Persists to workspace/mission_store.json on writes.
Singleton pattern.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
_silent_log = __import__("structlog").get_logger(__name__)

if TYPE_CHECKING:
    from api.models import MissionLogEvent, MissionSummary

_WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_PERSIST_PATH = _WORKSPACE_DIR / "mission_store.json"


class MissionStateStore:
    _instance: "MissionStateStore | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._log_lock = threading.Lock()
        self._sum_lock = threading.Lock()
        # mission_id -> list of MissionLogEvent
        self._logs: dict[str, list] = {}
        # mission_id -> MissionSummary
        self._summaries: dict[str, object] = {}
        self._load()

    @classmethod
    def get(cls) -> "MissionStateStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── Log operations ────────────────────────────────────────

    _MAX_EVENTS_PER_MISSION = 500
    _MAX_MISSIONS           = 100

    def append_log(self, event: "MissionLogEvent") -> None:
        with self._log_lock:
            lst = self._logs.setdefault(event.mission_id, [])
            lst.append(event)
            # Cap : 500 events par mission — drop les plus anciens
            if len(lst) > self._MAX_EVENTS_PER_MISSION:
                self._logs[event.mission_id] = lst[-self._MAX_EVENTS_PER_MISSION:]
        self._persist()

    def get_log(self, mission_id: str) -> list:
        with self._log_lock:
            return list(self._logs.get(mission_id, []))

    def clear_old_logs(self, older_than_s: float = 3600) -> int:
        """Remove log events older than N seconds. Returns count removed."""
        cutoff = time.time() - older_than_s
        removed = 0
        with self._log_lock:
            for mid in list(self._logs.keys()):
                before = len(self._logs[mid])
                self._logs[mid] = [e for e in self._logs[mid] if e.timestamp >= cutoff]
                removed += before - len(self._logs[mid])
                if not self._logs[mid]:
                    del self._logs[mid]
        if removed:
            self._persist()
        return removed

    # ── Summary operations ────────────────────────────────────

    def save_summary(self, summary: "MissionSummary") -> None:
        with self._sum_lock:
            self._summaries[summary.mission_id] = summary
            # Cap : 100 missions — éviction FIFO des plus anciens
            if len(self._summaries) > self._MAX_MISSIONS:
                oldest_keys = sorted(
                    self._summaries,
                    key=lambda k: getattr(self._summaries[k], "created_at", 0),
                )
                for k in oldest_keys[:len(self._summaries) - self._MAX_MISSIONS]:
                    del self._summaries[k]
        self._persist()

    def get_summary(self, mission_id: str) -> "MissionSummary | None":
        with self._sum_lock:
            return self._summaries.get(mission_id)

    def list_summaries(self, limit: int = 20) -> list:
        with self._sum_lock:
            sums = list(self._summaries.values())
        sums.sort(key=lambda s: getattr(s, "created_at", 0), reverse=True)
        return sums[:limit]

    # ── Persistence ───────────────────────────────────────────

    def _persist(self) -> None:
        try:
            _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            with self._log_lock, self._sum_lock:
                data = {
                    "logs": {
                        mid: [e.to_dict() for e in events]
                        for mid, events in self._logs.items()
                    },
                    "summaries": {
                        mid: s.to_dict()
                        for mid, s in self._summaries.items()
                    },
                    "saved_at": time.time(),
                }
            _PERSIST_PATH.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
            )
        except Exception:
            pass  # fail-open: in-memory state is authoritative

    def _load(self) -> None:
        try:
            if not _PERSIST_PATH.exists():
                return
            from api.models import MissionLogEvent, MissionSummary, LogEventType
            data = json.loads(_PERSIST_PATH.read_text("utf-8"))
            for mid, events in data.get("logs", {}).items():
                loaded = []
                for e in events:
                    try:
                        loaded.append(MissionLogEvent(
                            mission_id=e["mission_id"],
                            event_type=LogEventType(e["event_type"]),
                            message=e["message"],
                            agent_id=e.get("agent_id", ""),
                            tool_name=e.get("tool_name", ""),
                            risk_level=e.get("risk_level", "safe"),
                            data=e.get("data", {}),
                            event_id=e.get("event_id", ""),
                            timestamp=e.get("timestamp", time.time()),
                        ))
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='mission_store.py')
                if loaded:
                    self._logs[mid] = loaded
            for mid, s in data.get("summaries", {}).items():
                try:
                    from api.models import MissionSummary
                    self._summaries[mid] = MissionSummary(
                        mission_id=s["mission_id"],
                        goal=s["goal"],
                        status=s["status"],
                        tools_used=s.get("tools_used", []),
                        agents_involved=s.get("agents_involved", []),
                        errors=s.get("errors", []),
                        lessons_learned=s.get("lessons_learned", []),
                        performance_score=s.get("performance_score", 0.0),
                        duration_ms=s.get("duration_ms", 0),
                        created_at=s.get("created_at", time.time()),
                        completed_at=s.get("completed_at", 0.0),
                        metadata=s.get("metadata", {}),
                    )
                except Exception:
                    _silent_log.debug("suppressed_exception", src='mission_store.py')
        except Exception:
            pass  # fresh start on any load error
