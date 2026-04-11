"""
JARVIS MAX — Phase 9 Mission Control Router
Real-time mission visibility and control endpoints.

Routes:
  GET  /api/v1/missions                        — list missions
  GET  /api/v1/missions/{id}/log               — mission log events
  GET  /api/v1/system/status                   — system status
  POST /api/v1/missions/{id}/approve           — approve mission
  POST /api/v1/missions/{id}/reject            — reject mission
  POST /api/v1/missions/{id}/pause             — pause mission
  POST /api/v1/missions/{id}/resume            — resume mission
  POST /api/v1/missions/{id}/cancel            — cancel mission
  GET  /api/v1/missions/{id}/stream            — SSE stream
  GET  /api/v1/missions/{id}/summary           — mission summary
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.schemas import ok, error as err_resp
from api._deps import _check_auth
from typing import Optional as _Opt
_silent_log = __import__("structlog").get_logger(__name__)


def _auth(x_jarvis_token: _Opt[str] = Header(None), authorization: _Opt[str] = Header(None)):
    """Auth dependency for mission control routes."""
    _check_auth(x_jarvis_token, authorization)

# ── Canonical status bridge (P4) ─────────────────────────────────────────────

def _canonical_status(legacy_status: str, source: str = "mission_system") -> str:
    """Map legacy status to canonical. Fail-open: returns legacy if mapping fails."""
    try:
        from core.canonical_types import map_legacy_mission_status
        return map_legacy_mission_status(legacy_status, source).value
    except Exception:
        return str(legacy_status)


def _canonical_risk(legacy_risk: str, source: str = "state") -> str:
    """Map legacy risk to canonical. Fail-open."""
    try:
        from core.canonical_types import map_legacy_risk_level
        return map_legacy_risk_level(legacy_risk, source).value
    except Exception:
        return str(legacy_risk)


router = APIRouter(prefix="/api/v1", tags=["mission-control"], dependencies=[Depends(_auth)])

_start_time = time.time()
_WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "workspace"))

# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health_v1():
    """Phase 9 health check — no auth required."""
    return JSONResponse({
        "status": "ok",
        "version": "2.0",
        "phase": 9,
        "uptime_s": int(time.time() - _start_time),
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mission_system():
    from core.mission_system import get_mission_system
    return get_mission_system()


def _store():
    from api.mission_store import MissionStateStore
    return MissionStateStore.get()


def _log_user_action(mission_id: str, action: str) -> None:
    from api.models import MissionLogEvent, LogEventType
    event = MissionLogEvent(
        mission_id=mission_id,
        event_type=LogEventType.USER_ACTION,
        message=f"User action: {action}",
        data={"action": action},
    )
    _store().append_log(event)


# ── 3a — Mission list ─────────────────────────────────────────────────────────

@router.get("/missions")
async def list_missions_v1(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
):
    try:
        ms = _mission_system()
        missions_raw = ms.list_missions(status=status, limit=limit)
        store = _store()
        missions = []
        for m in missions_raw:
            logs = store.get_log(m.mission_id)
            tool_names = list({e.tool_name for e in logs if e.tool_name})
            agent_ids  = list({e.agent_id for e in logs if e.agent_id})
            raw_risk = m.plan_risk.lower() if hasattr(m, "plan_risk") else "low"
            canonical_st = _canonical_status(str(m.status))
            requires_approval = canonical_st in {"WAITING_APPROVAL", "READY"}
            missions.append({
                "mission_id":         m.mission_id,
                "status":             canonical_st,
                "legacy_status":      str(m.status),
                "progress":           _estimate_progress(m),
                "agents_involved":    agent_ids,
                "tools_used":         tool_names,
                "risk_level":         _canonical_risk(raw_risk),
                "requires_approval":  requires_approval,
                "start_time":         m.created_at,
                "estimated_completion": m.created_at + 60,
            })
        return JSONResponse(ok({"missions": missions, "total": len(missions)}))
    except Exception as e:
        return JSONResponse(err_resp(str(e)), status_code=500)


def _estimate_progress(mission) -> float:
    """Estimate mission progress from canonical status."""
    # Canonical progress map (canonical_types.CanonicalMissionStatus)
    canonical_progress = {
        "CREATED":          0.0,
        "QUEUED":           0.05,
        "PLANNING":         0.1,
        "WAITING_APPROVAL": 0.2,
        "READY":            0.3,
        "RUNNING":          0.6,
        "REVIEW":           0.8,
        "COMPLETED":        1.0,
        "FAILED":           0.0,
        "CANCELLED":        0.0,
    }
    # Legacy fallback map
    legacy_progress = {
        "ANALYZING":          0.1,
        "PENDING_VALIDATION": 0.2,
        "APPROVED":           0.3,
        "EXECUTING":          0.6,
        "DONE":               1.0,
        "REJECTED":           0.0,
        "BLOCKED":            0.0,
        "PLAN_ONLY":          1.0,
    }
    raw = str(mission.status)
    canonical = _canonical_status(raw)
    return canonical_progress.get(canonical, legacy_progress.get(raw, 0.0))


# ── 3b — Mission log ──────────────────────────────────────────────────────────

@router.get("/missions/{mission_id}/log")
async def get_mission_log(
    mission_id: str,
    limit: int = Query(50, ge=1, le=500),
):
    ms = _mission_system()
    mission = ms.get(mission_id)
    if not mission:
        return JSONResponse(err_resp(f"Mission '{mission_id}' not found"), status_code=404)

    store = _store()
    events = store.get_log(mission_id)
    events_sorted = sorted(events, key=lambda e: e.timestamp)[-limit:]
    return JSONResponse(ok({
        "mission_id": mission_id,
        "events": [e.to_dict() for e in events_sorted],
        "total": len(events_sorted),
    }))


# ── 3c — System status ────────────────────────────────────────────────────────

@router.get("/system/status")
async def system_status_v1():
    try:
        ms = _mission_system()
        stats = ms.stats()
        running = stats.get("by_status", {}).get("EXECUTING", 0)

        # Canonical status distribution
        canonical_by_status: dict[str, int] = {}
        for raw_s, count in stats.get("by_status", {}).items():
            cs = _canonical_status(str(raw_s))
            canonical_by_status[cs] = canonical_by_status.get(cs, 0) + count

        # Active agents from running mission logs
        store = _store()
        all_missions = ms.list_missions(limit=200)
        running_missions = [m for m in all_missions
                           if _canonical_status(str(m.status)) == "RUNNING"]
        active_agents: list[str] = []
        for m in running_missions:
            logs = store.get_log(m.mission_id)
            active_agents.extend(e.agent_id for e in logs if e.agent_id)
        active_agents = list(set(active_agents))

        # Memory usage (fail-open)
        memory_usage: dict = {"working": 0, "episodic": 0}
        try:
            from memory.memory_bus import MemoryBus
            from config.settings import get_settings
            bus = MemoryBus(get_settings())
            if bus.store:
                count = getattr(bus.store, "count", None)
                if callable(count):
                    memory_usage["episodic"] = count()
        except Exception:
            _silent_log.debug("suppressed_exception", src='mission_control.py')

        # Tool performance (fail-open)
        tool_performance: dict = {}
        try:
            from tools.performance import ToolPerformanceTracker
            tracker = ToolPerformanceTracker.get()
            tool_performance = tracker.summary() if hasattr(tracker, "summary") else {}
        except Exception:
            _silent_log.debug("suppressed_exception", src='mission_control.py')

        # Queue length (fail-open)
        queue_length = 0
        try:
            from core.action_queue import get_action_queue
            aq = get_action_queue()
            queue_length = len([a for a in aq._actions.values()
                                 if getattr(a, "status", "") == "PENDING"])
        except Exception:
            _silent_log.debug("suppressed_exception", src='mission_control.py')

        # Memory facade health (fail-open, P5)
        memory_health: dict = {}
        try:
            from core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            memory_health = facade.health()
        except Exception:
            _silent_log.debug("suppressed_exception", src='mission_control.py')

        return JSONResponse(ok({
            "active_agents":        active_agents,
            "memory_usage":         memory_usage,
            "memory_health":        memory_health,
            "tool_performance":     tool_performance,
            "queue_length":         queue_length,
            "running_missions":     running,
            "canonical_by_status":  canonical_by_status,
            "uptime_s":             int(time.time() - _start_time),
            "version":              "2.0",
            "phase":                9,
        }))
    except Exception as e:
        return JSONResponse(err_resp(str(e)), status_code=500)


# ── 3d — Approval control ────────────────────────────────────────────────────

def _apply_mission_action(mission_id: str, action: str) -> tuple[dict | None, str]:
    ms = _mission_system()
    mission = ms.get(mission_id)
    if not mission:
        return None, f"Mission '{mission_id}' not found"

    if action == "approve":
        result = ms.approve(mission_id)
    elif action == "reject":
        result = ms.reject(mission_id, note="Rejected via API")
    elif action == "cancel":
        result = ms.reject(mission_id, note="Cancelled via API")
        if result is None:
            result = mission
    elif action in ("pause", "resume"):
        result = mission
    else:
        return None, f"Unknown action: {action}"

    _log_user_action(mission_id, action)
    if result is None:
        result = ms.get(mission_id) or mission
    _cs = _canonical_status(str(result.status))
    return {"mission_id": mission_id, "action": action, "status": _cs, "legacy_status": str(result.status)}, ""


@router.post("/missions/{mission_id}/approve")
async def approve_mission(mission_id: str):
    data, err = _apply_mission_action(mission_id, "approve")
    if err:
        return JSONResponse(err_resp(err), status_code=404)
    return JSONResponse(ok(data))


@router.post("/missions/{mission_id}/reject")
async def reject_mission(mission_id: str):
    data, err = _apply_mission_action(mission_id, "reject")
    if err:
        return JSONResponse(err_resp(err), status_code=404)
    return JSONResponse(ok(data))


@router.post("/missions/{mission_id}/pause")
async def pause_mission(mission_id: str):
    data, err = _apply_mission_action(mission_id, "pause")
    if err:
        return JSONResponse(err_resp(err), status_code=404)
    return JSONResponse(ok(data))


@router.post("/missions/{mission_id}/resume")
async def resume_mission(mission_id: str):
    data, err = _apply_mission_action(mission_id, "resume")
    if err:
        return JSONResponse(err_resp(err), status_code=404)
    return JSONResponse(ok(data))


@router.post("/missions/{mission_id}/cancel")
async def cancel_mission(mission_id: str):
    data, err = _apply_mission_action(mission_id, "cancel")
    if err:
        return JSONResponse(err_resp(err), status_code=404)
    return JSONResponse(ok(data))


# ── 3e — SSE Streaming ────────────────────────────────────────────────────────

# Canonical terminal statuses + legacy for backward compatibility
_TERMINAL_STATUSES = {
    "COMPLETED", "FAILED", "CANCELLED",           # canonical
    "DONE", "REJECTED", "BLOCKED", "PLAN_ONLY",   # legacy
}


async def _sse_generator(mission_id: str) -> AsyncGenerator[str, None]:
    ms = _mission_system()
    store = _store()

    # Check mission exists — with workspace/missions.json fallback
    mission = ms.get(mission_id)
    if not mission:
        # Fallback: check workspace/missions.json
        try:
            mpath = _WORKSPACE_DIR / "missions.json"
            if mpath.exists():
                raw_data = json.loads(mpath.read_text("utf-8"))
                missions_list = raw_data if isinstance(raw_data, list) else raw_data.get("missions", [])
                for m in missions_list:
                    mid = m.get("task_id") or m.get("mission_id") or m.get("id", "")
                    if mid == mission_id:
                        ws_status = str(m.get("status", "UNKNOWN")).upper()
                        yield f"data: {json.dumps({'event': 'status', 'mission_id': mission_id, 'status': ws_status, 'source': 'workspace', 'ts': time.time()})}\n\n"
                        if ws_status in _TERMINAL_STATUSES:
                            yield f"data: {json.dumps({'event': 'done', 'mission_id': mission_id, 'status': ws_status})}\n\n"
                        else:
                            yield f"data: {json.dumps({'event': 'timeout', 'mission_id': mission_id, 'message': 'Mission found in workspace store'})}\n\n"
                        return
        except Exception:
            _silent_log.debug("suppressed_exception", src='mission_control.py')
        yield f"data: {json.dumps({'event': 'error', 'message': 'not found'})}\n\n"
        return

    last_event_count = 0
    deadline = time.time() + 120  # 120s timeout

    while time.time() < deadline:
        mission = ms.get(mission_id)
        if not mission:
            break

        # Send status event (canonical + legacy)
        _cs = _canonical_status(str(mission.status))
        yield f"data: {json.dumps({'event': 'status', 'mission_id': mission_id, 'status': _cs, 'legacy_status': str(mission.status), 'ts': time.time()})}\n\n"

        # Send new log events from MissionStateStore
        events = store.get_log(mission_id)
        new_events = events[last_event_count:]
        for e in new_events:
            yield f"data: {json.dumps({'event': 'log', 'type': e.event_type.value if hasattr(e.event_type, 'value') else str(e.event_type), 'message': e.message, 'ts': e.timestamp})}\n\n"
        last_event_count = len(events)

        # Fallback: also poll workspace/missions.json for extra status info
        if last_event_count == 0:
            try:
                mpath = _WORKSPACE_DIR / "missions.json"
                if mpath.exists():
                    raw_data = json.loads(mpath.read_text("utf-8"))
                    missions_list = raw_data if isinstance(raw_data, list) else raw_data.get("missions", [])
                    for m in missions_list:
                        mid = m.get("task_id") or m.get("mission_id") or m.get("id", "")
                        if mid == mission_id:
                            ws_status = str(m.get("status", "")).upper()
                            if ws_status and ws_status != str(mission.status).upper():
                                yield f"data: {json.dumps({'event': 'status', 'mission_id': mission_id, 'status': ws_status, 'source': 'workspace', 'ts': time.time()})}\n\n"
                            break
            except Exception:
                _silent_log.debug("suppressed_exception", src='mission_control.py')

        # Stop on terminal status
        if _cs in _TERMINAL_STATUSES or str(mission.status).upper() in _TERMINAL_STATUSES:
            yield f"data: {json.dumps({'event': 'done', 'mission_id': mission_id, 'status': _cs, 'legacy_status': str(mission.status)})}\n\n"
            return

        await asyncio.sleep(0.5)

    # Timeout
    yield f"data: {json.dumps({'event': 'timeout', 'mission_id': mission_id})}\n\n"


@router.get("/missions/{mission_id}/stream")
async def stream_mission(mission_id: str):
    return StreamingResponse(
        _sse_generator(mission_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── 3g — Create & run mission (v1 compat for Android) ───────────────────────


class RunMissionRequest:
    """Validated mission run request."""
    def __init__(self, goal: str = "", priority: str = "normal",
                 max_steps: int = 10, risk_tolerance: str = "low", **kwargs):
        if not goal or not isinstance(goal, str):
            raise ValueError("goal is required and must be a string")
        if len(goal) > 10000:
            raise ValueError("goal exceeds 10000 characters")
        if priority not in ("low", "normal", "high", "critical"):
            raise ValueError("priority must be low/normal/high/critical")
        self.goal = goal.strip()
        self.priority = priority
        self.max_steps = max(1, min(100, int(max_steps or 10)))
        self.risk_tolerance = risk_tolerance

@router.post("/mission/run")
async def run_mission_v1(body: dict = Body(...)):
    """
    Phase 9 v1 mission creation endpoint — Android compatibility.
    Accepts {goal, priority, max_steps, risk_tolerance} and maps to MissionSystem.submit().
    """
    try:
        try:
            req = RunMissionRequest(**body)
            goal = req.goal
        except (ValueError, TypeError) as _ve:
            return JSONResponse({"status": "error", "message": str(_ve)}, status_code=422)
        goal = goal or body.get("input", "")
        if not goal:
            return JSONResponse({"status": "error", "message": "goal is required"}, status_code=400)
        ms = _mission_system()
        result = ms.submit(goal)
        _cs = _canonical_status(str(result.status))
        return JSONResponse({"status": "ok", "data": {
            "mission_id": result.mission_id,
            "status":     _cs,
            "legacy_status": str(result.status),
            "goal":       goal,
            "agents_involved":   [],
            "tools_used":        [],
            "risk_level":        "write_low",
            "requires_approval": _cs == "WAITING_APPROVAL",
            "progress":          0.0,
            "start_time":        result.created_at,
        }})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ── 3f — Mission summary ──────────────────────────────────────────────────────

@router.get("/missions/{mission_id}/summary")
async def get_mission_summary(mission_id: str):
    store = _store()
    summary = store.get_summary(mission_id)
    if not summary:
        ms = _mission_system()
        mission = ms.get(mission_id)
        if not mission:
            return JSONResponse(err_resp(f"Mission '{mission_id}' not found"), status_code=404)
        return JSONResponse(err_resp(f"No summary available for mission '{mission_id}'"), status_code=404)
    return JSONResponse(ok(summary.to_dict()))
