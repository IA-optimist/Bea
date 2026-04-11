"""
core/capability_routing/feedback.py — Routing outcome learning.

Records routing decisions and outcomes, feeds back into:
  - Cognitive graph (capability reliability updates)
  - Learning traces (structured routing lessons)
  - In-memory history (for /history endpoint and future scoring)

Thread-safe. Fail-open. All feedback is fire-and-forget.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("capability_routing.feedback")

# Maximum history entries kept in memory
_MAX_HISTORY = 200


@dataclass
class RoutingOutcome:
    """Record of a completed routing decision and its result."""
    mission_id: str
    capability_id: str
    provider_id: str
    provider_type: str
    score: float
    alternatives_count: int
    fallback_used: bool
    requires_approval: bool
    # Outcome (filled after execution)
    success: bool | None = None         # None = not yet resolved
    error: str = ""
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "score": round(self.score, 3),
            "alternatives_count": self.alternatives_count,
            "fallback_used": self.fallback_used,
            "requires_approval": self.requires_approval,
            "success": self.success,
            "error": self.error[:200] if self.error else "",
            "duration_ms": round(self.duration_ms, 1),
            "timestamp": self.timestamp,
        }


class RoutingHistory:
    """
    In-memory ring buffer of routing outcomes.

    Used for:
      - /history endpoint
      - Future scoring adjustments (recent success/failure rates)
      - Learning trace generation
    """

    def __init__(self, max_size: int = _MAX_HISTORY):
        self._lock = threading.Lock()
        self._history: deque[RoutingOutcome] = deque(maxlen=max_size)
        self._by_provider: dict[str, list[float]] = {}  # provider_id → [success_rate samples]

    def record_decision(
        self,
        mission_id: str,
        capability_id: str,
        provider_id: str | None,
        provider_type: str = "",
        score: float = 0.0,
        alternatives_count: int = 0,
        fallback_used: bool = False,
        requires_approval: bool = False,
    ) -> RoutingOutcome:
        """Record a routing decision (before execution)."""
        outcome = RoutingOutcome(
            mission_id=mission_id,
            capability_id=capability_id,
            provider_id=provider_id or "none",
            provider_type=provider_type,
            score=score,
            alternatives_count=alternatives_count,
            fallback_used=fallback_used,
            requires_approval=requires_approval,
        )
        with self._lock:
            self._history.append(outcome)

        log.info("routing.decision_recorded",
                 mission_id=mission_id,
                 capability=capability_id,
                 provider=provider_id or "none",
                 score=round(score, 3))
        return outcome

    def record_outcome(
        self,
        mission_id: str,
        success: bool,
        error: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        """Update the most recent decision for a mission with execution outcome."""
        with self._lock:
            for outcome in reversed(self._history):
                if outcome.mission_id == mission_id and outcome.success is None:
                    outcome.success = success
                    outcome.error = error
                    outcome.duration_ms = duration_ms
                    # Update per-provider success tracking
                    pid = outcome.provider_id
                    self._by_provider.setdefault(pid, [])
                    self._by_provider[pid].append(1.0 if success else 0.0)
                    # Keep only last 50 samples per provider
                    if len(self._by_provider[pid]) > 50:
                        self._by_provider[pid] = self._by_provider[pid][-50:]
                    break

        # Feed back to cognitive graph (fail-open)
        self._feed_cognitive(mission_id, success, error)

        # Feed back to learning traces (fail-open)
        self._feed_learning(mission_id, success, error)

    def get_recent(self, limit: int = 50) -> list[dict]:
        """Get recent routing history."""
        with self._lock:
            items = list(self._history)[-limit:]
        return [o.to_dict() for o in reversed(items)]

    def get_provider_stats(self) -> dict[str, dict]:
        """Success rate stats per provider."""
        with self._lock:
            stats = {}
            for pid, samples in self._by_provider.items():
                if samples:
                    stats[pid] = {
                        "total": len(samples),
                        "success_rate": round(sum(samples) / len(samples), 3),
                        "recent_successes": sum(1 for s in samples[-10:] if s == 1.0),
                        "recent_total": min(10, len(samples)),
                    }
            return stats

    def get_provider_success_rate(self, provider_id: str) -> float | None:
        """Get the recent success rate for a provider. Returns None if no data."""
        with self._lock:
            samples = self._by_provider.get(provider_id, [])
            if not samples:
                return None
            return sum(samples) / len(samples)

    def summary(self) -> dict:
        """Summary statistics."""
        with self._lock:
            total = len(self._history)
            resolved = sum(1 for o in self._history if o.success is not None)
            successes = sum(1 for o in self._history if o.success is True)
            fallbacks = sum(1 for o in self._history if o.fallback_used)
        return {
            "total_decisions": total,
            "resolved_outcomes": resolved,
            "success_rate": round(successes / resolved, 3) if resolved > 0 else 0.0,
            "fallback_rate": round(fallbacks / total, 3) if total > 0 else 0.0,
            "providers_tracked": len(self._by_provider),
        }

    # ── Feedback sinks (all fail-open) ────────────────────────

    def _feed_cognitive(self, mission_id: str, success: bool, error: str) -> None:
        """Update cognitive graph with routing outcome."""
        try:
            from core.cognitive_bridge import get_bridge
            bridge = get_bridge()

            # Find the outcome entry
            outcome = None
            with self._lock:
                for o in reversed(self._history):
                    if o.mission_id == mission_id:
                        outcome = o
                        break

            if outcome and bridge.capability_graph:
                # Update capability reliability based on outcome
                cap_graph = bridge.capability_graph
                cap_id = outcome.capability_id
                cap = cap_graph.get_capability(cap_id)
                if cap:
                    # Nudge reliability toward recent outcome
                    if success:
                        cap.reliability = min(1.0, cap.reliability + 0.02)
                    else:
                        cap.reliability = max(0.0, cap.reliability - 0.05)

            # Also record in agent reputation if it was an agent provider
            if outcome and outcome.provider_type == "agent":
                agent_id = outcome.provider_id.replace("agent:", "")
                try:
                    if bridge.agent_reputation:
                        if success:
                            bridge.agent_reputation.record_success(agent_id, outcome.capability_id)
                        else:
                            bridge.agent_reputation.record_failure(agent_id, outcome.capability_id, error[:100])
                except Exception:
                    _silent_log.debug("suppressed_exception", src='feedback.py')

        except Exception as e:
            log.debug("routing_feedback.cognitive_failed", err=str(e)[:60])

    def _feed_learning(self, mission_id: str, success: bool, error: str) -> None:
        """Create a learning trace for the routing decision."""
        try:
            from core.cognitive_bridge import get_bridge
            bridge = get_bridge()
            if not bridge.learning_traces:
                return

            outcome = None
            with self._lock:
                for o in reversed(self._history):
                    if o.mission_id == mission_id:
                        outcome = o
                        break

            if outcome:
                bridge.learning_traces.record({
                    "event_description": f"Routing: {outcome.capability_id} → {outcome.provider_id}",
                    "root_cause": error[:100] if error else "success",
                    "outcome": "success" if success else "failure",
                    "context": {
                        "mission_id": mission_id,
                        "capability_id": outcome.capability_id,
                        "provider_id": outcome.provider_id,
                        "score": outcome.score,
                        "fallback_used": outcome.fallback_used,
                        "duration_ms": outcome.duration_ms,
                    },
                    "source": "capability_routing",
                })

        except Exception as e:
            log.debug("routing_feedback.learning_failed", err=str(e)[:60])


# ── Singleton ─────────────────────────────────────────────────

_history: RoutingHistory | None = None
_history_lock = threading.Lock()


def get_routing_history() -> RoutingHistory:
    """Get or create the singleton routing history."""
    global _history
    if _history is None:
        with _history_lock:
            if _history is None:
                _history = RoutingHistory()
    return _history
