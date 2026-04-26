"""
core/autonomy/planners.py — Action planners for the autonomy daemon.

A planner converts (objective, current StopContext) into the next
PlannedAction. The default planner in daemon.py emits a noop ; this
module ships planners that consult real signals :

1. `objective_engine_planner(engine)` — asks
   `ObjectiveEngine.get_next_best_action()` and translates the result
   into a PlannedAction.

2. `learner_aware_planner(base, learner)` — wraps a base planner. When
   the base proposes a candidate, the planner consults the OutcomeLearner
   to verify the score is above a floor (default 0.3). Below the floor,
   the action is downgraded (description annotated) so the daemon can
   choose a different strategy on retry.

3. `chain_planner(*planners)` — try planners in order, first non-None
   wins. Matches `composite_runner` for runners.

Real-world wiring (kept as documentation, not auto-imported) :

    from core.meta_orchestrator import get_meta_orchestrator
    from core.objectives.objective_engine import get_objective_engine
    from core.autonomy import (
        AutonomyDaemon, get_outcome_learner,
    )
    from core.autonomy.runners import meta_orchestrator_runner
    from core.autonomy.planners import (
        objective_engine_planner, learner_aware_planner,
    )

    orch = get_meta_orchestrator()
    eng = get_objective_engine()
    learner = get_outcome_learner()

    base = objective_engine_planner(eng)
    planner = learner_aware_planner(base, learner)
    daemon = AutonomyDaemon(
        objective="<top-level-goal>",
        action_runner=meta_orchestrator_runner(orch),
        planner=planner,
    )
    daemon.run_forever(max_iters=50, sleep_s=10)
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from core.autonomy.daemon import ActionPlanner, PlannedAction
from core.autonomy.learning import OutcomeLearner
from core.autonomy.stop_conditions import StopContext

log = structlog.get_logger(__name__)


def objective_engine_planner(engine: Any) -> ActionPlanner:
    """Use ObjectiveEngine.get_next_best_action() to plan the next step."""

    def plan(objective: str, _ctx: StopContext) -> Optional[PlannedAction]:
        try:
            nba = engine.get_next_best_action(goal_hint=objective)
        except Exception as exc:
            log.debug("autonomy.planner.objective_engine_failed", err=str(exc)[:120])
            return None
        if not nba or nba.get("action_type") in ("no_active_objectives", None, ""):
            return None
        action_type = nba.get("action_type", "execute")
        rationale = nba.get("rationale", objective)
        confidence = float(nba.get("confidence", 0.5))
        # Heuristic estimate : higher-confidence actions are usually shorter.
        # No real cost data here ; the runner reports actuals back.
        return PlannedAction(
            name=action_type,
            description=rationale,
            estimated_tokens=int(2000 * (1.0 - confidence) + 500),
            estimated_usd=0.0,
            payload={
                "objective_id": nba.get("objective_id"),
                "node_id": nba.get("node_id"),
                "required_tools": nba.get("required_tools", []),
                "suggested_agent": nba.get("suggested_agent"),
                "requires_human_approval": bool(nba.get("requires_human_approval", False)),
                "confidence": confidence,
            },
        )

    return plan


def learner_aware_planner(
    base: ActionPlanner,
    learner: OutcomeLearner,
    *,
    min_score: float = 0.3,
) -> ActionPlanner:
    """Wrap `base` ; downgrade actions whose historical score is below `min_score`."""

    def plan(objective: str, ctx: StopContext) -> Optional[PlannedAction]:
        action = base(objective, ctx)
        if action is None:
            return None
        score = learner.score(f"action:{action.name}")
        if score < min_score:
            log.info(
                "autonomy.planner.action_downgraded",
                action=action.name,
                score=round(score, 3),
                min_score=min_score,
            )
            # Keep the action but annotate so a downstream gate / runner
            # can decide to skip or pick an alternative.
            action.payload = {**action.payload, "downgraded": True, "score": score}
            action.description = f"[low-score:{score:.2f}] {action.description}"
        return action

    return plan


def chain_planner(*planners: ActionPlanner) -> ActionPlanner:
    """Try planners in order ; first non-None wins."""
    if not planners:
        raise ValueError("chain_planner requires at least one planner")

    def plan(objective: str, ctx: StopContext) -> Optional[PlannedAction]:
        for p in planners:
            try:
                action = p(objective, ctx)
            except Exception as exc:
                log.debug("autonomy.planner.chain_step_failed", err=str(exc)[:120])
                continue
            if action is not None:
                return action
        return None

    return plan


def static_planner(action: PlannedAction) -> ActionPlanner:
    """Test planner : always returns the same PlannedAction."""

    def plan(_objective: str, _ctx: StopContext) -> Optional[PlannedAction]:
        return action

    return plan
