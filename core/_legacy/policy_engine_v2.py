"""
core/policy/policy_engine.py — Economic Policy Engine.

Guardrail between MetaOrchestrator and Executor.
Evaluates cost, success probability, expected value, and budget
before allowing action execution.

NOT a replacement for the orchestrator — a decision filter.
"""
from __future__ import annotations

import os
import time
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal

log = logging.getLogger("jarvis.policy")


# ── Cost profile per tool category ───────────────────────────────────────────

_DEFAULT_TOOL_COSTS: dict[str, float] = {
    # Low cost — auto-allowed
    "web_search": 0.005,
    "web_fetch": 0.003,
    "file_read": 0.001,
    "memory_read": 0.001,
    # Medium cost
    "file_write": 0.01,
    "memory_write": 0.01,
    "api_call": 0.05,
    "browser_navigate": 0.03,
    # High cost
    "shell_execute": 0.10,
    "code_execute": 0.10,
    # LLM inference (estimated per call)
    "llm_reasoning": 0.08,
    "llm_long_reasoning": 0.25,
}

# ── Priority multipliers ─────────────────────────────────────────────────────

PRIORITY_BUDGET_MULTIPLIER = {
    "LOW": 0.5,
    "NORMAL": 1.0,
    "HIGH": 2.0,
    "CRITICAL": 5.0,
}


# ── Policy Decision ──────────────────────────────────────────────────────────

@dataclass
class PolicyDecision:
    """Result of policy evaluation for an action."""
    allowed: bool = True
    reason: str = ""
    risk_level: str = "LOW"
    estimated_cost: float = 0.0
    expected_value: float = 0.0
    score: float = 0.0
    requires_approval: bool = False
    suggested_alternative: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Action Cost Estimate ─────────────────────────────────────────────────────

@dataclass
class ActionCostEstimate:
    """Cost metadata for a proposed action."""
    estimated_cost: float = 0.0
    estimated_duration: float = 0.0
    success_probability: float = 0.7
    expected_value: float = 1.0
    priority: str = "NORMAL"

    @property
    def score(self) -> float:
        """Net expected value: (value * probability) - cost."""
        return (self.expected_value * self.success_probability) - self.estimated_cost

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = self.score
        return d


# ── Budget Tracker ────────────────────────────────────────────────────────────

class BudgetTracker:
    """Tracks cumulative cost per mission."""

    def __init__(self):
        self._lock = threading.Lock()
        self._missions: dict[str, dict] = {}

    def record(self, mission_id: str, cost: float, tokens: int = 0,
               duration: float = 0.0) -> None:
        with self._lock:
            if mission_id not in self._missions:
                self._missions[mission_id] = {
                    "total_cost": 0.0,
                    "total_tokens": 0,
                    "total_duration": 0.0,
                    "tool_calls": 0,
                    "started_at": time.time(),
                }
            m = self._missions[mission_id]
            m["total_cost"] += cost
            m["total_tokens"] += tokens
            m["total_duration"] += duration
            m["tool_calls"] += 1

    def get(self, mission_id: str) -> dict:
        with self._lock:
            return dict(self._missions.get(mission_id, {
                "total_cost": 0.0, "total_tokens": 0,
                "total_duration": 0.0, "tool_calls": 0,
            }))

    def check_budget(self, mission_id: str, config: "PolicyConfig") -> Optional[str]:
        """Return violation reason if budget exceeded, else None."""
        m = self.get(mission_id)
        if m["total_cost"] > config.max_cost_per_mission:
            return f"budget_exceeded: {m['total_cost']:.3f} > {config.max_cost_per_mission}"
        if config.max_tokens_per_mission and m["total_tokens"] > config.max_tokens_per_mission:
            return f"token_limit: {m['total_tokens']} > {config.max_tokens_per_mission}"
        if config.max_execution_time and m["total_duration"] > config.max_execution_time:
            return f"time_limit: {m['total_duration']:.1f}s > {config.max_execution_time}s"
        return None

    def cleanup(self, max_age: float = 7200) -> int:
        """Remove old mission budgets."""
        cutoff = time.time() - max_age
        with self._lock:
            stale = [k for k, v in self._missions.items()
                     if v.get("started_at", 0) < cutoff]
            for k in stale:
                del self._missions[k]
            return len(stale)


