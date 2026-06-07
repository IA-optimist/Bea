"""
api/routes/autonomy.py — REST control plane for the autonomy daemon.

Endpoints under /api/v3/autonomy :

    POST   /start       — start a daemon for a given objective
    POST   /stop        — graceful stop signal (idempotent)
    GET    /status      — current state + budget + recent events
    GET    /decisions   — list pending multi-choice decisions
    POST   /decisions/{id}/answer — answer a decision

Auth : every endpoint goes through `require_auth`.

Lifecycle :

- Only ONE daemon thread runs per process at a time. Calling /start
  while one is active returns 409 Conflict unless `force=true`.
- /stop sets the stop event ; the loop exits at the next iteration
  boundary. Returns the snapshot of what ran.
- /status is read-only and cheap.

The daemon runs in a background thread (not asyncio task) because
its `run_forever` is sync ; the thread daemonizes so it dies with
the process.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api._deps import require_auth
from core.autonomy import (
    ActionPlanner,
    ActionRunner,
    AutonomyDaemon,
    Budget,
    chain_planner,
    get_budget_tracker,
    get_event_bus,
    get_multi_choice_store,
    get_outcome_learner,
    learner_aware_planner,
    objective_engine_planner,
    reset_budget_tracker,
)
from core.autonomy.daemon import default_planner, event_bus_runner
from core.autonomy.runners import composite_runner, meta_orchestrator_runner
from core.autonomy.stop_conditions import default_mission_policy

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v3/autonomy",
    tags=["autonomy"],
    dependencies=[Depends(require_auth)],
)


# ── Process-wide daemon state ───────────────────────────────
_daemon_lock = threading.Lock()
_daemon: Optional[AutonomyDaemon] = None
_daemon_thread: Optional[threading.Thread] = None
_daemon_meta: Dict[str, Any] = {}


# ── Runner / planner factories ──────────────────────────────
# By default the daemon uses safe stubs (event_bus_runner +
# default_planner). Setting BEA_AUTONOMY_USE_REAL=1 swaps in the
# real MetaOrchestrator runner + ObjectiveEngine-aware planner with
# learner downgrade. Operators flip this flag in pre-prod first ; CI
# stays on the safe defaults so tests don't accidentally execute
# real missions.
def _build_runner_and_planner() -> tuple[ActionRunner, ActionPlanner]:
    use_real = os.getenv("BEA_AUTONOMY_USE_REAL", "0").lower() in ("1", "true", "yes")
    if not use_real:
        return event_bus_runner(get_event_bus()), default_planner

    # Lazy imports : avoid pulling MetaOrchestrator at module load
    # time (keeps the api/main.py startup fast even when autonomy
    # is disabled).
    try:
        from core.meta_orchestrator import get_meta_orchestrator
        orchestrator = get_meta_orchestrator()
    except Exception as exc:
        log.warning("autonomy.real_runner_unavailable", err=str(exc)[:160])
        return event_bus_runner(get_event_bus()), default_planner

    real_runner = meta_orchestrator_runner(orchestrator)
    safe_runner = event_bus_runner(get_event_bus())
    runner = composite_runner(real_runner, safe_runner)

    planner: ActionPlanner = default_planner
    try:
        from core.objectives.objective_engine import get_objective_engine
        engine = get_objective_engine()
        learner = get_outcome_learner()
        planner = chain_planner(
            learner_aware_planner(objective_engine_planner(engine), learner),
            default_planner,
        )
    except Exception as exc:
        log.debug("autonomy.objective_planner_unavailable", err=str(exc)[:120])

    log.info("autonomy.real_runner_active",
             objective_engine=("yes" if planner is not default_planner else "no"))
    return runner, planner


# ── Schemas ──────────────────────────────────────────────────
class StartRequest(BaseModel):
    objective: str = Field(..., min_length=1, max_length=2000)
    max_iters: int = Field(default=20, ge=1, le=10_000)
    sleep_s: float = Field(default=10.0, ge=0.0, le=3600.0)
    max_seconds: float = Field(default=1800.0, ge=10.0, le=86_400.0)
    max_tokens: int = Field(default=100_000, ge=100, le=10_000_000)
    max_usd: float = Field(default=1.0, ge=0.0, le=100.0)
    force: bool = Field(default=False, description="Replace any running daemon")


class StopRequest(BaseModel):
    reason: str = Field(default="user_requested", max_length=300)


class AnswerRequest(BaseModel):
    selected_index: int = Field(..., ge=0, le=99)


# ── Endpoints ────────────────────────────────────────────────
@router.post("/start")
async def start_daemon(req: StartRequest) -> Dict[str, Any]:
    """Spawn a daemon thread for the given objective.

    Returns 409 if one is already running and force=False.
    """
    global _daemon, _daemon_thread, _daemon_meta

    with _daemon_lock:
        running = _daemon_thread is not None and _daemon_thread.is_alive()
        if running and not req.force:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "daemon_already_running",
                    "objective": _daemon_meta.get("objective"),
                    "started_at": _daemon_meta.get("started_at"),
                },
            )
        if running:
            log.info("autonomy.api.replacing_running_daemon")
            if _daemon is not None:
                _daemon.stop()
            _daemon_thread.join(timeout=5.0)

        # Reset budget tracker so the new mission starts clean
        reset_budget_tracker()

        mission_id = f"autonomy-{int(time.time())}"
        budget = Budget(
            max_tokens=req.max_tokens,
            max_usd=req.max_usd,
            max_seconds=req.max_seconds,
            max_consecutive_failures=3,
        )
        policy = default_mission_policy(
            max_seconds=req.max_seconds,
            max_iterations=req.max_iters,
        )
        runner, planner = _build_runner_and_planner()
        use_real = os.getenv("BEA_AUTONOMY_USE_REAL", "0").lower() in ("1", "true", "yes")
        _daemon = AutonomyDaemon(
            objective=req.objective,
            mission_id=mission_id,
            mission_budget=budget,
            stop_policy=policy,
            planner=planner,
            action_runner=runner,
        )

        def _run():
            try:
                _daemon.run_forever(max_iters=req.max_iters, sleep_s=req.sleep_s)
            except Exception as exc:
                log.warning("autonomy.api.thread_crashed", err=str(exc)[:200])

        _daemon_thread = threading.Thread(target=_run, daemon=True, name="autonomy-daemon")
        _daemon_meta = {
            "objective": req.objective,
            "mission_id": mission_id,
            "started_at": time.time(),
            "max_iters": req.max_iters,
            "max_seconds": req.max_seconds,
            "mode": "real" if use_real else "safe",
        }
        _daemon_thread.start()
        return {"status": "started", **_daemon_meta}


@router.post("/stop")
async def stop_daemon(req: StopRequest) -> Dict[str, Any]:
    """Send a graceful stop ; wait up to 10 s for the loop to exit."""
    global _daemon, _daemon_thread

    with _daemon_lock:
        if _daemon is None or _daemon_thread is None or not _daemon_thread.is_alive():
            return {"status": "not_running"}

        _daemon.stop()
        # Capture snapshot before joining
        meta = dict(_daemon_meta)
        history = _daemon.history

    _daemon_thread.join(timeout=10.0)
    still_alive = _daemon_thread.is_alive()

    return {
        "status": "stopped" if not still_alive else "stop_signal_sent",
        "reason": req.reason,
        "iterations": len(history),
        "successes": sum(1 for r in history if r.success),
        "failures": sum(1 for r in history if not r.success),
        "objective": meta.get("objective"),
    }


@router.get("/status")
async def status_daemon() -> Dict[str, Any]:
    """Read-only snapshot of daemon + budget + recent bus events."""
    with _daemon_lock:
        running = _daemon_thread is not None and _daemon_thread.is_alive()
        meta = dict(_daemon_meta) if running else {}
        history = list(_daemon.history) if (running and _daemon) else []
        confidence = _daemon.context.confidence if (running and _daemon) else None
        iteration = _daemon.context.iteration if (running and _daemon) else 0

    bus = get_event_bus()
    recent = [
        {"topic": e.topic, "ts": e.ts, "payload_keys": sorted(e.payload.keys())}
        for e in bus.replay("autonomy.*", limit=20)
    ]

    return {
        "running": running,
        "objective": meta.get("objective"),
        "mission_id": meta.get("mission_id"),
        "started_at": meta.get("started_at"),
        "iteration": iteration,
        "confidence": confidence,
        "history_count": len(history),
        "successes": sum(1 for r in history if r.success),
        "failures": sum(1 for r in history if not r.success),
        "budget": get_budget_tracker().snapshot(),
        "event_bus_stats": bus.stats(),
        "recent_events": recent,
    }


@router.get("/decisions")
async def list_decisions() -> List[Dict[str, Any]]:
    """List pending multi-choice decisions."""
    return [d.to_dict() for d in get_multi_choice_store().pending()]


@router.post("/decisions/{decision_id}/answer")
async def answer_decision(decision_id: str, req: AnswerRequest) -> Dict[str, Any]:
    """Operator answers a multi-choice decision."""
    store = get_multi_choice_store()
    try:
        result = store.answer(decision_id, req.selected_index, answered_by="api_user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="decision_not_found_or_resolved")
    return result.to_dict()
