"""
BEA Workflow — Events & Versioning (Phases 3-4)
=================================================
- EventTrigger / EventTriggerManager  — event-driven workflow triggers
- WorkflowVersion / WorkflowVersionManager — versioning + performance comparison
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

import structlog

from .boundaries import (
    MAX_EVENT_HANDLERS,
    MAX_EVENT_LOG,
    MAX_VERSION_HISTORY,
    MAX_WORKFLOW_DEPTH,
)

logger = structlog.get_logger("bea.workflow_runtime")


# ═══════════════════════════════════════════════════════════════
# PHASE 3 — EVENT-DRIVEN TRIGGERS
# ═══════════════════════════════════════════════════════════════

@dataclass
class EventTrigger:
    """An event-driven workflow trigger."""
    trigger_id: str = ""
    name: str = ""
    event_type: str = ""
    condition: str = ""
    workflow_name: str = ""
    workflow_steps: list = field(default_factory=list)
    enabled: bool = True
    debounce_s: int = 300
    last_triggered: float = 0.0
    trigger_count: int = 0
    max_triggers_per_day: int = 10
    daily_trigger_count: int = 0
    daily_reset_time: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def can_trigger(self, now: float = 0.0) -> bool:
        """Check if this trigger can fire (debounce + daily limit)."""
        if not self.enabled:
            return False
        now = now or time.time()

        if (now - self.last_triggered) < self.debounce_s:
            return False

        if (now - self.daily_reset_time) > 86400:
            self.daily_trigger_count = 0
            self.daily_reset_time = now

        if self.daily_trigger_count >= self.max_triggers_per_day:
            return False

        return True

    def record_trigger(self) -> None:
        now = time.time()
        self.last_triggered = now
        self.trigger_count += 1
        self.daily_trigger_count += 1


VALID_EVENT_TYPES = {
    "opportunity_detected",
    "objective_stalled",
    "tool_failure_repeated",
    "workflow_success_pattern",
    "external_signal",
    "mission_completed",
    "mission_failed",
    "schedule_tick",
}


class EventTriggerManager:
    """Manages event-driven workflow triggers with bounded execution."""

    def __init__(self):
        self._triggers: dict[str, EventTrigger] = {}
        self._event_log: list[dict] = []

    def register_trigger(self, trigger: EventTrigger) -> EventTrigger:
        if len(self._triggers) >= MAX_EVENT_HANDLERS:
            raise ValueError(f"Max event handlers reached ({MAX_EVENT_HANDLERS})")
        if trigger.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event type: {trigger.event_type}")
        if not trigger.trigger_id:
            trigger.trigger_id = str(uuid.uuid4())[:8]
        if not trigger.created_at:
            trigger.created_at = time.time()
        self._triggers[trigger.trigger_id] = trigger
        return trigger

    def unregister_trigger(self, trigger_id: str) -> bool:
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            return True
        return False

    def fire_event(self, event_type: str, context: dict = None) -> list[dict]:
        """
        Fire an event; return matching triggers (does NOT execute workflows).
        """
        if event_type not in VALID_EVENT_TYPES:
            return []

        now = time.time()
        triggered = []

        for trigger in self._triggers.values():
            if trigger.event_type != event_type:
                continue
            if not trigger.can_trigger(now):
                continue
            trigger.record_trigger()
            triggered.append({
                "trigger_id": trigger.trigger_id,
                "name": trigger.name,
                "workflow_name": trigger.workflow_name,
                "workflow_steps": trigger.workflow_steps,
                "event_type": event_type,
                "context": context or {},
            })

        self._event_log.append({
            "event_type": event_type,
            "triggers_fired": len(triggered),
            "timestamp": now,
            "context_keys": list((context or {}).keys()),
        })
        if len(self._event_log) > MAX_EVENT_LOG:
            self._event_log = self._event_log[-MAX_EVENT_LOG:]

        return triggered

    def list_triggers(self) -> list[dict]:
        return [t.to_dict() for t in self._triggers.values()]

    def get_event_log(self, limit: int = 50) -> list[dict]:
        return self._event_log[-limit:]


# ═══════════════════════════════════════════════════════════════
# PHASE 4 — WORKFLOW VERSIONING
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkflowVersion:
    """A versioned workflow definition."""
    workflow_name: str = ""
    version: int = 1
    steps_template: list = field(default_factory=list)
    created_at: float = 0.0
    executions: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_s: float = 0.0
    total_duration_s: float = 0.0
    is_stable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def success_rate(self) -> float:
        if self.executions == 0:
            return 0.0
        return round(self.successes / self.executions, 3)

    @property
    def efficiency(self) -> float:
        """Lower duration with higher success = more efficient."""
        if self.executions == 0 or self.avg_duration_s <= 0:
            return 0.0
        return round(self.success_rate / max(self.avg_duration_s, 0.1), 4)


class WorkflowVersionManager:
    """Tracks workflow versions with performance comparison."""

    def __init__(self):
        self._versions: dict[str, list[WorkflowVersion]] = {}

    def register_version(self, name: str, steps_template: list,
                         version: int = 0) -> WorkflowVersion:
        if name not in self._versions:
            self._versions[name] = []
        history = self._versions[name]

        if version <= 0:
            version = max((v.version for v in history), default=0) + 1

        if len(history) >= MAX_VERSION_HISTORY:
            history.pop(0)

        wv = WorkflowVersion(
            workflow_name=name,
            version=version,
            steps_template=steps_template[:MAX_WORKFLOW_DEPTH],
            created_at=time.time(),
        )
        history.append(wv)
        return wv

    def record_execution(self, name: str, version: int,
                         success: bool, duration_s: float) -> None:
        history = self._versions.get(name, [])
        for wv in history:
            if wv.version == version:
                wv.executions += 1
                if success:
                    wv.successes += 1
                else:
                    wv.failures += 1
                wv.total_duration_s += duration_s
                wv.avg_duration_s = round(wv.total_duration_s / wv.executions, 2)
                if wv.executions >= 5 and wv.success_rate >= 0.8:
                    wv.is_stable = True
                return

    def get_best_version(self, name: str) -> Optional[WorkflowVersion]:
        history = self._versions.get(name, [])
        if not history:
            return None
        scored = []
        for wv in history:
            score = wv.success_rate * 0.5 + wv.efficiency * 0.3
            if wv.is_stable:
                score += 0.2
            scored.append((score, wv))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None

    def get_stable_version(self, name: str) -> Optional[WorkflowVersion]:
        history = self._versions.get(name, [])
        stable = [v for v in history if v.is_stable]
        if not stable:
            return None
        return max(stable, key=lambda v: v.version)

    def compare_versions(self, name: str) -> list[dict]:
        history = self._versions.get(name, [])
        return [
            {
                "version": wv.version,
                "executions": wv.executions,
                "success_rate": wv.success_rate,
                "avg_duration_s": wv.avg_duration_s,
                "efficiency": wv.efficiency,
                "is_stable": wv.is_stable,
            }
            for wv in sorted(history, key=lambda v: v.version, reverse=True)
        ]

    def list_workflows(self) -> list[dict]:
        result = []
        for name, history in self._versions.items():
            latest = max(history, key=lambda v: v.version) if history else None
            best = self.get_best_version(name)
            result.append({
                "workflow_name": name,
                "total_versions": len(history),
                "latest_version": latest.version if latest else 0,
                "best_version": best.version if best else 0,
                "has_stable": any(v.is_stable for v in history),
            })
        return result
