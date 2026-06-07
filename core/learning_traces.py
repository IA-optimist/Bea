"""
BEA MAX — Learning Traces Exploitation
=============================================
Captures structured learning events from runtime execution and makes
them queryable for future decision-making.

A learning trace is: what happened → why → what was learned → how to use it.

Integrates with:
  - self-improvement lesson memory
  - agent reputation
  - memory graph
  - decision memory
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()

_PERSIST_PATH = os.environ.get("LEARNING_TRACES_PATH", "data/learning_traces.json")
_MAX_TRACES = 5_000


class TraceType(str, Enum):
    MISSION_SUCCESS = "mission_success"
    MISSION_FAILURE = "mission_failure"
    TOOL_DEGRADATION = "tool_degradation"
    ROUTING_SUBOPTIMAL = "routing_suboptimal"
    PATCH_PROMOTED = "patch_promoted"
    PATCH_REJECTED = "patch_rejected"
    APPROVAL_PATTERN = "approval_pattern"
    COST_ANOMALY = "cost_anomaly"
    LATENCY_ANOMALY = "latency_anomaly"
    USER_CORRECTION = "user_correction"


@dataclass
class LearningTrace:
    """Structured learning event."""
    id: str = ""
    type: TraceType = TraceType.MISSION_SUCCESS
    timestamp: float = field(default_factory=time.time)
    # What happened
    event_description: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    # Why
    root_cause: str = ""
    contributing_factors: List[str] = field(default_factory=list)
    # What was learned
    lesson: str = ""
    actionable_insight: str = ""
    # How to use it
    applicable_to: List[str] = field(default_factory=list)  # mission types, agents, tools
    confidence: float = 0.5
    # Tracking
    times_applied: int = 0
    last_applied: float = 0.0
    effectiveness: float = 0.0  # -1.0 to 1.0 (negative = made things worse)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type.value,
            "timestamp": self.timestamp,
            "event_description": self.event_description,
            "root_cause": self.root_cause,
            "lesson": self.lesson,
            "actionable_insight": self.actionable_insight,
            "applicable_to": self.applicable_to,
            "confidence": round(self.confidence, 2),
            "times_applied": self.times_applied,
            "effectiveness": round(self.effectiveness, 2),
        }


class LearningTraceStore:
    """
    Store and query learning traces.
    Singleton via get_learning_traces().
    """

    def __init__(self, persist_path: str = _PERSIST_PATH):
        self._lock = threading.RLock()
        self._traces: Dict[str, LearningTrace] = {}
        self._path = Path(persist_path)
        self._load()

    def record(self, trace: LearningTrace) -> LearningTrace:
        """Record a new learning trace."""
        with self._lock:
            if not trace.id:
                trace.id = f"lt-{int(time.time())}-{len(self._traces)}"
            self._traces[trace.id] = trace
            if len(self._traces) > _MAX_TRACES:
                self._evict_oldest(500)
            self._save()
        return trace

    def query(
        self,
        type: Optional[TraceType] = None,
        applicable_to: Optional[str] = None,
        min_confidence: float = 0.0,
        min_effectiveness: float = -1.0,
        limit: int = 20,
    ) -> List[LearningTrace]:
        """Query learning traces with filters."""
        results = []
        for t in self._traces.values():
            if type and t.type != type:
                continue
            if applicable_to and applicable_to not in t.applicable_to:
                continue
            if t.confidence < min_confidence:
                continue
            if t.effectiveness < min_effectiveness:
                continue
            results.append(t)
        return sorted(results, key=lambda t: t.confidence * max(t.effectiveness, 0.1), reverse=True)[:limit]

    def get_insights_for(self, context: str) -> List[str]:
        """Get actionable insights applicable to a context."""
        relevant = self.query(applicable_to=context, min_confidence=0.5, min_effectiveness=0.0)
        return [t.actionable_insight for t in relevant if t.actionable_insight]

    def record_application(self, trace_id: str, was_helpful: bool) -> None:
        """Record that a trace's insight was applied and whether it helped."""
        with self._lock:
            t = self._traces.get(trace_id)
            if t:
                t.times_applied += 1
                t.last_applied = time.time()
                # Exponential moving average for effectiveness
                new_score = 1.0 if was_helpful else -0.5
                if t.times_applied == 1:
                    t.effectiveness = new_score
                else:
                    t.effectiveness = t.effectiveness * 0.7 + new_score * 0.3
                self._save()

    def get_all(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in sorted(
            self._traces.values(), key=lambda t: t.timestamp, reverse=True
        )]

    def stats(self) -> Dict[str, Any]:
        by_type = {}
        for t in self._traces.values():
            by_type[t.type.value] = by_type.get(t.type.value, 0) + 1
        avg_eff = 0.0
        applied = [t for t in self._traces.values() if t.times_applied > 0]
        if applied:
            avg_eff = sum(t.effectiveness for t in applied) / len(applied)
        return {
            "total_traces": len(self._traces),
            "by_type": by_type,
            "total_applied": sum(t.times_applied for t in self._traces.values()),
            "avg_effectiveness": round(avg_eff, 2),
        }

    # ── Persistence ──

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {tid: {
                "type": t.type.value, "timestamp": t.timestamp,
                "event_description": t.event_description, "context": t.context,
                "root_cause": t.root_cause, "contributing_factors": t.contributing_factors,
                "lesson": t.lesson, "actionable_insight": t.actionable_insight,
                "applicable_to": t.applicable_to, "confidence": t.confidence,
                "times_applied": t.times_applied, "last_applied": t.last_applied,
                "effectiveness": t.effectiveness,
            } for tid, t in self._traces.items()}
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.warning("learning_traces_save_failed", err=str(e))

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text())
            for tid, vals in data.items():
                self._traces[tid] = LearningTrace(
                    id=tid, type=TraceType(vals.get("type", "mission_success")),
                    timestamp=vals.get("timestamp", 0),
                    event_description=vals.get("event_description", ""),
                    context=vals.get("context", {}),
                    root_cause=vals.get("root_cause", ""),
                    contributing_factors=vals.get("contributing_factors", []),
                    lesson=vals.get("lesson", ""),
                    actionable_insight=vals.get("actionable_insight", ""),
                    applicable_to=vals.get("applicable_to", []),
                    confidence=vals.get("confidence", 0.5),
                    times_applied=vals.get("times_applied", 0),
                    last_applied=vals.get("last_applied", 0),
                    effectiveness=vals.get("effectiveness", 0),
                )
        except Exception as e:
            log.warning("learning_traces_load_failed", err=str(e))

    def _evict_oldest(self, count: int) -> None:
        sorted_traces = sorted(self._traces.values(), key=lambda t: t.timestamp)
        for t in sorted_traces[:count]:
            del self._traces[t.id]


_singleton: Optional[LearningTraceStore] = None
_lock = threading.Lock()


def get_learning_traces() -> LearningTraceStore:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = LearningTraceStore()
    return _singleton
