"""
core/cognitive_events/store.py — Append-only event journal.

Thread-safe, in-memory with optional file persistence.
Ring buffer to prevent unbounded growth.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import Callable

import structlog

from core.cognitive_events.types import (
    CognitiveEvent, EventType, EventSeverity, EventDomain,
)

log = structlog.get_logger("cognitive_events.store")

_DEFAULT_MAX_SIZE = 5000
_PERSIST_DIR = os.path.join("data", "cognitive_events")


class CognitiveJournal:
    """
    Append-only cognitive event journal.

    Features:
      - Ring buffer (configurable max size)
      - Optional file persistence (JSONL, append-only)
      - Subscriber callbacks for reactive consumers
      - Thread-safe
      - Domain-aware filtering
    """

    def __init__(
        self,
        max_size: int = _DEFAULT_MAX_SIZE,
        persist: bool = True,
        persist_dir: str = _PERSIST_DIR,
    ):
        self._lock = threading.Lock()
        self._events: deque[CognitiveEvent] = deque(maxlen=max_size)
        self._subscribers: list[Callable[[CognitiveEvent], None]] = []
        self._persist = persist
        self._persist_dir = persist_dir
        self._event_count = 0

        if persist:
            try:
                os.makedirs(persist_dir, exist_ok=True)
            except Exception:
                self._persist = False

    # ── Core API ──────────────────────────────────────────────

    def append(self, event: CognitiveEvent) -> CognitiveEvent:
        """
        Append an event to the journal. Returns the event.

        Thread-safe. Notifies subscribers. Optionally persists.
        """
        with self._lock:
            self._events.append(event)
            self._event_count += 1

        # Persist (fail-open)
        if self._persist:
            try:
                self._persist_event(event)
            except Exception as _exc:
                log.warning("swallowed_exception", action="store_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Notify subscribers (fail-open, non-blocking)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception as _exc:
                log.warning("swallowed_exception", action="store_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return event

    def subscribe(self, callback: Callable[[CognitiveEvent], None]) -> None:
        """Register a callback for new events."""
        self._subscribers.append(callback)

    # ── Query API ─────────────────────────────────────────────

    def get_recent(
        self,
        limit: int = 50,
        domain: EventDomain | None = None,
        event_type: EventType | None = None,
        mission_id: str | None = None,
        severity_min: EventSeverity | None = None,
        source: str | None = None,
    ) -> list[dict]:
        """
        Query recent events with optional filters.

        Returns newest-first list of event dicts.
        """
        _severity_order = {
            EventSeverity.DEBUG: 0, EventSeverity.INFO: 1,
            EventSeverity.WARNING: 2, EventSeverity.ERROR: 3,
            EventSeverity.CRITICAL: 4,
        }
        min_sev = _severity_order.get(severity_min, 0) if severity_min else 0

        with self._lock:
            candidates = list(self._events)

        results = []
        for evt in reversed(candidates):
            if domain and evt.domain != domain:
                continue
            if event_type and evt.event_type != event_type:
                continue
            if mission_id and evt.mission_id != mission_id:
                continue
            if source and evt.source != source:
                continue
            if _severity_order.get(evt.severity, 0) < min_sev:
                continue
            results.append(evt.to_dict())
            if len(results) >= limit:
                break

        return results

    def get_mission_timeline(self, mission_id: str) -> list[dict]:
        """Get all events for a specific mission, oldest first."""
        with self._lock:
            return [
                e.to_dict() for e in self._events
                if e.mission_id == mission_id
            ]

    def get_lab_events(self, limit: int = 50) -> list[dict]:
        """Get recent lab/sandbox events."""
        return self.get_recent(limit=limit, domain=EventDomain.LAB)

    def get_runtime_events(self, limit: int = 50) -> list[dict]:
        """Get recent runtime events."""
        return self.get_recent(limit=limit, domain=EventDomain.RUNTIME)

    # ── Stats ─────────────────────────────────────────────────

    def stats(self) -> dict:
        """Summary statistics."""
        with self._lock:
            events = list(self._events)

        by_type: dict[str, int] = {}
        by_domain: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for e in events:
            by_type[e.event_type.value] = by_type.get(e.event_type.value, 0) + 1
            by_domain[e.domain.value] = by_domain.get(e.domain.value, 0) + 1
            by_severity[e.severity.value] = by_severity.get(e.severity.value, 0) + 1

        return {
            "total_events": self._event_count,
            "in_buffer": len(events),
            "by_type": by_type,
            "by_domain": by_domain,
            "by_severity": by_severity,
            "subscribers": len(self._subscribers),
            "persist_enabled": self._persist,
        }

    # ── Replay ────────────────────────────────────────────────

    def replay(
        self,
        since_ts: float = 0.0,
        domain: EventDomain | None = None,
    ) -> list[dict]:
        """
        Replay events since a timestamp. Oldest first.

        Useful for audit, debugging, and catch-up consumers.
        """
        with self._lock:
            events = list(self._events)

        return [
            e.to_dict() for e in events
            if e.timestamp >= since_ts
            and (domain is None or e.domain == domain)
        ]

    # ── Explanation helpers ─────────────────────────────────────

    def explain_mission(self, mission_id: str) -> dict:
        """
        Generate a compact explanation of what happened in a mission.

        Returns a structured summary answering:
          - What capabilities were resolved?
          - What provider was selected and why?
          - Was approval needed?
          - Did it succeed or fail?
          - How long did it take?
        """
        timeline = self.get_mission_timeline(mission_id)
        if not timeline:
            return {"mission_id": mission_id, "found": False, "explanation": "No events found"}

        explanation = {
            "mission_id": mission_id,
            "found": True,
            "events": len(timeline),
            "capabilities_resolved": [],
            "provider_selected": None,
            "risk": None,
            "approval": None,
            "outcome": None,
            "duration_ms": None,
            "narrative": [],
        }

        for evt in timeline:
            etype = evt["event_type"]
            if etype == "mission.created":
                explanation["narrative"].append(
                    f"Mission created: {evt['payload'].get('goal', '')[:80]}"
                )
            elif etype == "routing.capability_resolved":
                caps = evt["payload"].get("capabilities", [])
                explanation["capabilities_resolved"] = caps
                explanation["narrative"].append(
                    f"Capabilities resolved: {', '.join(caps[:5])}"
                )
            elif etype == "routing.provider_selected":
                p = evt["payload"]
                explanation["provider_selected"] = {
                    "provider_id": p.get("provider_id"),
                    "capability_id": p.get("capability_id"),
                    "score": p.get("score"),
                    "alternatives": p.get("alternatives", 0),
                }
                explanation["narrative"].append(
                    f"Provider selected: {p.get('provider_id')} "
                    f"(score={p.get('score', 0):.3f}, {p.get('alternatives', 0)} alternatives)"
                )
            elif etype == "risk.evaluated":
                explanation["risk"] = evt["payload"]
                explanation["narrative"].append(
                    f"Risk: {evt['payload'].get('risk_level', '?')}, "
                    f"approval={'required' if evt['payload'].get('needs_approval') else 'not needed'}"
                )
            elif etype in ("approval.requested", "approval.granted", "approval.denied"):
                explanation["approval"] = {
                    "type": etype.split(".")[-1],
                    "payload": evt["payload"],
                }
                explanation["narrative"].append(f"Approval: {etype.split('.')[-1]}")
            elif etype == "mission.completed":
                explanation["outcome"] = "success"
                explanation["duration_ms"] = evt["payload"].get("duration_ms")
                explanation["narrative"].append(
                    f"Completed in {evt['payload'].get('duration_ms', 0):.0f}ms"
                )
            elif etype == "mission.failed":
                explanation["outcome"] = "failure"
                explanation["narrative"].append(
                    f"Failed: {evt['payload'].get('error', '')[:80]}"
                )

        return explanation

    def get_mission_approvals(self, mission_id: str) -> list[dict]:
        """Get all approval-related events for a mission."""
        approval_types = {
            "approval.requested", "approval.granted", "approval.denied",
            "risk.evaluated",
        }
        with self._lock:
            return [
                e.to_dict() for e in self._events
                if e.mission_id == mission_id
                and e.event_type.value in approval_types
            ]

    def get_patch_events(self, patch_id: str = "") -> list[dict]:
        """Get all events related to a patch (by patch_id in payload or tag)."""
        patch_types = {
            "lab.patch_proposed", "lab.patch_validated",
            "lab.patch_rejected", "lab.patch_promoted",
        }
        with self._lock:
            results = []
            for e in self._events:
                if e.event_type.value not in patch_types:
                    continue
                if patch_id and e.payload.get("patch_id") != patch_id:
                    continue
                results.append(e.to_dict())
            return results

    def get_degraded_events(self, limit: int = 50) -> list[dict]:
        """Get recent degradation and alert events."""
        degraded_types = {
            "runtime.degraded", "runtime.alert",
            "execution.tool_failed",
        }
        with self._lock:
            results = []
            for e in reversed(list(self._events)):
                if e.event_type.value in degraded_types:
                    results.append(e.to_dict())
                    if len(results) >= limit:
                        break
            return results

    # ── Persistence ───────────────────────────────────────────

    def _persist_event(self, event: CognitiveEvent) -> None:
        """Append event to daily JSONL file."""
        import datetime
        day = datetime.datetime.fromtimestamp(event.timestamp, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(self._persist_dir, f"journal-{day}.jsonl")
        line = json.dumps(event.to_dict(), default=str) + "\n"
        with open(path, "a") as f:
            f.write(line)

    def load_from_disk(self, days: int = 1) -> int:
        """Load recent events from persisted JSONL files."""
        if not self._persist or not os.path.isdir(self._persist_dir):
            return 0

        import datetime
        loaded = 0
        for i in range(days):
            day = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            path = os.path.join(self._persist_dir, f"journal-{day}.jsonl")
            if not os.path.isfile(path):
                continue
            try:
                with open(path) as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            evt = CognitiveEvent(
                                event_type=EventType(data["event_type"]),
                                summary=data.get("summary", ""),
                                source=data.get("source", ""),
                                mission_id=data.get("mission_id", ""),
                                session_id=data.get("session_id", ""),
                                severity=EventSeverity(data.get("severity", "info")),
                                payload=data.get("payload", {}),
                                tags=data.get("tags", []),
                                event_id=data.get("event_id", ""),
                                timestamp=data.get("timestamp", 0),
                            )
                            with self._lock:
                                self._events.append(evt)
                            loaded += 1
                        except Exception:
                            log.debug("swallowed_exception", exc_info=True)
                            continue
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
                continue

        return loaded


# ── Singleton ─────────────────────────────────────────────────

_journal: CognitiveJournal | None = None
_journal_lock = threading.Lock()


def get_journal(persist: bool = True) -> CognitiveJournal:
    """Get or create the singleton cognitive journal."""
    global _journal
    if _journal is None:
        with _journal_lock:
            if _journal is None:
                _journal = CognitiveJournal(persist=persist)
    return _journal