# ── Policy Configuration ─────────────────────────────────────────────────────

@dataclass
class PolicyConfig:
    """Configurable policy thresholds."""
    max_cost_per_mission: float = 2.0
    max_tokens_per_mission: int = 150_000
    max_execution_time: float = 120.0
    approval_threshold_score: float = 0.05
    auto_approve_threshold: float = 0.50
    # Per-risk-level max cost
    low_risk_max_cost: float = 0.10
    medium_risk_max_cost: float = 0.50
    high_risk_requires_approval: bool = True

    @classmethod
    def from_yaml(cls, path: str = "config/policy.yaml") -> "PolicyConfig":
        """Load from YAML if available, else defaults."""
        try:
            import yaml
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            return cls(
                max_cost_per_mission=data.get("max_cost_per_mission", 2.0),
                max_tokens_per_mission=data.get("max_tokens_per_mission", 150_000),
                max_execution_time=data.get("max_execution_time_seconds", 120.0),
                approval_threshold_score=data.get("approval_threshold_score", 0.05),
                auto_approve_threshold=data.get("auto_approve_threshold", 0.50),
                low_risk_max_cost=data.get("risk_thresholds", {}).get("LOW", {}).get("max_cost", 0.10),
                medium_risk_max_cost=data.get("risk_thresholds", {}).get("MEDIUM", {}).get("max_cost", 0.50),
                high_risk_requires_approval=data.get("risk_thresholds", {}).get("HIGH", {}).get("requires_approval", True),
            )
        except Exception:
            return cls()

    def to_dict(self) -> dict:
        return asdict(self)


# ── Policy Engine ─────────────────────────────────────────────────────────────

