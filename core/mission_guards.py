"""
JARVIS MAX — Mission Guards (P10 + P5)
==========================================
Iteration limit and token/cost budget enforcement for missions.

Injected into MetaOrchestrator via CognitiveBridge — no CRITICAL file modification.

P10 — Iteration Limit:
  max_steps: hard cap on execution steps per mission (default 50)
  Prevents infinite loops, runaway agents, and resource exhaustion.

P5 — Token Budget:
  max_cost_usd: hard cost ceiling per mission
  max_tokens: hard token ceiling per mission
  warning_threshold: % at which to emit warning (default 80%)
  Tracks cumulative cost/tokens across steps.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import structlog

log = structlog.get_logger()

# Cost tiers (from existing llm_routing_policy.py)
_COST_TIERS = {
    "local": 0.0, "nano": 0.10, "cheap": 0.50,
    "standard": 3.00, "premium": 15.00,
}
_DEFAULT_COST_PER_STEP = 0.001  # ~$1/1000 steps as fallback


@dataclass
class MissionBudget:
    """Budget limits for a single mission."""
    max_steps: int = 50
    max_cost_usd: float = 0.0      # 0 = unlimited
    max_tokens: int = 0             # 0 = unlimited
    warning_threshold: float = 0.8  # Emit warning at 80%
    # Runtime counters
    steps_used: int = 0
    cost_used_usd: float = 0.0
    tokens_used: int = 0
    warnings_emitted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "max_steps": self.max_steps,
            "steps_used": self.steps_used,
            "max_cost_usd": self.max_cost_usd,
            "cost_used_usd": round(self.cost_used_usd, 4),
            "max_tokens": self.max_tokens,
            "tokens_used": self.tokens_used,
            "warnings": self.warnings_emitted[-5:],
        }


class StepLimitExceeded(Exception):
    """Raised when mission exceeds max_steps."""
    pass


class BudgetExceeded(Exception):
    """Raised when mission exceeds cost/token budget."""
    pass


class MissionGuardian:
    """
    Enforces iteration limits and budgets across all active missions.

    Thread-safe. Fail-open: if guard check errors, execution proceeds.
    """

    def __init__(self, default_max_steps: int = 50):
        self._budgets: Dict[str, MissionBudget] = {}
        self._lock = threading.RLock()
        self._default_max_steps = default_max_steps

    def register_mission(
        self,
        mission_id: str,
        max_steps: int = 0,
        max_cost_usd: float = 0.0,
        max_tokens: int = 0,
    ) -> MissionBudget:
        """Register a mission with its budget. 0 = use defaults or unlimited."""
        budget = MissionBudget(
            max_steps=max_steps or self._default_max_steps,
            max_cost_usd=max_cost_usd,
            max_tokens=max_tokens,
        )
        with self._lock:
            self._budgets[mission_id] = budget
        return budget

    def check_step(
        self,
        mission_id: str,
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> Dict[str, Any]:
        """
        Check and record a step. Returns status dict.
        Raises StepLimitExceeded or BudgetExceeded on hard stop.

        Return dict:
          allowed: bool
          reason: str (if not allowed)
          warning: str (if approaching limit)
          budget: dict (current state)
        """
        with self._lock:
            budget = self._budgets.get(mission_id)
            if not budget:
                # Auto-register with defaults
                budget = self.register_mission(mission_id)

            budget.steps_used += 1
            budget.cost_used_usd += cost_usd or _DEFAULT_COST_PER_STEP
            budget.tokens_used += tokens

            result: Dict[str, Any] = {"allowed": True, "budget": budget.to_dict()}

            # P10: Iteration limit check
            if budget.steps_used > budget.max_steps:
                reason = (f"Step limit exceeded: {budget.steps_used}/{budget.max_steps}. "
                         f"Mission will be terminated to prevent runaway execution.")
                budget.warnings_emitted.append(f"HARD_STOP:steps:{budget.steps_used}")
                log.warning("mission_guard.step_limit_exceeded",
                           mission_id=mission_id, steps=budget.steps_used,
                           max_steps=budget.max_steps)
                raise StepLimitExceeded(reason)

            # P5: Cost budget check
            if budget.max_cost_usd > 0 and budget.cost_used_usd > budget.max_cost_usd:
                reason = (f"Cost budget exceeded: ${budget.cost_used_usd:.4f}/${budget.max_cost_usd:.4f}. "
                         f"Mission will be terminated to prevent overspend.")
                budget.warnings_emitted.append(f"HARD_STOP:cost:${budget.cost_used_usd:.4f}")
                log.warning("mission_guard.cost_exceeded",
                           mission_id=mission_id, cost=budget.cost_used_usd,
                           max_cost=budget.max_cost_usd)
                raise BudgetExceeded(reason)

            # P5: Token budget check
            if budget.max_tokens > 0 and budget.tokens_used > budget.max_tokens:
                reason = (f"Token budget exceeded: {budget.tokens_used}/{budget.max_tokens}.")
                budget.warnings_emitted.append(f"HARD_STOP:tokens:{budget.tokens_used}")
                log.warning("mission_guard.token_exceeded",
                           mission_id=mission_id, tokens=budget.tokens_used,
                           max_tokens=budget.max_tokens)
                raise BudgetExceeded(reason)

            # Warning thresholds
            warn_pct = budget.warning_threshold
            step_pct = budget.steps_used / budget.max_steps
            if step_pct >= warn_pct and f"WARN:steps:{budget.steps_used}" not in budget.warnings_emitted:
                w = f"Approaching step limit: {budget.steps_used}/{budget.max_steps} ({step_pct:.0%})"
                result["warning"] = w
                budget.warnings_emitted.append(f"WARN:steps:{budget.steps_used}")
                log.info("mission_guard.step_warning", mission_id=mission_id, pct=step_pct)

            if budget.max_cost_usd > 0:
                cost_pct = budget.cost_used_usd / budget.max_cost_usd
                if cost_pct >= warn_pct and f"WARN:cost:{budget.steps_used}" not in budget.warnings_emitted:
                    w = f"Approaching cost limit: ${budget.cost_used_usd:.4f}/${budget.max_cost_usd:.4f} ({cost_pct:.0%})"
                    result["warning"] = w
                    budget.warnings_emitted.append(f"WARN:cost:{budget.steps_used}")
                    log.info("mission_guard.cost_warning", mission_id=mission_id, pct=cost_pct)

            return result

    def get_budget(self, mission_id: str) -> Optional[MissionBudget]:
        return self._budgets.get(mission_id)

    def release_mission(self, mission_id: str) -> None:
        """Clean up mission budget on completion."""
        with self._lock:
            self._budgets.pop(mission_id, None)

    def active_missions(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {mid: b.to_dict() for mid, b in self._budgets.items()}


# Singleton
_guardian: Optional[MissionGuardian] = None
_guardian_lock = threading.Lock()


def get_guardian() -> MissionGuardian:
    global _guardian
    if _guardian is None:
        with _guardian_lock:
            if _guardian is None:
                _guardian = MissionGuardian()
    return _guardian
