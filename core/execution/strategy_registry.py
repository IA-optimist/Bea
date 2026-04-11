"""
core/execution/strategy_registry.py — Strategy v2: capability-aware registry with promotion.

Design:
  - StrategyProfile: named strategy with model, budget, template config
  - StrategyRegistry: discover, compare, promote better strategies per task
  - Auto-promotion: when a strategy consistently outperforms current default, it becomes the new default
  - Promotion requires MIN_SAMPLES and MIN_IMPROVEMENT to avoid noise
  - All decisions logged and traceable
  - Fail-open: defaults survive any error
"""
from __future__ import annotations

import json
import time
import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.execution.strategy_memory import (
    StrategyMemory, StrategyRecord, get_strategy_memory,
)

_silent_log = __import__("structlog").get_logger(__name__)
log = structlog.get_logger("execution.strategy_registry")

# ── Promotion thresholds ───────────────────────────────────────

MIN_SAMPLES = 5          # minimum executions before promotion eligible
MIN_IMPROVEMENT = 0.05   # composite score improvement required (5%)
COOLDOWN_SECONDS = 3600  # 1 hour between promotions per task type


# ── Strategy Profile ───────────────────────────────────────────

@dataclass
class StrategyProfile:
    """A named strategy configuration."""
    strategy_id: str
    model_preference: str = ""     # e.g., "anthropic/claude-sonnet-4.5"
    budget_mode: str = "normal"
    template_preference: str = ""
    description: str = ""
    is_default: bool = False
    promoted_at: float = 0.0
    promoted_from: str = ""        # previous default it replaced

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "model_preference": self.model_preference,
            "budget_mode": self.budget_mode,
            "template_preference": self.template_preference,
            "description": self.description,
            "is_default": self.is_default,
            "promoted_at": self.promoted_at,
            "promoted_from": self.promoted_from,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyProfile":
        return cls(
            strategy_id=d.get("strategy_id", ""),
            model_preference=d.get("model_preference", ""),
            budget_mode=d.get("budget_mode", "normal"),
            template_preference=d.get("template_preference", ""),
            description=d.get("description", ""),
            is_default=d.get("is_default", False),
            promoted_at=d.get("promoted_at", 0.0),
            promoted_from=d.get("promoted_from", ""),
        )


@dataclass
class PromotionEvent:
    """Record of a strategy promotion."""
    task_type: str
    old_strategy: str
    new_strategy: str
    old_score: float
    new_score: float
    improvement: float
    sample_count: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "old_strategy": self.old_strategy,
            "new_strategy": self.new_strategy,
            "old_score": round(self.old_score, 3),
            "new_score": round(self.new_score, 3),
            "improvement": round(self.improvement, 3),
            "sample_count": self.sample_count,
            "timestamp": self.timestamp,
        }


# ── Strategy Registry ──────────────────────────────────────────