class PolicyEngine:
    """
    Economic decision filter for action execution.

    Evaluates proposed actions against cost, value, and budget constraints.
    Does NOT replace orchestrator — acts as a guardrail.
    """

    def __init__(self, config: PolicyConfig = None):
        self.config = config or PolicyConfig.from_yaml()
        self.budget = BudgetTracker()
        self._tool_costs = dict(_DEFAULT_TOOL_COSTS)

    def evaluate(
        self,
        tool_name: str,
        mission_id: str = "",
        params: dict = None,
        priority: str = "NORMAL",
        estimated_value: float = 1.0,
        success_probability: float = 0.7,
    ) -> PolicyDecision:
        """
        Evaluate a proposed action against policy rules.

        Returns PolicyDecision with allowed/blocked/requires_approval.
        """
        # AI OS control profile check (fail-open)
        try:
            from core.policy.control_profiles import get_active_profile
            profile = get_active_profile()
            if profile.requires_approval(tool_name):
                log.info("policy_profile_approval", tool=tool_name, profile=profile.name)
                return PolicyDecision(
                    allowed=True,
                    reason=f"Profile {profile.name}: {tool_name} requires approval",
                    cost_estimate=self._estimate_cost(tool_name, params or {}),
                    requires_approval=True,
                )
        except Exception:
            pass
        cost = self._estimate_cost(tool_name, params or {})
        estimate = ActionCostEstimate(
            estimated_cost=cost,
            success_probability=success_probability,
            expected_value=estimated_value,
            priority=priority,
        )
        score = estimate.score

        # 1. Budget check (hard limit)
        if mission_id:
            violation = self.budget.check_budget(mission_id, self.config)
            if violation:
                return PolicyDecision(
                    allowed=False,
                    reason=f"budget_violation: {violation}",
                    risk_level="HIGH",
                    estimated_cost=cost,
                    expected_value=estimated_value,
                    score=score,
                )

        # 2. Priority-adjusted threshold
        multiplier = PRIORITY_BUDGET_MULTIPLIER.get(priority, 1.0)
        adj_approval_threshold = self.config.approval_threshold_score / multiplier
        adj_auto_threshold = self.config.auto_approve_threshold / multiplier

        # 3. Classify risk
        risk = self._classify_risk(tool_name, cost)

        # 4. Score evaluation (negative ROI is a hard block — checked first)
        if score < 0:
            # Negative ROI — block unless critical
            if priority == "CRITICAL":
                return PolicyDecision(
                    allowed=True,
                    reason="negative_roi_but_critical_priority",
                    risk_level="HIGH",
                    estimated_cost=cost,
                    expected_value=estimated_value,
                    score=score,
                    requires_approval=True,
                )
            return PolicyDecision(
                allowed=False,
                reason=f"negative_roi: score={score:.3f} (value*prob={estimated_value*success_probability:.3f} < cost={cost:.3f})",
                risk_level="HIGH",
                estimated_cost=cost,
                expected_value=estimated_value,
                score=score,
                suggested_alternative=self._suggest_cheaper(tool_name),
            )

        if score < adj_approval_threshold:
            # Near-zero ROI — request approval
            return PolicyDecision(
                allowed=True,
                reason=f"marginal_roi: score={score:.3f}, requesting approval",
                risk_level="MEDIUM",
                estimated_cost=cost,
                expected_value=estimated_value,
                score=score,
                requires_approval=True,
            )

        # 5. High-risk tools require approval even with positive ROI
        if risk == "HIGH" and self.config.high_risk_requires_approval:
            return PolicyDecision(
                allowed=True,
                reason=f"high_risk_tool: {tool_name} (cost={cost:.3f})",
                risk_level="HIGH",
                estimated_cost=cost,
                expected_value=estimated_value,
                score=score,
                requires_approval=True,
            )

        # 6. Auto-approve: good ROI
        return PolicyDecision(
            allowed=True,
            reason=f"positive_roi: score={score:.3f}",
            risk_level=risk,
            estimated_cost=cost,
            expected_value=estimated_value,
            score=score,
        )

    def record_execution(self, mission_id: str, tool_name: str,
                         cost: float = None, tokens: int = 0,
                         duration: float = 0.0) -> None:
        """Record actual execution cost for budget tracking."""
        actual_cost = cost if cost is not None else self._estimate_cost(tool_name, {})
        self.budget.record(mission_id, actual_cost, tokens, duration)

    def get_budget(self, mission_id: str) -> dict:
        return self.budget.get(mission_id)

    # ── Private helpers ───────────────────────────────────────────────────

    def _estimate_cost(self, tool_name: str, params: dict) -> float:
        """Estimate cost based on tool type and params."""
        base = self._tool_costs.get(tool_name, 0.05)
        # Scale by param complexity
        if len(params) > 5:
            base *= 1.2
        return round(base, 4)

    # Tools that are always HIGH risk regardless of cost
    _HIGH_RISK_TOOLS = {"shell_execute", "code_execute"}
    _MEDIUM_RISK_TOOLS = {"api_call", "browser_navigate", "file_write", "memory_write"}

    def _classify_risk(self, tool_name: str, cost: float) -> str:
        """Classify risk by tool type first, then by cost."""
        if tool_name in self._HIGH_RISK_TOOLS:
            return "HIGH"
        if tool_name in self._MEDIUM_RISK_TOOLS:
            return "MEDIUM"
        if cost <= self.config.low_risk_max_cost:
            return "LOW"
        elif cost <= self.config.medium_risk_max_cost:
            return "MEDIUM"
        return "HIGH"

    def _suggest_cheaper(self, tool_name: str) -> str:
        """Suggest a cheaper alternative if available."""
        alternatives = {
            "llm_long_reasoning": "llm_reasoning",
            "shell_execute": "file_read",
            "code_execute": "file_read",
            "browser_navigate": "web_fetch",
        }
        alt = alternatives.get(tool_name, "")
        return f"Consider {alt} (lower cost)" if alt else ""


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: PolicyEngine | None = None
_lock = threading.Lock()


def get_policy_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = PolicyEngine()
    return _engine
