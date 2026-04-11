"""
core/trace.py — Lightweight decision tracing for observability.

Records structured decision events during mission execution.
Stored per-mission in workspace/missions/<id>/trace.jsonl.

Usage:
    from core.trace import MissionTrace
    trace = MissionTrace(mission_id)
    trace.record("planner", "plan_generated", steps=5, difficulty="medium")
    trace.record("executor", "tool_executed", tool="shell_command", ok=True, duration_ms=120)
    trace.record("risk", "approval_required", level="HIGH", action="delete")
    events = trace.get_events()
"""
from __future__ import annotations
import json
import time
from pathlib import Path


class MissionTrace:
    """Append-only trace log for a single mission."""

    def __init__(self, mission_id: str, workspace_dir: str = "workspace"):
        self._mission_id = mission_id
        self._dir = Path(workspace_dir) / "missions" / mission_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "trace.jsonl"

    def record(self, component: str, event: str, **data) -> None:
        """Record a structured trace event."""
        entry = {
            "ts": time.time(),
            "mission": self._mission_id,
            "component": component,
            "event": event,
            **data,
        }
        try:
            with open(self._file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass  # tracing must never crash the system

    def get_events(self, component: str | None = None, limit: int = 100) -> list[dict]:
        """Read trace events, optionally filtered by component."""
        if not self._file.exists():
            return []
        events = []
        try:
            with open(self._file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if component and entry.get("component") != component:
                            continue
                        events.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            _silent_log.debug("suppressed_exception", src='trace.py')
        return events[-limit:]

    def summary(self) -> dict:
        """Return a summary of the trace (counts by component and event)."""
        events = self.get_events(limit=10000)
        by_component: dict[str, int] = {}
        by_event: dict[str, int] = {}
        errors = 0
        for e in events:
            comp = e.get("component", "unknown")
            evt = e.get("event", "unknown")
            by_component[comp] = by_component.get(comp, 0) + 1
            by_event[evt] = by_event.get(evt, 0) + 1
            if e.get("ok") is False or "error" in e.get("event", ""):
                errors += 1
        return {
            "mission_id": self._mission_id,
            "total_events": len(events),
            "errors": errors,
            "by_component": by_component,
            "by_event": by_event,
        }
