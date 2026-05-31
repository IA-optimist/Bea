"""
core/model_intelligence/auto_update.py — Model intelligence auto-update engine.

Design:
  - Scheduled catalog refresh (daily or on-demand)
  - A/B testing when models have similar performance
  - Dynamic quality/cost ratio scoring from real usage
  - Real cost tracking from performance memory
  - All fail-open, traceable, deterministic
"""
from __future__ import annotations

import time
import structlog
from dataclasses import dataclass, field
from typing import Optional

log = structlog.get_logger("model_intelligence.auto_update")

# ── Config ─────────────────────────────────────────────────────

REFRESH_INTERVAL_HOURS = 24
AB_TEST_THRESHOLD = 0.05    # Score difference below this triggers A/B
AB_MIN_SAMPLES = 3          # Min samples per variant before declaring winner
AB_MAX_ROUNDS = 20          # Max rounds before force-declaring


# ── A/B Test ───────────────────────────────────────────────────

@dataclass
class ABTest:
    """A/B test between two model variants for a task class."""
    test_id: str = ""
    task_class: str = ""
    model_a: str = ""
    model_b: str = ""
    a_successes: int = 0
    a_failures: int = 0
    a_quality_sum: float = 0.0
    a_cost_sum: float = 0.0
    b_successes: int = 0
    b_failures: int = 0
    b_quality_sum: float = 0.0
    b_cost_sum: float = 0.0
    rounds: int = 0
    winner: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def a_total(self) -> int:
        return self.a_successes + self.a_failures

    @property
    def b_total(self) -> int:
        return self.b_successes + self.b_failures

    @property
    def a_score(self) -> float:
        if self.a_total == 0:
            return 0.5
        quality = self.a_quality_sum / self.a_total
        success_rate = self.a_successes / self.a_total
        cost_eff = 1.0 / (1.0 + self.a_cost_sum / max(self.a_total, 1) * 10)
        return quality * 0.5 + success_rate * 0.3 + cost_eff * 0.2

    @property
    def b_score(self) -> float:
        if self.b_total == 0:
            return 0.5
        quality = self.b_quality_sum / self.b_total
        success_rate = self.b_successes / self.b_total
        cost_eff = 1.0 / (1.0 + self.b_cost_sum / max(self.b_total, 1) * 10)
        return quality * 0.5 + success_rate * 0.3 + cost_eff * 0.2

    @property
    def is_conclusive(self) -> bool:
        if self.a_total < AB_MIN_SAMPLES or self.b_total < AB_MIN_SAMPLES:
            return False
        return abs(self.a_score - self.b_score) > AB_TEST_THRESHOLD or self.rounds >= AB_MAX_ROUNDS

    def pick_variant(self) -> str:
        """Pick which model to use next (balanced random)."""
        if self.a_total <= self.b_total:
            return self.model_a
        return self.model_b

    def record_outcome(
        self, model_id: str, success: bool, quality: float = 0.0, cost: float = 0.0
    ) -> None:
        self.rounds += 1
        if model_id == self.model_a:
            if success:
                self.a_successes += 1
            else:
                self.a_failures += 1
            self.a_quality_sum += quality
            self.a_cost_sum += cost
        elif model_id == self.model_b:
            if success:
                self.b_successes += 1
            else:
                self.b_failures += 1
            self.b_quality_sum += quality
            self.b_cost_sum += cost

    def evaluate(self) -> Optional[str]:
        """Evaluate the test. Returns winner model_id or None if inconclusive."""
        if not self.is_conclusive:
            return None
        if self.a_score >= self.b_score:
            self.winner = self.model_a
        else:
            self.winner = self.model_b
        self.finished_at = time.time()
        return self.winner

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "task_class": self.task_class,
            "model_a": self.model_a,
            "model_b": self.model_b,
            "a_score": round(self.a_score, 3),
            "b_score": round(self.b_score, 3),
            "a_total": self.a_total,
            "b_total": self.b_total,
            "rounds": self.rounds,
            "winner": self.winner,
            "is_conclusive": self.is_conclusive,
        }


# ── Auto Update Engine ─────────────────────────────────────────

