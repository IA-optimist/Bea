"""
kernel/planning/planner.py — Kernel Planning Engine
=====================================================
The kernel's planning interface. Takes a KernelGoal and produces a KernelPlan.

KERNEL RULE: This module does NOT import from core/, agents/, api/, tools/.
Core planning implementations (core/mission_planner.py, core/goal_decomposer.py)
can register themselves here via register_core_planner(). If no core planner
is registered, the kernel uses its own heuristic planner.

Registration (at app startup):
  from kernel.planning.planner import register_core_planner
  from core.mission_planner import MissionPlanner
  register_core_planner(MissionPlanner().build_plan)
"""
from __future__ import annotations

import uuid
import logging
from typing import Callable, Optional

from kernel.planning.goal import (
    KernelGoal, KernelPlan, KernelPlanStep, PlanComplexity,
)

log = logging.getLogger("kernel.planning")

# ── Registration slot ─────────────────────────────────────────────────────────
_core_planner_fn: Optional[Callable[..., object]] = None


def register_core_planner(fn: Callable[..., object]) -> None:
    """
    Register a core planning function (e.g. core.mission_planner.MissionPlanner.build_plan).
    Called at app startup. kernel/planning never imports core directly.
    """
    global _core_planner_fn
    _core_planner_fn = fn
    log.debug("kernel_planner_registered")


class KernelPlanner:
    """
    Converts a KernelGoal into a KernelPlan.

    Priority:
      1. Registered core planner (rich, mission-type-aware)
      2. Kernel heuristic planner (minimal, always available)

    The kernel heuristic planner produces a single-step plan when no core
    planner is registered. This ensures the system always has a plan.
    """

    # Complexity thresholds (word count heuristic)
    _COMPLEX_THRESHOLD = 30   # goals > 30 words → HIGH
    _MEDIUM_THRESHOLD  = 10   # goals > 10 words → MEDIUM

    def build(self, goal: KernelGoal) -> KernelPlan:
        """
        Build a plan for the given goal.
        Never raises — returns minimal plan on error.
        """
        plan_id = f"kplan-{uuid.uuid4().hex[:8]}"

        # 1 — Try registered core planner
        if _core_planner_fn is not None:
            try:
                raw = _core_planner_fn(goal.description)
                return self._from_core_result(plan_id, goal, raw)
            except Exception as e:
                log.warning("kernel_planner_core_failed", err=str(e)[:80])

        # 2 — Kernel heuristic planner
        return self._heuristic_plan(plan_id, goal)

    def _complexity(self, goal: KernelGoal) -> PlanComplexity:
        word_count = len(goal.description.split())
        if word_count > self._COMPLEX_THRESHOLD:
            return PlanComplexity.HIGH
        if word_count > self._MEDIUM_THRESHOLD:
            return PlanComplexity.MEDIUM
        return PlanComplexity.LOW

    def _heuristic_plan(self, plan_id: str, goal: KernelGoal) -> KernelPlan:
        """
        Minimal heuristic plan: analyze → execute → review.
        Always works, no external dependencies.
        """
        complexity = self._complexity(goal)

        steps = [
            KernelPlanStep(
                step_id=0, action=f"Analyser: {goal.description[:80]}",
                agent_hint="planner", complexity=PlanComplexity.LOW,
            ),
            KernelPlanStep(
                step_id=1, action=f"Exécuter: {goal.description[:80]}",
                agent_hint="executor", complexity=complexity, depends_on=[0],
            ),
            KernelPlanStep(
                step_id=2, action="Valider et synthétiser le résultat",
                agent_hint="reviewer", complexity=PlanComplexity.LOW, depends_on=[1],
            ),
        ]

        return KernelPlan(
            plan_id=plan_id, goal=goal, steps=steps,
            complexity=complexity, source="kernel_heuristic",
        )

    def _from_core_result(self, plan_id: str, goal: KernelGoal, raw: object) -> KernelPlan:
        """
        Convert a core planner result (MissionPlan or dict) to a KernelPlan.
        Handles: MissionPlan (has .steps list), dict (has "steps" key), fallback.
        """
        steps: list[KernelPlanStep] = []

        # MissionPlan object (core/mission_planner.py)
        raw_steps = getattr(raw, "steps", None) or (raw.get("steps") if isinstance(raw, dict) else None)

        if raw_steps:
            for i, s in enumerate(raw_steps):
                if hasattr(s, "description"):
                    action = s.description
                    agent  = getattr(s, "required_agents", [""])[0] if getattr(s, "required_agents", []) else ""
                    tool   = getattr(s, "required_tools", [""])[0] if getattr(s, "required_tools", []) else ""
                    cplx   = PlanComplexity(getattr(s, "estimated_complexity", "medium")) if hasattr(s, "estimated_complexity") else PlanComplexity.MEDIUM
                    deps   = getattr(s, "depends_on", [])
                elif isinstance(s, dict):
                    action = s.get("action") or s.get("description") or str(s)
                    agent  = s.get("agent_hint") or s.get("agent", "")
                    tool   = s.get("tool_hint") or s.get("tool", "")
                    cplx   = PlanComplexity.MEDIUM
                    deps   = s.get("depends_on", [])
                else:
                    action = str(s)
                    agent = tool = ""
                    cplx = PlanComplexity.MEDIUM
                    deps = []

                steps.append(KernelPlanStep(
                    step_id=i, action=action, agent_hint=agent, tool_hint=tool,
                    complexity=cplx, depends_on=deps,
                ))

        if not steps:
            return self._heuristic_plan(plan_id, goal)

        complexity = max((s.complexity for s in steps), key=lambda c: list(PlanComplexity).index(c))
        return KernelPlan(
            plan_id=plan_id, goal=goal, steps=steps,
            complexity=complexity, source="core_planner",
        )


# ── Module-level singleton ────────────────────────────────────────────────────
_planner: KernelPlanner | None = None


def get_planner() -> KernelPlanner:
    """Return the singleton KernelPlanner."""
    global _planner
    if _planner is None:
        _planner = KernelPlanner()
    return _planner
