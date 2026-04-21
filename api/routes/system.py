"""
JARVIS MAX — System Routes (extracted from api/main.py)
=========================================================
Health, status, metrics, diagnostics, logs, restart, mode, capabilities,
policy-mode, tools registry, knowledge, plan.

All routes preserve exact same behavior as when inline in main.py.
"""
from __future__ import annotations

import time
from typing import Any
from api._deps import require_auth

import structlog
from fastapi import Depends, APIRouter, Query

log = structlog.get_logger()
router = APIRouter()

_start_time = time.time()


# ── Lazy singletons (same pattern as main.py) ──

def _get_mission_system():
    from core.mission_system import get_mission_system
    return get_mission_system()

def _get_monitoring_agent():
    from agents.monitoring_agent import MonitoringAgent
    from config.settings import get_settings
    return MonitoringAgent(get_settings())

def _get_metrics():
    try:
        from core.metrics_store import get_metrics_store
        return get_metrics_store()
    except Exception:
        return None

def _get_task_queue():
    from core.task_queue import TaskQueue
    return TaskQueue.get()



# ═══════════════════════════════════════════════════════════════
# HEALTH / STATUS / METRICS
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v2/health")
async def health():
    """Health check complet via MonitoringAgent."""
    try:
        agent = _get_monitoring_agent()
        report = await agent.run()
        return {"ok": True, "data": report.model_dump(mode="json")}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": {"status": "unknown"}}


@router.get("/api/v2/status")
async def system_status(_user: dict = Depends(require_auth)):
    ms = _get_mission_system()
    from core.mode_system import get_mode_system
    mode_val = get_mode_system().get_mode().value
    return {"ok": True, "data": {
        "uptime_s": int(time.time() - _start_time),
        "missions": ms.stats(),
        "mode": mode_val,
        "version": "2.0.0",
    }}


@router.get("/api/v2/metrics")
async def get_metrics(_user: dict = Depends(require_auth)):
    try:
        metrics = _get_metrics()
        if metrics:
            return {"ok": True, "data": metrics.get_report()}
        ms = _get_mission_system()
        return {"ok": True, "data": {"missions": ms.stats()}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/api/v2/diagnostics")
async def diagnostics(_user: dict = Depends(require_auth)):
    diag: dict[str, Any] = {}
    try:
        queue = _get_task_queue()
        diag["task_queue"] = queue.stats()
    except Exception as e:
        diag["task_queue"] = {"error": str(e)}
    try:
        ms = _get_mission_system()
        diag["missions"] = ms.stats()
    except Exception as e:
        diag["missions"] = {"error": str(e)}
    try:
        from core.system_state import SystemState
        from config.settings import get_settings
        ss = SystemState(get_settings())
        diag["modules"] = ss.get_report()
    except Exception as e:
        diag["modules"] = {"error": str(e)}
    return {"ok": True, "data": diag}


@router.get("/api/v2/logs")
async def get_logs(
    n: int = Query(50, ge=1, le=500),
    _user: dict = Depends(require_auth),
):
    try:
        from config.settings import get_settings
        from executor.runner import ActionExecutor
        ex = ActionExecutor(get_settings())
        logs = await ex.tail_logs(n)
        return {"ok": True, "data": {"logs": logs, "count": len(logs)}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/api/v2/restart")
async def restart(_user: dict = Depends(require_auth)):
    try:
        from core.mode_system import get_mode_system
        ms = get_mode_system()
        ms.reset()
        log.info("system_restart_signal")
        return {"ok": True, "message": "Restart signal sent"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# NOTE: System mode, policy-mode, capabilities, tools/registry, tools/test,
# tools/rollback, knowledge/recent, plan/last, metrics/recent remain inline in
# api/main.py — they use different internal modules and will be extracted in a
# future consolidation pass when implementations are unified.