class ModelAutoUpdate:
    """
    Manages model catalog refresh, A/B testing, and dynamic cost/quality scoring.

    Responsibilities:
      - Periodic catalog refresh
      - Detect close-performing models → start A/B test
      - Track real cost usage from invocations
      - Declare winner when test is conclusive
    """

    def __init__(self):
        self._active_tests: dict[str, ABTest] = {}   # task_class → test
        self._completed_tests: list[ABTest] = []
        self._last_refresh: float = 0
        self._real_costs: dict[str, float] = {}  # model_id → total cost

    def should_refresh(self) -> bool:
        """Check if catalog refresh is due."""
        return (time.time() - self._last_refresh) > REFRESH_INTERVAL_HOURS * 3600

    def mark_refreshed(self) -> None:
        self._last_refresh = time.time()

    def refresh_catalog(self) -> dict:
        """Refresh model catalog from OpenRouter. Returns refresh result."""
        try:
            from core.model_intelligence.catalog import get_model_catalog
            catalog = get_model_catalog()
            count_before = catalog.count
            catalog.refresh()
            count_after = catalog.count
            self._last_refresh = time.time()
            return {
                "refreshed": True,
                "models_before": count_before,
                "models_after": count_after,
                "new_models": max(0, count_after - count_before),
            }
        except Exception as e:
            return {"refreshed": False, "error": str(e)[:200]}

    def start_ab_test(
        self, task_class: str, model_a: str, model_b: str
    ) -> ABTest:
        """Start an A/B test between two models for a task class."""
        test = ABTest(
            test_id=f"ab-{task_class}-{int(time.time())}",
            task_class=task_class,
            model_a=model_a,
            model_b=model_b,
        )
        self._active_tests[task_class] = test
        log.info("ab_test_started", task_class=task_class, a=model_a, b=model_b)
        return test

    def get_active_test(self, task_class: str) -> Optional[ABTest]:
        return self._active_tests.get(task_class)

    def record_invocation(
        self, task_class: str, model_id: str,
        success: bool, quality: float = 0.0, cost: float = 0.0,
    ) -> Optional[str]:
        """
        Record model invocation. If A/B test active, routes to test.
        Returns winner model_id if test just concluded, None otherwise.
        """
        # Track real cost
        self._real_costs[model_id] = self._real_costs.get(model_id, 0) + cost

        # Feed A/B test if active
        test = self._active_tests.get(task_class)
        if test and not test.winner:
            test.record_outcome(model_id, success, quality, cost)
            winner = test.evaluate()
            if winner:
                self._completed_tests.append(test)
                del self._active_tests[task_class]
                log.info("ab_test_concluded", task_class=task_class, winner=winner)
                return winner
        return None

    def detect_ab_candidates(self) -> list[dict]:
        """
        Scan performance memory for task classes where top 2 models
        have close scores → candidates for A/B test.
        """
        candidates = []
        try:
            from core.model_intelligence.selector import (
                get_model_performance, TASK_CLASSES,
            )
            perf = get_model_performance()
            for tc in TASK_CLASSES:
                if tc in self._active_tests:
                    continue
                ranked = perf.get_best_for_task(tc, min_samples=AB_MIN_SAMPLES)
                if len(ranked) >= 2:
                    diff = abs(ranked[0].get("avg_quality", 0) - ranked[1].get("avg_quality", 0))
                    if diff < AB_TEST_THRESHOLD:
                        candidates.append({
                            "task_class": tc,
                            "model_a": ranked[0]["model_id"],
                            "model_b": ranked[1]["model_id"],
                            "quality_diff": round(diff, 3),
                            "samples_a": ranked[0].get("samples", 0),
                            "samples_b": ranked[1].get("samples", 0),
                        })
        except Exception as _exc:
            log.warning("swallowed_exception", action="auto_update_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return candidates

    def get_real_cost_stats(self) -> dict:
        """Get real cost tracking stats."""
        return {
            "models_tracked": len(self._real_costs),
            "total_cost": round(sum(self._real_costs.values()), 4),
            "per_model": {
                mid: round(cost, 4)
                for mid, cost in sorted(
                    self._real_costs.items(),
                    key=lambda x: x[1], reverse=True,
                )[:20]
            },
        }

    def get_dynamic_quality_cost_ratio(self, model_id: str) -> float:
        """
        Compute dynamic quality/cost ratio from real usage data.
        Higher = better (more quality per dollar).
        Returns 0.5 if insufficient data.
        """
        try:
            from core.model_intelligence.selector import get_model_performance
            perf = get_model_performance()
            stats = perf.get_stats(model_id)
            if not stats:
                return 0.5
            total_quality = sum(s.get("avg_quality", 0.5) for s in stats)
            avg_quality = total_quality / len(stats) if stats else 0.5
            total_cost = self._real_costs.get(model_id, 0)
            if total_cost <= 0:
                return avg_quality  # Free = quality IS the ratio
            return avg_quality / (1 + total_cost * 10)
        except Exception:
            return 0.5

    def get_status(self) -> dict:
        return {
            "active_tests": len(self._active_tests),
            "completed_tests": len(self._completed_tests),
            "last_refresh_ago_hours": round(
                (time.time() - self._last_refresh) / 3600, 1
            ) if self._last_refresh else None,
            "should_refresh": self.should_refresh(),
            "real_costs": self.get_real_cost_stats(),
            "active_test_details": {
                tc: t.to_dict() for tc, t in self._active_tests.items()
            },
        }


# ── Singleton ──────────────────────────────────────────────────

_engine: Optional[ModelAutoUpdate] = None


def get_model_auto_update() -> ModelAutoUpdate:
    global _engine
    if _engine is None:
        _engine = ModelAutoUpdate()
    return _engine
