"""
JARVIS MAX — Self-Improvement Observability
===============================================
Structured events + metrics for the autonomous code patching pipeline.

Events:
  SANDBOX_CREATED       — isolated workspace ready
  PATCH_APPLIED         — candidate written to sandbox
  PATCH_REJECTED        — candidate failed policy/syntax/size gate
  VALIDATION_STARTED    — test/lint/typecheck phase begins
  VALIDATION_FINISHED   — validation complete with results
  VALIDATION_TIMEOUT    — validation exceeded time limit
  PROMOTION_DECISION    — PROMOTE/REJECT/REVIEW decided
  ROLLBACK_READY        — rollback instructions generated
  LESSON_STORED         — outcome recorded to improvement memory

All events are fail-open: never crash the caller.
Reuses existing metrics_store and observability_helpers when available.
"""
from __future__ import annotations

import time
from typing import Any

try:
    import structlog
    log = structlog.get_logger("self_improvement")
except ImportError:
    import logging
    log = logging.getLogger("self_improvement")


# ═══════════════════════════════════════════════════════════════
# EVENT TYPES
# ═══════════════════════════════════════════════════════════════

class SIEvent:
    """Self-improvement event types."""
    SANDBOX_CREATED = "si.sandbox_created"
    PATCH_APPLIED = "si.patch_applied"
    PATCH_REJECTED = "si.patch_rejected"
    VALIDATION_STARTED = "si.validation_started"
    VALIDATION_FINISHED = "si.validation_finished"
    VALIDATION_TIMEOUT = "si.validation_timeout"
    PROMOTION_DECISION = "si.promotion_decision"
    ROLLBACK_READY = "si.rollback_ready"
    LESSON_STORED = "si.lesson_stored"


# ═══════════════════════════════════════════════════════════════
# EVENT EMITTER
# ═══════════════════════════════════════════════════════════════

