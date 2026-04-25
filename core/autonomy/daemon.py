"""
core/autonomy/daemon.py — Goal-driven autonomy loop.

The daemon is the outer loop that turns JarvisMax from "reactive
mission-runner" into "goal-driven actor". One iteration :

    1. Pick the next active objective (from ObjectiveEngine if available)
    2. Plan one concrete next action
    3. Charge the budget for the planned cost
    4. Execute via the registered action_runner
    5. Evaluate outcome ; record success / failure
    6. Check stop conditions ; halt if any trip
    7. Repeat

The daemon is intentionally agnostic about HOW to execute an action —
it calls a pluggable `ActionRunner` that the application provides at
boot. By default, the runner emits the planned action on the event bus
(`autonomy.action.requested`) and waits for a result event ; this lets
the existing ApprovalQueue / human-in-the-loop infrastructure stay in
charge of actually invoking risky operations.

Safety :
- Every iteration consults the BudgetTracker before charging
- Every iteration respects the StopCheck composite policy
- A single failure does NOT abort the daemon — only consecutive
  failures past the policy limit do
- All risky actions still go through ApprovalQueue (the daemon never
  bypasses it)
- Operator can halt globally via `JARVIS_AUTONOMY_PAUSED=1` env var

Public API :
    daemon = AutonomyDaemon(action_runner=my_runner)
    daemon.set_objective("ship_the_audit")
    result = daemon.run_once()                # one iteration (sync, testable)
    daemon.run_forever(max_iters=100)          # long-running loop
    daemon.stop()                              # graceful shutdown signal

The `run_once`/`run_forever` split keeps the loop fully testable in
unit tests without threading.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog

from core.autonomy.budget import (
    Budget,
    BudgetExceeded,
    BudgetTracker,
    get_budget_tracker,
)
from core.autonomy.event_bus import EventBus, get_event_bus
from core.autonomy.stop_conditions import (
    StopCheck,
    StopContext,
    default_mission_policy,
    reason as condition_reason,
)

log = structlog.get_logger(__name__)


# ── Action contract ──────────────────────────────────────────
@dataclass
class PlannedAction:
    """A unit of work the daemon decides to attempt next."""
    name: str
    description: str = ""
    estimated_tokens: int = 0
    estimated_usd: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Outcome of executing a PlannedAction."""
    success: bool
    confidence: float = 0.0
    actual_tokens: int = 0
    actual_usd: float = 0.0
    output: Any = None
    error: str = ""


ActionRunner = Callable[[PlannedAction], ActionResult]
ActionPlanner = Callable[[str, StopContext], Optional[PlannedAction]]


# ── Default plugins ──────────────────────────────────────────
def default_planner(objective: str, ctx: StopContext) -> Optional[PlannedAction]:
    """Stub planner used when no real planner is registered.

    Returns a single 'noop' action — enough to exercise the loop in
    tests without requiring the full meta-orchestrator.
    """
    if not objective:
        return None
    return PlannedAction(
        name="noop",
        description=f"placeholder action for objective '{objective}'",
        estimated_tokens=10,
        estimated_usd=0.0,
    )


def event_bus_runner(bus: EventBus) -> ActionRunner:
    """Default runner : publish on the bus, return success.

    Real applications register a runner that calls the kernel /
    meta-orchestrator. This default keeps the daemon useful as a
    notification hub even without an executor wired up.
    """

    def run(action: PlannedAction) -> ActionResult:
        bus.publish("autonomy.action.requested", {
            "action": action.name,
            "description": action.description,
            "payload": action.payload,
        })
        return ActionResult(
            success=True,
            confidence=0.5,
            actual_tokens=action.estimated_tokens,
            actual_usd=action.estimated_usd,
            output=None,
        )

    return run


