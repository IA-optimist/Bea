"""
core/observability/event_envelope.py — Unified event envelope for mission tracing.

Every action, tool call, agent decision, and memory write shares a common trace_id.
Single trace_id reconstructs full mission lifecycle.
"""
from __future__ import annotations

import time
import uuid
import threading
import logging
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

log = logging.getLogger("jarvis.observability")


@dataclass
class EventEnvelope:
    """Unified event for all mission lifecycle observability."""
    trace_id: str
    mission_id: str
    timestamp: float = field(default_factory=time.time)
    component: Literal[
        "orchestrator", "agent", "executor", "tool", "memory"
    ] = "executor"
    event_type: Literal[
        "decision", "tool_call", "tool_result",
        "memory_write", "error", "status_update"
    ] = "status_update"
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Trace ID generation + propagation ─────────────────────────────────────────

def generate_trace_id() -> str:
    """Generate a unique trace ID for a mission lifecycle."""
    return f"tr-{uuid.uuid4().hex[:12]}"


class _TraceContext(threading.local):
    """Thread-local trace context for propagation."""
    trace_id: Optional[str] = None
    mission_id: Optional[str] = None


_ctx = _TraceContext()


def set_trace(trace_id: str, mission_id: str = "") -> None:
    """Set trace context for current thread."""
    _ctx.trace_id = trace_id
    _ctx.mission_id = mission_id


def get_trace_id() -> Optional[str]:
    """Get current trace ID (or None if not set)."""
    return getattr(_ctx, "trace_id", None)


def get_mission_id() -> Optional[str]:
    """Get current mission ID from trace context."""
    return getattr(_ctx, "mission_id", None)


def clear_trace() -> None:
    """Clear trace context."""
    _ctx.trace_id = None
    _ctx.mission_id = None


# ── Event collector ───────────────────────────────────────────────────────────

class EventCollector:
    """Collects events for a mission trace. Thread-safe."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: dict[str, list[dict]] = {}  # trace_id → events
        self._lock = threading.Lock()
        self._max_events = max_events

    def emit(self, envelope: EventEnvelope) -> None:
        """Record an event."""
        with self._lock:
            tid = envelope.trace_id
            if tid not in self._events:
                self._events[tid] = []
            events = self._events[tid]
            if len(events) < self._max_events:
                events.append(envelope.to_dict())
        log.debug("event_emitted",
                  extra={"trace_id": envelope.trace_id,
                         "component": envelope.component,
                         "event_type": envelope.event_type})

    def emit_quick(self, component: str, event_type: str, payload: dict = None) -> None:
        """Emit using current trace context. No-op if no trace set."""
        tid = get_trace_id()
        mid = get_mission_id()
        if not tid:
            return
        self.emit(EventEnvelope(
            trace_id=tid,
            mission_id=mid or "",
            component=component,
            event_type=event_type,
            payload=payload or {},
        ))

    def get_trace(self, trace_id: str) -> list[dict]:
        """Get all events for a trace."""
        with self._lock:
            return list(self._events.get(trace_id, []))

    def get_mission_trace(self, mission_id: str) -> list[dict]:
        """Get all events across traces for a mission."""
        with self._lock:
            result = []
            for events in self._events.values():
                for e in events:
                    if e.get("mission_id") == mission_id:
                        result.append(e)
            result.sort(key=lambda e: e.get("timestamp", 0))
            return result

    def cleanup(self, max_age_seconds: float = 3600) -> int:
        """Remove traces older than max_age."""
        cutoff = time.time() - max_age_seconds
        removed = 0
        with self._lock:
            to_remove = []
            for tid, events in self._events.items():
                if events and events[-1].get("timestamp", 0) < cutoff:
                    to_remove.append(tid)
            for tid in to_remove:
                del self._events[tid]
                removed += 1
        return removed

    def stats(self) -> dict:
        with self._lock:
            total_events = sum(len(e) for e in self._events.values())
            return {
                "active_traces": len(self._events),
                "total_events": total_events,
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_collector: Optional[EventCollector] = None


def get_event_collector() -> EventCollector:
    global _collector
    if _collector is None:
        _collector = EventCollector()
    return _collector
