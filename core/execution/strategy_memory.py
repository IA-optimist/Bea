"""
core/execution/strategy_memory.py — Strategy comparison + learning for execution.

Phase 4 of consolidation: closed improvement loop.

Design:
  - StrategyRecord: outcome of each execution strategy (model, budget, template)
  - StrategyComparison: compare strategies across cost, success, quality, feedback
  - StrategyMemory: persist best strategies per task type
  - Feeds into self-improvement loop and model intelligence
  - All deterministic, fail-open
"""
from __future__ import annotations

import json
import time
import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("execution.strategy_memory")


@dataclass
class StrategyRecord:
    """Record of a single execution strategy outcome."""
    task_type: str = ""          # e.g., "landing_page", "api_service"
    strategy_id: str = ""        # e.g., "normal_budget_sonnet"
    model_used: str = ""
    budget_mode: str = "normal"
    template_used: str = ""
    success: bool = False
    quality_score: float = 0.0   # 0.0-1.0 from evaluation
    cost_estimate: float = 0.0   # approximate $ cost
    duration_ms: float = 0
    retry_count: int = 0
    feedback_score: float = 0.0  # operator feedback if any
    timestamp: float = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "strategy_id": self.strategy_id,
            "model_used": self.model_used[:50],
            "budget_mode": self.budget_mode,
            "template_used": self.template_used,
            "success": self.success,
            "quality_score": round(self.quality_score, 3),
            "cost_estimate": round(self.cost_estimate, 4),
            "duration_ms": round(self.duration_ms),
            "retry_count": self.retry_count,
            "feedback_score": round(self.feedback_score, 3),
        }


@dataclass
class StrategyComparison:
    """Comparison of strategies for a task type."""
    task_type: str
    strategies: list[dict] = field(default_factory=list)
    best_strategy: str = ""
    best_score: float = 0.0
    sample_count: int = 0

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "strategies": self.strategies[:20],
            "best_strategy": self.best_strategy,
            "best_score": round(self.best_score, 3),
            "sample_count": self.sample_count,
        }


class StrategyMemory:
    """
    Persistent strategy learning memory.

    Tracks which strategies work best per task type.
    Computes aggregate scores: quality × success_rate × (1/cost_factor).
    """

    MAX_RECORDS = 500

    def __init__(self, persist_path: Optional[Path] = None):
        self._records: list[StrategyRecord] = []
        self._path = persist_path

    def record(self, rec: StrategyRecord) -> None:
        """Record a strategy outcome."""
        self._records.append(rec)
        if len(self._records) > self.MAX_RECORDS:
            self._records = self._records[-self.MAX_RECORDS:]
        self._try_persist()

    def get_best_strategy(self, task_type: str) -> Optional[str]:
        """Get the best strategy ID for a task type."""
        comparison = self.compare(task_type)
        return comparison.best_strategy if comparison.best_strategy else None

    def compare(self, task_type: str) -> StrategyComparison:
        """Compare all strategies for a task type."""
        relevant = [r for r in self._records if r.task_type == task_type]
        if not relevant:
            return StrategyComparison(task_type=task_type)

        # Group by strategy
        groups: dict[str, list[StrategyRecord]] = {}
        for r in relevant:
            sid = r.strategy_id or f"{r.budget_mode}_{r.model_used[:20]}"
            groups.setdefault(sid, []).append(r)

        strategies = []
        best_id = ""
        best_score = -1.0

        for sid, records in groups.items():
            n = len(records)
            success_rate = sum(1 for r in records if r.success) / n
            avg_quality = sum(r.quality_score for r in records) / n
            avg_cost = sum(r.cost_estimate for r in records) / n
            avg_duration = sum(r.duration_ms for r in records) / n
            avg_feedback = sum(r.feedback_score for r in records) / n

            # Composite score: quality(40%) × success(30%) × cost_efficiency(20%) × feedback(10%)
            cost_factor = 1.0 / (1.0 + avg_cost * 10)  # Lower cost → higher score
            composite = (
                avg_quality * 0.4 +
                success_rate * 0.3 +
                cost_factor * 0.2 +
                avg_feedback * 0.1
            )

            entry = {
                "strategy_id": sid,
                "sample_count": n,
                "success_rate": round(success_rate, 3),
                "avg_quality": round(avg_quality, 3),
                "avg_cost": round(avg_cost, 4),
                "avg_duration_ms": round(avg_duration),
                "composite_score": round(composite, 3),
            }
            strategies.append(entry)

            if composite > best_score:
                best_score = composite
                best_id = sid

        strategies.sort(key=lambda x: x["composite_score"], reverse=True)

        return StrategyComparison(
            task_type=task_type,
            strategies=strategies,
            best_strategy=best_id,
            best_score=best_score,
            sample_count=len(relevant),
        )

    def get_all_comparisons(self) -> list[StrategyComparison]:
        """Get comparisons for all known task types."""
        task_types = set(r.task_type for r in self._records)
        return [self.compare(tt) for tt in sorted(task_types)]

    def get_records(self, task_type: str = "", limit: int = 50) -> list[dict]:
        """Get recent strategy records."""
        records = self._records
        if task_type:
            records = [r for r in records if r.task_type == task_type]
        return [r.to_dict() for r in records[-limit:]]

    def _try_persist(self) -> None:
        """Persist to disk (fail-open)."""
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "records": [r.to_dict() for r in self._records[-self.MAX_RECORDS:]],
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(self._path)
        except Exception:
            _silent_log.debug("suppressed_exception", src='strategy_memory.py')

    def load(self) -> None:
        """Load from disk (fail-open)."""
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for rd in data.get("records", []):
                self._records.append(StrategyRecord(
                    task_type=rd.get("task_type", ""),
                    strategy_id=rd.get("strategy_id", ""),
                    model_used=rd.get("model_used", ""),
                    budget_mode=rd.get("budget_mode", "normal"),
                    template_used=rd.get("template_used", ""),
                    success=rd.get("success", False),
                    quality_score=rd.get("quality_score", 0),
                    cost_estimate=rd.get("cost_estimate", 0),
                    duration_ms=rd.get("duration_ms", 0),
                    retry_count=rd.get("retry_count", 0),
                    feedback_score=rd.get("feedback_score", 0),
                ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='strategy_memory.py')


# Singleton
_memory: Optional[StrategyMemory] = None


def get_strategy_memory() -> StrategyMemory:
    global _memory
    if _memory is None:
        persist_path = Path("workspace/data/strategy_memory.json")
        _memory = StrategyMemory(persist_path=persist_path)
        _memory.load()
    return _memory
