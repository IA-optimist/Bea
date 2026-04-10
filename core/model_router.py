"""
core/model_router.py — Legacy model routing stub (TEST-ONLY).

⚠️  DEPRECATED: This router is NOT used in production.
    Production routing uses: core/capability_routing/router.py

Status: Kept for backward compatibility with test suite (16 tests).
Consolidation note: Will be removed after tests migrated to capability_routing.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RoutingDecision:
    tier: str
    reason: str
    estimated_cost: float = 0.0
    model: str = ""
    fallback_tier: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "reason": self.reason,
            "estimated_cost": self.estimated_cost,
            "model": self.model,
        }


class ModelRouter:
    """Simple model tier router. Routes based on task_type and complexity."""

    _TIER_MAP = {
        "classify": "FAST",
        "search": "FAST",
        "embed": "FAST",
        "summarize": "STANDARD",
        "plan": "STANDARD",
        "code": "STANDARD",
        "business_analysis": "STRONG",
        "creative": "STRONG",
        "research": "STRONG",
        "reason": "STRONG",
    }

    _COST_MAP = {"FAST": 0.0001, "STANDARD": 0.001, "STRONG": 0.01}

    def __init__(self) -> None:
        self._usage: dict[str, dict] = {}

    def route(
        self,
        task_type: str = "",
        complexity: str = "",
        context_size: int = 0,
        estimated_tokens: int = 0,
        mission_priority: str = "",
    ) -> RoutingDecision:
        tier = "STANDARD"
        reason = "default"

        # Complexity override
        if complexity == "trivial":
            tier, reason = "FAST", "trivial_complexity"
        elif complexity == "complex":
            tier, reason = "STRONG", "complex_task"
        elif task_type:
            tier = self._TIER_MAP.get(task_type.lower(), "STANDARD")
            reason = f"task_type:{task_type}"

        # Context size upgrade
        if (context_size > 16000) or (estimated_tokens > 6000):
            if tier == "FAST":
                tier = "STANDARD"
                reason = "context_upgrade"

        # Critical priority boost
        if mission_priority == "CRITICAL" and tier == "FAST":
            tier = "STANDARD"
            reason = "critical_boost"

        # Set fallback tier
        fallback = {"STRONG": "STANDARD", "STANDARD": None, "FAST": None}.get(tier)
        return RoutingDecision(
            tier=tier,
            reason=reason,
            estimated_cost=self._COST_MAP.get(tier, 0.001),
            fallback_tier=fallback,
        )

    def record_usage(self, tier: str, tokens: int = 0) -> None:
        if tier not in self._usage:
            self._usage[tier] = {"calls": 0, "total_tokens": 0}
        self._usage[tier]["calls"] += 1
        self._usage[tier]["total_tokens"] += tokens

    def get_usage(self) -> dict:
        return dict(self._usage)

    def estimated_savings(self) -> dict:
        """Estimate savings vs always using STRONG model."""
        strong_cost = self._COST_MAP["STRONG"]
        actual = 0.0
        baseline = 0.0
        for tier, data in self._usage.items():
            tokens = data["total_tokens"]
            actual += (tokens / 1000) * self._COST_MAP.get(tier, 0.001)
            baseline += (tokens / 1000) * strong_cost
        savings = baseline - actual
        pct = (savings / baseline * 100) if baseline > 0 else 0.0
        return {"savings": round(savings, 4), "savings_pct": round(pct, 1), "baseline": round(baseline, 4)}