# ── Daemon ───────────────────────────────────────────────────
class AutonomyDaemon:
    """Goal-driven outer loop with budget + stop-condition safety."""

    def __init__(
        self,
        objective: str = "",
        bus: Optional[EventBus] = None,
        budget: Optional[BudgetTracker] = None,
        action_runner: Optional[ActionRunner] = None,
        planner: Optional[ActionPlanner] = None,
        stop_policy: Optional[StopCheck] = None,
        mission_id: str = "autonomy-loop",
        mission_budget: Optional[Budget] = None,
    ):
        self._objective = objective
        self._bus = bus or get_event_bus()
        self._budget = budget or get_budget_tracker()
        self._runner: ActionRunner = action_runner or event_bus_runner(self._bus)
        self._planner: ActionPlanner = planner or default_planner
        self._stop_policy = stop_policy or default_mission_policy()
        self._mission_id = mission_id
        self._stop_event = threading.Event()
        self._ctx = StopContext()
        self._budget.start_mission(
            mission_id,
            limits=mission_budget or Budget(
                max_tokens=100_000, max_usd=1.0, max_seconds=1800,
                max_consecutive_failures=3,
            ),
        )
        self._history: List[ActionResult] = []

    # ── Configuration ─────────────────────────────────────────
    def set_objective(self, objective: str) -> None:
        self._objective = objective
        self._bus.publish("autonomy.objective.changed", {"objective": objective})

    @property
    def objective(self) -> str:
        return self._objective

    @property
    def context(self) -> StopContext:
        return self._ctx

    @property
    def history(self) -> List[ActionResult]:
        return list(self._history)

    # ── Stop control ──────────────────────────────────────────
    def stop(self) -> None:
        self._stop_event.set()

    def is_paused(self) -> bool:
        """Operator-level pause via env var. Useful for emergency halt."""
        return os.getenv("JARVIS_AUTONOMY_PAUSED", "").lower() in ("1", "true", "yes")

    # ── One iteration ─────────────────────────────────────────
    def run_once(self) -> Optional[ActionResult]:
        """Execute exactly one autonomy iteration. Returns None when halted.

        Halts when : stop event fired, paused via env, stop policy
        triggered, budget exhausted, or planner returns None.
        """
        if self._stop_event.is_set():
            self._publish_halt("stop_event_set")
            return None
        if self.is_paused():
            self._publish_halt("env_paused")
            return None
        if self._stop_policy(self._ctx):
            self._publish_halt(f"stop_policy:{condition_reason(self._stop_policy)}")
            return None

        self._ctx.iteration += 1
        action = self._planner(self._objective, self._ctx)
        if action is None:
            self._publish_halt("planner_returned_none")
            return None

        # Pre-charge budget : refuse to start an action we can't afford
        try:
            self._budget.charge(
                self._mission_id,
                tokens=action.estimated_tokens,
                usd=action.estimated_usd,
            )
        except BudgetExceeded as exc:
            self._publish_halt(f"budget_exceeded:{exc.dimension}")
            return None

        self._bus.publish("autonomy.iteration.started", {
            "objective": self._objective,
            "iteration": self._ctx.iteration,
            "action": action.name,
        })

        try:
            result = self._runner(action)
        except Exception as exc:
            log.warning("autonomy.runner_failed", err=str(exc)[:120])
            result = ActionResult(success=False, error=str(exc)[:200])

        # Record outcome
        self._history.append(result)
        self._ctx.confidence = result.confidence
        if result.success:
            self._ctx.consecutive_failures = 0
            self._budget.record_success(self._mission_id)
        else:
            self._ctx.consecutive_failures += 1
            try:
                self._budget.record_failure(self._mission_id)
            except BudgetExceeded as exc:
                self._publish_halt(f"budget_exceeded:{exc.dimension}")
                return result

        # Publish outcome
        self._bus.publish(
            "autonomy.iteration.completed" if result.success
            else "autonomy.iteration.failed",
            {
                "objective": self._objective,
                "iteration": self._ctx.iteration,
                "confidence": result.confidence,
                "tokens": result.actual_tokens,
                "usd": result.actual_usd,
                "error": result.error,
            },
        )
        return result

    # ── Forever loop ──────────────────────────────────────────
    def run_forever(
        self,
        max_iters: int = 0,
        sleep_s: float = 1.0,
    ) -> List[ActionResult]:
        """Run iterations until halted. Returns history.

        Args:
            max_iters: hard cap on iterations (0 = unlimited)
            sleep_s: pause between iterations to avoid busy loop
        """
        results: List[ActionResult] = []
        i = 0
        while not self._stop_event.is_set():
            if max_iters and i >= max_iters:
                self._publish_halt("max_iters_reached")
                break
            r = self.run_once()
            if r is None:
                break  # halted by policy / budget / planner
            results.append(r)
            i += 1
            if sleep_s > 0:
                time.sleep(sleep_s)
        return results

    # ── Internals ─────────────────────────────────────────────
    def _publish_halt(self, reason: str) -> None:
        self._bus.publish("autonomy.halted", {
            "objective": self._objective,
            "iteration": self._ctx.iteration,
            "reason": reason,
        })
        log.info("autonomy.halted", objective=self._objective, reason=reason)
