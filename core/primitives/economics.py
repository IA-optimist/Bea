"""
BEA — Economic Primitives (sections 7, 12)
Full economic evaluation, outcome tracking, and trend analysis.
"""
from __future__ import annotations

import time
import structlog
from dataclasses import asdict, dataclass

logger = structlog.get_logger("bea.operating_primitives")

# ═══════════════════════════════════════════════════════════════
# 7. ECONOMIC REASONING MODEL
# ═══════════════════════════════════════════════════════════════

@dataclass
class EconomicEstimate:
    """Full economic evaluation of a mission."""
    estimated_cost: float = 0.0       # 0-10 scale (tool + time + complexity)
    estimated_value: float = 0.0      # 0-10 scale (benefit + impact)
    estimated_risk: float = 0.0       # 0-10 scale
    time_to_value_hours: float = 0.0  # estimated hours
    probability_of_success: float = 0.5
    expected_return: float = 0.0      # (value × prob) / (cost + time + risk_penalty)
    priority_score: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def compute_economics(
    goal: str,
    mission_type: str,
    complexity: str = "medium",
    plan_steps: int = 1,
    risk_score: int = 0,
    required_tools: list[str] | None = None,
) -> EconomicEstimate:
    """Compute full economic estimate for a mission."""
    result = EconomicEstimate()

    # Cost: based on complexity + steps + tool count
    complexity_cost = {"low": 1, "medium": 3, "high": 6, "critical": 9}.get(complexity, 3)
    step_cost = min(plan_steps * 0.5, 5)
    tool_cost = min(len(required_tools or []) * 0.3, 3)
    result.estimated_cost = round(min(10, complexity_cost + step_cost + tool_cost), 1)

    # Value: based on mission type + goal keywords
    type_value = {
        "coding_task": 7, "architecture_task": 8, "system_task": 7,
        "debug_task": 6, "research_task": 5, "planning_task": 6,
        "evaluation_task": 4, "info_query": 2,
    }.get(mission_type, 3)
    # High-value keywords boost
    high_value_kw = {"deploy", "fix", "build", "create", "automate", "optimize", "launch"}
    goal_lower = goal.lower()
    kw_boost = sum(1 for kw in high_value_kw if kw in goal_lower)
    result.estimated_value = round(min(10, type_value + kw_boost * 0.5), 1)

    # Risk
    result.estimated_risk = round(min(10, risk_score + (1 if complexity in ("high", "critical") else 0)), 1)

    # Time to value (hours)
    step_time = {"low": 0.1, "medium": 0.3, "high": 0.8, "critical": 2.0}.get(complexity, 0.3)
    result.time_to_value_hours = round(plan_steps * step_time, 1)

    # Probability of success: from performance data if available
    try:
        from core.mission_performance_tracker import get_mission_performance_tracker
        mpt = get_mission_performance_tracker()
        strategy = mpt.get_strategy_for_type(mission_type)
        if strategy and strategy.get("sample_size", 0) >= 3:
            result.probability_of_success = round(strategy["success_rate"], 2)
        else:
            result.probability_of_success = 0.6  # default moderate
    except Exception:
        result.probability_of_success = 0.6

    # Expected return: (value × probability) / (cost + time + risk_penalty)
    risk_penalty = result.estimated_risk * 0.3
    denominator = max(result.estimated_cost + result.time_to_value_hours + risk_penalty, 0.1)
    result.expected_return = round(
        (result.estimated_value * result.probability_of_success) / denominator, 3
    )

    # Priority score (normalized 0-1)
    result.priority_score = round(min(1.0, result.expected_return / 3.0), 3)

    result.reasoning = (
        f"V={result.estimated_value} × P={result.probability_of_success:.0%} "
        f"/ (C={result.estimated_cost} + T={result.time_to_value_hours}h + R={risk_penalty:.1f}) "
        f"= ER={result.expected_return}"
    )
    return result


# ═══════════════════════════════════════════════════════════════
# 12. ECONOMIC EXECUTION TRACKING
# ═══════════════════════════════════════════════════════════════

_economic_history: list[dict] = []
_MAX_ECONOMIC_HISTORY = 200


def record_economic_outcome(
    mission_id: str,
    estimated: EconomicEstimate,
    actual_success: bool,
    actual_duration_s: float,
    actual_tools_used: int,
):
    """Record estimated vs actual economic signals."""
    global _economic_history
    actual_cost = min(10, actual_tools_used * 0.5 + actual_duration_s / 60)
    realized_value = estimated.estimated_value if actual_success else 0
    efficiency = realized_value / max(actual_cost, 0.1)

    record = {
        "mission_id": mission_id,
        "estimated_return": estimated.expected_return,
        "actual_success": actual_success,
        "actual_cost": round(actual_cost, 2),
        "realized_value": round(realized_value, 1),
        "efficiency": round(efficiency, 3),
        "estimation_accuracy": round(
            1.0 - abs(estimated.estimated_cost - actual_cost) / max(estimated.estimated_cost, 1), 2
        ),
        "timestamp": time.time(),
    }
    _economic_history.append(record)
    if len(_economic_history) > _MAX_ECONOMIC_HISTORY:
        _economic_history = _economic_history[-_MAX_ECONOMIC_HISTORY:]
    return record


def get_economic_trends() -> dict:
    """Get economic performance trends."""
    if not _economic_history:
        return {"total": 0, "avg_efficiency": 0, "avg_accuracy": 0, "trend": "insufficient_data"}

    recent = _economic_history[-50:]
    avg_eff = sum(r["efficiency"] for r in recent) / len(recent)
    avg_acc = sum(r["estimation_accuracy"] for r in recent) / len(recent)
    success_rate = sum(1 for r in recent if r["actual_success"]) / len(recent)

    # Trend: compare first half vs second half
    if len(recent) >= 10:
        first_half = recent[:len(recent)//2]
        second_half = recent[len(recent)//2:]
        first_eff = sum(r["efficiency"] for r in first_half) / len(first_half)
        second_eff = sum(r["efficiency"] for r in second_half) / len(second_half)
        trend = "improving" if second_eff > first_eff * 1.1 else "declining" if second_eff < first_eff * 0.9 else "stable"
    else:
        trend = "insufficient_data"

    return {
        "total": len(_economic_history),
        "avg_efficiency": round(avg_eff, 3),
        "avg_accuracy": round(avg_acc, 3),
        "success_rate": round(success_rate, 3),
        "trend": trend,
        "recent_count": len(recent),
    }
