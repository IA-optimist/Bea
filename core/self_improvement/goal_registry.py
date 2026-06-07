"""
core/self_improvement/goal_registry.py — Improvement Goal Registry.

Defines WHAT "better" means in measurable terms.
Each goal has a metric, baseline, target direction, and safety impact.
Rejects vague or unmeasurable goals.
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

log = structlog.get_logger("bea.improvement.goals")


@dataclass(frozen=True)
class ImprovementGoal:
    """A measurable improvement goal."""
    goal_id: str
    description: str
    metric_name: str
    baseline_value: float
    target_direction: Literal["up", "down"]
    importance: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    safety_impact: Literal["NONE", "LOW", "MEDIUM", "HIGH"] = "NONE"
    allowed_change_scope: list[str] = field(default_factory=list)

    def is_improvement(self, new_value: float) -> bool:
        """Check if new_value is better than baseline."""
        if self.target_direction == "down":
            return new_value < self.baseline_value
        return new_value > self.baseline_value

    def improvement_delta(self, new_value: float) -> float:
        """Signed improvement (positive = better)."""
        if self.target_direction == "down":
            return self.baseline_value - new_value
        return new_value - self.baseline_value

    def to_dict(self) -> dict:
        d = asdict(self)
        d["allowed_change_scope"] = list(self.allowed_change_scope)
        return d


# ── Default v1 goals ─────────────────────────────────────────────────────────

_DEFAULT_GOALS: list[ImprovementGoal] = [
    ImprovementGoal(
        goal_id="reduce_mission_cost",
        description="Reduce average cost per mission",
        metric_name="avg_mission_cost",
        baseline_value=0.50,
        target_direction="down",
        importance="HIGH",
        safety_impact="NONE",
        allowed_change_scope=["config/policy.yaml", "core/policy/"],
    ),
    ImprovementGoal(
        goal_id="reduce_mission_latency",
        description="Reduce average mission execution time",
        metric_name="avg_mission_duration_seconds",
        baseline_value=45.0,
        target_direction="down",
        importance="HIGH",
        safety_impact="NONE",
        allowed_change_scope=["config/", "core/planner.py"],
    ),
    ImprovementGoal(
        goal_id="reduce_executor_failures",
        description="Reduce executor failure rate",
        metric_name="executor_failure_rate",
        baseline_value=0.15,
        target_direction="down",
        importance="HIGH",
        safety_impact="LOW",
        allowed_change_scope=["core/action_executor.py", "core/tool_executor.py"],
    ),
    ImprovementGoal(
        goal_id="improve_success_rate",
        description="Improve mission completion success rate",
        metric_name="mission_success_rate",
        baseline_value=0.80,
        target_direction="up",
        importance="CRITICAL",
        safety_impact="LOW",
        allowed_change_scope=["core/"],
    ),
    ImprovementGoal(
        goal_id="reduce_unnecessary_llm_calls",
        description="Reduce unnecessary long-reasoning LLM calls",
        metric_name="unnecessary_llm_call_rate",
        baseline_value=0.20,
        target_direction="down",
        importance="MEDIUM",
        safety_impact="NONE",
        allowed_change_scope=["core/planner.py", "config/"],
    ),
    ImprovementGoal(
        goal_id="reduce_schema_violations",
        description="Reduce FinalOutput schema violations",
        metric_name="schema_violation_count",
        baseline_value=0.0,
        target_direction="down",
        importance="CRITICAL",
        safety_impact="HIGH",
        allowed_change_scope=["core/schemas/", "core/result_aggregator.py"],
    ),
    ImprovementGoal(
        goal_id="reduce_policy_false_blocks",
        description="Reduce false positive policy blocks on valid actions",
        metric_name="policy_false_block_rate",
        baseline_value=0.05,
        target_direction="down",
        importance="MEDIUM",
        safety_impact="MEDIUM",
        allowed_change_scope=["core/policy/", "config/policy.yaml"],
    ),
    ImprovementGoal(
        goal_id="improve_trace_completeness",
        description="Ensure trace_id appears in all mission outputs",
        metric_name="trace_completeness_rate",
        baseline_value=0.90,
        target_direction="up",
        importance="HIGH",
        safety_impact="NONE",
        allowed_change_scope=["core/observability/", "core/result_aggregator.py"],
    ),
]


class ImprovementGoalRegistry:
    """Registry of measurable improvement goals."""

    def __init__(self):
        self._goals: dict[str, ImprovementGoal] = {}
        for g in _DEFAULT_GOALS:
            self._goals[g.goal_id] = g

    def register(self, goal: ImprovementGoal) -> None:
        """Register a new goal. Rejects vague goals."""
        if not goal.metric_name:
            raise ValueError(f"Goal '{goal.goal_id}' has no metric_name — rejected as unmeasurable")
        if not goal.description or len(goal.description) < 10:
            raise ValueError(f"Goal '{goal.goal_id}' description too vague")
        self._goals[goal.goal_id] = goal
        log.info("goal_registered", goal_id=goal.goal_id)

    def get(self, goal_id: str) -> Optional[ImprovementGoal]:
        return self._goals.get(goal_id)

    def list_goals(self) -> list[ImprovementGoal]:
        return list(self._goals.values())

    def list_by_importance(self, importance: str = None) -> list[ImprovementGoal]:
        if importance:
            return [g for g in self._goals.values() if g.importance == importance]
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        return sorted(self._goals.values(), key=lambda g: order.get(g.importance, 9))

    def evaluate(self, goal_id: str, new_value: float) -> dict:
        """Evaluate a measurement against a goal."""
        goal = self._goals.get(goal_id)
        if not goal:
            return {"error": f"unknown goal: {goal_id}"}
        improved = goal.is_improvement(new_value)
        delta = goal.improvement_delta(new_value)
        return {
            "goal_id": goal_id,
            "baseline": goal.baseline_value,
            "new_value": new_value,
            "improved": improved,
            "delta": round(delta, 4),
            "target_direction": goal.target_direction,
        }

    def to_dict(self) -> dict:
        return {gid: g.to_dict() for gid, g in self._goals.items()}


_registry: ImprovementGoalRegistry | None = None

def get_goal_registry() -> ImprovementGoalRegistry:
    global _registry
    if _registry is None:
        _registry = ImprovementGoalRegistry()
    return _registry