class SIObservability:
    """
    Emits structured events and updates metrics for self-improvement.
    
    Fail-open: all methods are wrapped in try/except.
    Reuses MetricsStore if available.
    """

    def __init__(self):
        self._metrics = None
        self._events: list[dict] = []
        self._try_load_metrics()

    def _try_load_metrics(self) -> None:
        """Try to connect to the global MetricsStore."""
        try:
            from core.metrics_store import get_metrics
            self._metrics = get_metrics()
        except Exception:
            _silent_log.debug("suppressed_exception", src='observability.py')

    # ── Event emitters ──

    def sandbox_created(self, patch_id: str, method: str, sandbox_path: str = "") -> None:
        self._emit(SIEvent.SANDBOX_CREATED, {
            "patch_id": patch_id, "method": method,
            "sandbox_path": sandbox_path[:100],
        })
        self._inc("si_sandbox_created_total", {"method": method})

    def patch_applied(self, patch_id: str, files: list[str], lines_changed: int) -> None:
        self._emit(SIEvent.PATCH_APPLIED, {
            "patch_id": patch_id, "files": files[:5],
            "lines_changed": lines_changed,
        })
        self._inc("si_patches_applied_total")
        self._observe("si_patch_lines_changed", lines_changed)

    def patch_rejected(self, patch_id: str, reason: str, category: str = "") -> None:
        self._emit(SIEvent.PATCH_REJECTED, {
            "patch_id": patch_id, "reason": reason[:200],
            "category": category,
        })
        self._inc("si_patches_rejected_total", {"category": category or "unknown"})

    def validation_started(self, patch_id: str, level: str = "full") -> None:
        self._emit(SIEvent.VALIDATION_STARTED, {
            "patch_id": patch_id, "level": level,
        })
        self._inc("si_validations_started_total", {"level": level})

    def validation_finished(self, patch_id: str, passed: bool,
                             tests_total: int = 0, tests_passed: int = 0,
                             tests_failed: int = 0, duration_ms: float = 0,
                             level: str = "full") -> None:
        self._emit(SIEvent.VALIDATION_FINISHED, {
            "patch_id": patch_id, "passed": passed,
            "tests_total": tests_total, "tests_passed": tests_passed,
            "tests_failed": tests_failed, "duration_ms": round(duration_ms, 1),
            "level": level,
        })
        status = "pass" if passed else "fail"
        self._inc("si_validations_finished_total", {"status": status, "level": level})
        if duration_ms > 0:
            self._observe("si_validation_duration_ms", duration_ms)

    def validation_timeout(self, patch_id: str, timeout_s: int) -> None:
        self._emit(SIEvent.VALIDATION_TIMEOUT, {
            "patch_id": patch_id, "timeout_s": timeout_s,
        })
        self._inc("si_validation_timeouts_total")

    def promotion_decision(self, patch_id: str, decision: str, reason: str,
                            score: float = 0.0, risk: str = "low") -> None:
        self._emit(SIEvent.PROMOTION_DECISION, {
            "patch_id": patch_id, "decision": decision,
            "reason": reason[:200], "score": round(score, 3),
            "risk": risk,
        })
        self._inc("si_promotion_decisions_total", {"decision": decision, "risk": risk})

    def rollback_ready(self, patch_id: str, instructions: str) -> None:
        self._emit(SIEvent.ROLLBACK_READY, {
            "patch_id": patch_id,
            "has_instructions": bool(instructions),
        })

    def lesson_stored(self, patch_id: str, result: str, strategy: str = "") -> None:
        self._emit(SIEvent.LESSON_STORED, {
            "patch_id": patch_id, "result": result,
            "strategy": strategy,
        })
        self._inc("si_lessons_stored_total", {"result": result})
        # Feed into cognitive learning traces (fail-open)
        try:
            from core.cognitive_bridge import get_bridge
            bridge = get_bridge()
            bridge.post_mission(
                mission_id=f"si-{patch_id}",
                goal=f"Self-improvement patch: {strategy or patch_id}",
                success=(result in ("PROMOTE", "REVIEW", "pass")),
                agent_id="self_improvement",
                lessons_learned=[f"Patch {patch_id}: {result}"],
            )
        except Exception:
            pass  # Fail-open: cognitive bridge is optional

    # ── Query ──

    def get_events(self, limit: int = 50) -> list[dict]:
        """Get recent events."""
        return list(reversed(self._events))[:limit]

    def get_stats(self) -> dict:
        """Get summary statistics."""
        events = self._events
        total = len(events)
        by_type: dict[str, int] = {}
        for e in events:
            by_type[e["event"]] = by_type.get(e["event"], 0) + 1
        return {"total_events": total, "by_type": by_type}

    # ── Internal ──

    def _emit(self, event: str, data: dict) -> None:
        """Emit a structured event — fail-open."""
        try:
            entry = {
                "event": event,
                "timestamp": time.time(),
                **data,
            }
            self._events.append(entry)
            # Keep bounded
            if len(self._events) > 500:
                self._events = self._events[-300:]
            # Structured log
            log.info(event, **{k: v for k, v in data.items() if not isinstance(v, (list, dict))})
        except Exception:
            _silent_log.debug("suppressed_exception", src='observability.py')

    def _inc(self, metric: str, labels: dict | None = None) -> None:
        """Increment a counter — fail-open."""
        try:
            if self._metrics:
                self._metrics.inc(metric, labels=labels)
        except Exception:
            _silent_log.debug("suppressed_exception", src='observability.py')

    def _observe(self, metric: str, value: float, labels: dict | None = None) -> None:
        """Observe a histogram value — fail-open."""
        try:
            if self._metrics:
                self._metrics.observe(metric, value, labels=labels)
        except Exception:
            _silent_log.debug("suppressed_exception", src='observability.py')


# ── Singleton ──

_instance: SIObservability | None = None


def get_si_observability() -> SIObservability:
    """Get the singleton observability instance."""
    global _instance
    if _instance is None:
        _instance = SIObservability()
    return _instance
