"""
core/autonomy/runners.py — Action runners that bridge to existing executors.

A `runner` takes a `PlannedAction` and turns it into real work. The
default `event_bus_runner` (in daemon.py) only publishes on the bus.
Real runners delegate to MetaOrchestrator, kernel, or any custom
executor — and translate their output back into an `ActionResult`.

Two concrete runners shipped here :

1. `meta_orchestrator_runner(orchestrator)` — calls
   `MetaOrchestrator.run_mission(goal=..., mode=...)`. Maps the
   resulting MissionContext to ActionResult.

2. `composite_runner(*runners)` — tries runners in order, returns the
   first that returns success=True. Useful when you want
   meta_orchestrator with an event-bus fallback.

The runners are pure adapters : no orchestration logic, no extra
side effects. Approval still flows through ApprovalQueue (which the
orchestrator itself consults).
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from core.autonomy.daemon import ActionResult, ActionRunner, PlannedAction

log = structlog.get_logger(__name__)


def meta_orchestrator_runner(orchestrator: Any, *, default_mode: str = "auto") -> ActionRunner:
    """Build a runner that delegates to MetaOrchestrator.run_mission().

    Args:
        orchestrator: instance of `core.meta_orchestrator.MetaOrchestrator`
                      (already booted)
        default_mode: passed to run_mission when payload doesn't override

    The PlannedAction is mapped as :
      - description → goal
      - payload['mode'] → mode (else default_mode)
      - payload['mission_id'] → mission_id (else generated)
      - payload['project_id'] → project_id

    The returned ActionResult carries :
      - success         : ctx.status not in {FAILED, CANCELLED}
      - confidence      : ctx.metadata.get("confidence_score", 0.5)
      - actual_tokens/usd : 0 by default (orchestrator doesn't track per-call cost)
      - output          : ctx.result (string) — the mission output
      - error           : ctx.error
    """

    def run(action: PlannedAction) -> ActionResult:
        goal = action.description or action.name
        mode = action.payload.get("mode", default_mode)
        mid = action.payload.get("mission_id")
        pid = action.payload.get("project_id")
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None:
                # Already in a loop — sync runner can't await safely. Caller
                # must invoke from a thread or use an async variant.
                raise RuntimeError(
                    "meta_orchestrator_runner invoked from inside an event loop "
                    "(call from a worker thread or build an async runner)"
                )
            ctx = asyncio.run(
                orchestrator.run_mission(
                    goal=goal, mode=mode, mission_id=mid, project_id=pid,
                )
            )
        except Exception as exc:
            log.warning("autonomy.runner.meta_orch_failed", err=str(exc)[:160])
            return ActionResult(success=False, error=str(exc)[:200])

        status_str = str(getattr(ctx, "status", "")).upper()
        success = status_str not in ("FAILED", "CANCELLED", "REJECTED")
        confidence = float((getattr(ctx, "metadata", {}) or {}).get("confidence_score", 0.5))
        return ActionResult(
            success=success,
            confidence=confidence,
            actual_tokens=int((getattr(ctx, "metadata", {}) or {}).get("tokens_used", 0)),
            actual_usd=float((getattr(ctx, "metadata", {}) or {}).get("cost_usd", 0.0)),
            output=getattr(ctx, "result", None) or getattr(ctx, "final_output", None),
            error=str(getattr(ctx, "error", "") or ""),
        )

    return run


def composite_runner(*runners: ActionRunner) -> ActionRunner:
    """Try runners in order ; first success wins. Records last error on full miss."""
    if not runners:
        raise ValueError("composite_runner requires at least one runner")

    def run(action: PlannedAction) -> ActionResult:
        last_err = ""
        for r in runners:
            try:
                result = r(action)
            except Exception as exc:
                last_err = str(exc)[:200]
                continue
            if result.success:
                return result
            last_err = result.error or last_err
        return ActionResult(success=False, error=last_err or "all_runners_failed")

    return run


def static_response_runner(success: bool = True, output: Any = None) -> ActionRunner:
    """Test runner : always returns the same canned ActionResult.

    Handy for unit-testing the daemon without booting MetaOrchestrator.
    """

    def run(_action: PlannedAction) -> ActionResult:
        return ActionResult(success=success, confidence=1.0 if success else 0.0, output=output)

    return run