class StrategyRegistry:
    """
    Manages strategy profiles per task type with automatic promotion.

    When a challenger strategy outperforms the current default (by MIN_IMPROVEMENT
    over MIN_SAMPLES), it gets promoted to default.
    """

    def __init__(
        self,
        memory: Optional[StrategyMemory] = None,
        persist_path: Optional[Path] = None,
    ):
        self._memory = memory or get_strategy_memory()
        self._defaults: dict[str, StrategyProfile] = {}  # task_type → default
        self._profiles: dict[str, dict[str, StrategyProfile]] = {}  # task_type → {id: profile}
        self._promotions: list[PromotionEvent] = []
        self._last_promotion: dict[str, float] = {}  # task_type → timestamp
        self._path = persist_path
        self._load()

    def register_strategy(
        self, task_type: str, profile: StrategyProfile
    ) -> None:
        """Register a strategy for a task type."""
        self._profiles.setdefault(task_type, {})[profile.strategy_id] = profile
        if profile.is_default:
            self._defaults[task_type] = profile
        self._save()

    def get_default(self, task_type: str) -> Optional[StrategyProfile]:
        """Get current default strategy for a task type."""
        return self._defaults.get(task_type)

    def get_strategies(self, task_type: str) -> list[StrategyProfile]:
        """Get all registered strategies for a task type."""
        return list(self._profiles.get(task_type, {}).values())

    def get_all_defaults(self) -> dict[str, dict]:
        """Get all current defaults."""
        return {tt: p.to_dict() for tt, p in self._defaults.items()}

    def check_promotion(self, task_type: str) -> Optional[PromotionEvent]:
        """
        Check if any strategy should be promoted for a task type.

        Returns PromotionEvent if promotion happened, None otherwise.
        """
        # Cooldown check
        last = self._last_promotion.get(task_type, 0)
        if time.time() - last < COOLDOWN_SECONDS:
            return None

        comparison = self._memory.compare(task_type)
        if comparison.sample_count < MIN_SAMPLES:
            return None

        if not comparison.strategies or not comparison.best_strategy:
            return None

        current_default = self._defaults.get(task_type)
        current_id = current_default.strategy_id if current_default else ""
        best_id = comparison.best_strategy
        best_score = comparison.best_score

        # No change needed
        if best_id == current_id:
            return None

        # Find current default's score
        current_score = 0.0
        for s in comparison.strategies:
            if s["strategy_id"] == current_id:
                current_score = s["composite_score"]
                break

        # Check minimum improvement
        improvement = best_score - current_score
        if improvement < MIN_IMPROVEMENT:
            return None

        # Check challenger has enough samples
        challenger_samples = 0
        for s in comparison.strategies:
            if s["strategy_id"] == best_id:
                challenger_samples = s["sample_count"]
                break
        if challenger_samples < MIN_SAMPLES:
            return None

        # Promote!
        new_profile = self._profiles.get(task_type, {}).get(best_id)
        if not new_profile:
            new_profile = StrategyProfile(
                strategy_id=best_id,
                description=f"Auto-promoted from data ({challenger_samples} samples)",
            )
            self._profiles.setdefault(task_type, {})[best_id] = new_profile

        # Demote old default
        if current_default:
            current_default.is_default = False

        # Set new default
        new_profile.is_default = True
        new_profile.promoted_at = time.time()
        new_profile.promoted_from = current_id
        self._defaults[task_type] = new_profile

        event = PromotionEvent(
            task_type=task_type,
            old_strategy=current_id,
            new_strategy=best_id,
            old_score=current_score,
            new_score=best_score,
            improvement=improvement,
            sample_count=challenger_samples,
        )
        self._promotions.append(event)
        self._last_promotion[task_type] = time.time()
        self._save()

        log.info("strategy_promoted",
                 task_type=task_type,
                 old=current_id, new=best_id,
                 improvement=round(improvement, 3))

        return event

    def check_all_promotions(self) -> list[PromotionEvent]:
        """Check promotions for all known task types."""
        events = []
        task_types = set()
        for r in self._memory._records:
            task_types.add(r.task_type)
        for tt in task_types:
            ev = self.check_promotion(tt)
            if ev:
                events.append(ev)
        return events

    def get_promotion_history(self) -> list[dict]:
        return [p.to_dict() for p in self._promotions[-50:]]

    def get_status(self) -> dict:
        return {
            "task_types": len(self._profiles),
            "total_strategies": sum(len(v) for v in self._profiles.values()),
            "defaults_set": len(self._defaults),
            "promotions_total": len(self._promotions),
            "last_promotion": (
                self._promotions[-1].to_dict() if self._promotions else None
            ),
        }

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "defaults": {tt: p.to_dict() for tt, p in self._defaults.items()},
                "profiles": {
                    tt: {sid: p.to_dict() for sid, p in strats.items()}
                    for tt, strats in self._profiles.items()
                },
                "promotions": [p.to_dict() for p in self._promotions[-100:]],
                "last_promotion": self._last_promotion,
            }
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(self._path)
        except Exception:
            _silent_log.debug("suppressed_exception", src='strategy_registry.py')

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for tt, pd in data.get("defaults", {}).items():
                self._defaults[tt] = StrategyProfile.from_dict(pd)
            for tt, strats in data.get("profiles", {}).items():
                self._profiles[tt] = {
                    sid: StrategyProfile.from_dict(sd)
                    for sid, sd in strats.items()
                }
            for pd in data.get("promotions", []):
                self._promotions.append(PromotionEvent(
                    task_type=pd["task_type"],
                    old_strategy=pd["old_strategy"],
                    new_strategy=pd["new_strategy"],
                    old_score=pd["old_score"],
                    new_score=pd["new_score"],
                    improvement=pd["improvement"],
                    sample_count=pd["sample_count"],
                    timestamp=pd.get("timestamp", 0),
                ))
            self._last_promotion = data.get("last_promotion", {})
        except Exception:
            _silent_log.debug("suppressed_exception", src='strategy_registry.py')


# ── Singleton ──────────────────────────────────────────────────

_registry: Optional[StrategyRegistry] = None


def get_strategy_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        from pathlib import Path
        _registry = StrategyRegistry(
            persist_path=Path("workspace/data/strategy_registry.json"),
        )
    return _registry
