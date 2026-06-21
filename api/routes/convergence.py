"""
BEA MAX — Convergence API Router
======================================
Provides /api/v3/ endpoints that route through the OrchestrationBridge
to MetaOrchestrator (canonical authority) when BEA_USE_CANONICAL_ORCHESTRATOR=1.

Falls back to MissionSystem transparently when flag is OFF.

This router sits ALONGSIDE existing mission_control.py routes.
No existing routes modified. Clients can migrate to /api/v3/ at their own pace.

Endpoints:
    POST /api/v3/missions           — submit mission (bridge → canonical)
    GET  /api/v3/missions           — list missions (merged sources)
    GET  /api/v3/missions/{id}      — get mission (canonical status)
    POST /api/v3/missions/{id}/approve  — approve mission
    POST /api/v3/missions/{id}/reject   — reject mission
    GET  /api/v3/system/status      — unified system status
    GET  /api/v3/system/health      — deep health check
    GET  /api/v3/approvals/pending  — approval queue
    GET  /api/v3/agents/status      — agent registry status
    WS   /ws/stream                 — unified event stream
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import os
import time
from typing import Optional
from api._deps import require_auth

try:
    from fastapi import BackgroundTasks, Depends, APIRouter, Body, HTTPException, WebSocket, WebSocketDisconnect  # noqa: F401
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError:
    # Stub for syntax validation without fastapi
    class _Stub:
        def get(self, *a, **k):
            def dec(f): return f
            return dec
        def post(self, *a, **k):
            def dec(f): return f
            return dec
        def websocket(self, *a, **k):
            def dec(f): return f
            return dec
    APIRouter = _Stub
    def Body(**k):
        return None
    WebSocket = object
    WebSocketDisconnect = Exception
    JSONResponse = dict

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    log = structlog.get_logger(__name__)



router = APIRouter(prefix="/api/v3", tags=["convergence"], dependencies=[Depends(require_auth)])


def _use_canonical() -> bool:
    # Default TRUE — v3 API always uses the canonical orchestrator bridge.
    # Set BEA_USE_CANONICAL_ORCHESTRATOR=0 to fall back to legacy MissionSystem.
    val = os.environ.get("BEA_USE_CANONICAL_ORCHESTRATOR", "1").lower()
    return val not in ("0", "false", "no")


def _ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data}, status_code=status)


def _err(msg: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


# ═══════════════════════════════════════════════════════════════
# MISSION ENDPOINTS
# ═══════════════════════════════════════════════════════════════



@router.post("/missions")
async def submit_mission(body: dict = Body(...), background_tasks: BackgroundTasks = None):
    """
    Submit a new mission.

    When canonical orchestrator enabled:
      → OrchestrationBridge.submit() → MetaOrchestrator (background execution)
    When disabled:
      → MissionSystem.submit() (legacy)
    """
    try:
        goal = str(body.get("goal") or body.get("input", "")).strip()
        if not goal:
            return _err("Field 'goal' is required.")

        if _use_canonical():
            try:
                from core.orchestration_bridge import submit_mission as bridge_submit
                result = bridge_submit(goal)
                mission_id = result.get("mission_id")
                # Track submission in metrics store (admin panel counters)
                if result.get("ok"):
                    try:
                        from core.metrics_store import emit_mission_submitted
                        emit_mission_submitted("canonical")
                    except Exception as _exc:
                        log.warning("swallowed_exception", action="mission_submitted_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                # Trigger real execution in background — without this, mission stays READY forever
                if background_tasks and mission_id and result.get("ok"):
                    _goal_capture = goal
                    _mid_capture = mission_id
                    _ctx_capture = str(body.get("context", "") or "")
                    _risk_capture = str(body.get("risk_level", "low") or "low")
                    _requires_capture = bool(body.get("requires_validation", False))
                    _mode_capture = str(body.get("mode", "auto") or "auto")
                    async def _execute_canonical():
                        try:
                            from core.meta_orchestrator import get_meta_orchestrator
                            mo = get_meta_orchestrator()

                            # Tag mission as requiring validation in mission store
                            if _requires_capture:
                                try:
                                    from core.mission_system import get_mission_system
                                    _ms_inner = get_mission_system()
                                    _m = _ms_inner.get(_mid_capture)
                                    if _m:
                                        _m.decision_trace["requires_validation"] = True
                                        _m.decision_trace["requested_risk_level"] = _risk_capture
                                        log.info("mission.validation_flagged", mission_id=_mid_capture)
                                except Exception as _exc:
                                    log.debug("validation_flag_suppressed", exc_type=type(_exc).__name__)

                            import asyncio as _asyncio
                            await _asyncio.wait_for(
                                mo.run_mission(_goal_capture, mission_id=_mid_capture, mode=_mode_capture),
                                timeout=660.0,  # 11 min safety net — inner timeout is 600s
                            )
                        except _asyncio.TimeoutError:
                            log.warning("canonical_execution_timeout", mission_id=_mid_capture)
                        except Exception as _exc:
                            import traceback
                            log.warning("canonical_execution_failed", mission_id=_mid_capture, err=str(_exc)[:120], tb=traceback.format_exc()[-300:])
                    background_tasks.add_task(_execute_canonical)
                return _ok(result, status=201)
            except Exception as e:
                log.warning("canonical_submit_fallback", err=str(e)[:80])
                # Fall through to legacy

        # Legacy path
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.submit(goal)
        data = result.to_dict()

        # Intelligence hooks
        try:
            from core.intelligence_hooks import post_mission_submit
            enrichment = post_mission_submit(data.get("mission_id", ""), goal)
            if enrichment:
                data["intelligence"] = enrichment
        except Exception as _exc:
            log.warning("swallowed_exception", action="intelligence_enrichment", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return _ok(data, status=201)

    except Exception as e:
        log.warning("submit_mission_err", err=str(e)[:80])
        return _err(str(e)[:200], status=500)


@router.get("/missions")
async def list_missions(
    status: Optional[str] = None,
    limit: int = 20
):
    """List missions with canonical status mapping."""
    try:
        if _use_canonical():
            try:
                from core.orchestration_bridge import get_orchestration_bridge
                bridge = get_orchestration_bridge()
                missions = bridge.list_missions(status_filter=status, limit=limit)
                return _ok({"missions": missions, "source": "bridge"})
            except Exception as e:
                log.warning("canonical_list_fallback", err=str(e)[:80])

        from core.mission_system import get_mission_system
        ms = get_mission_system()
        missions = ms.list_missions(status=status, limit=limit)
        return _ok({
            "missions": [m.to_dict() for m in missions],
            "source": "legacy",
        })

    except Exception as e:
        return _err(str(e)[:200], status=500)




@router.get("/missions/history")
async def mission_history(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    domain: Optional[str] = None
):
    """
    GET /api/v3/missions/history — Paginated mission history with filters.
    
    Query params:
      limit  (int, default=50)   — max results
      offset (int, default=0)    — pagination offset
      status (str, optional)     — filter by status (DONE, FAILED, ...)
      domain (str, optional)     — filter by domain (software_dev, saas_builder, ...)
    
    Returns missions sorted by created_at DESC (most recent first).
    """
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()

        # Get all missions then filter + paginate
        all_missions = ms.list_missions(limit=1000)  # practical upper bound

        # Filter
        filtered = all_missions
        if status:
            filtered = [m for m in filtered if (m.status.value if hasattr(m.status, "value") else str(m.status)).upper() == status.upper()]
        if domain:
            filtered = [m for m in filtered if getattr(m, "domain", "") == domain]

        # Sort DESC by created_at
        filtered.sort(key=lambda m: getattr(m, "created_at", 0) or 0, reverse=True)

        # Paginate
        total = len(filtered)
        page = filtered[offset:offset + limit]

        return _ok({
            "missions": [m.to_dict() for m in page],
            "total":    total,
            "offset":   offset,
            "limit":    limit,
            "has_more": (offset + limit) < total,
            "filters":  {"status": status, "domain": domain},
        })

    except Exception as e:
        return _err(str(e)[:200], status=500)

@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    """Get mission with canonical status."""
    try:
        if _use_canonical():
            try:
                from core.orchestration_bridge import get_mission_canonical
                ctx = get_mission_canonical(mission_id)
                if ctx:
                    return _ok(ctx.to_dict())
            except Exception as e:
                log.warning("canonical_get_fallback", err=str(e)[:80])

        from core.mission_system import get_mission_system
        ms = get_mission_system()
        mission = ms.get(mission_id)
        if not mission:
            return _err(f"Mission '{mission_id}' not found.", status=404)
        return _ok(mission.to_dict())

    except Exception as e:
        return _err(str(e)[:200], status=500)


@router.post("/missions/{mission_id}/approve")
async def approve_mission(mission_id: str, body: dict = Body(default={})):
    """Approve a pending mission."""
    try:
        note = str(body.get("note", ""))

        if _use_canonical():
            try:
                from core.orchestration_bridge import approve_mission as bridge_approve
                result = bridge_approve(mission_id, note)
                return _ok(result)
            except Exception as e:
                log.warning("canonical_approve_fallback", err=str(e)[:80])

        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.approve(mission_id, note)
        if result is None:
            return _err(f"Mission '{mission_id}' not found or not pending.", status=404)
        return _ok(result.to_dict())

    except Exception as e:
        return _err(str(e)[:200], status=500)


@router.post("/missions/{mission_id}/reject")
async def reject_mission(mission_id: str, body: dict = Body(default={})):
    """Reject a pending mission."""
    try:
        note = str(body.get("note", ""))

        if _use_canonical():
            try:
                from core.orchestration_bridge import reject_mission as bridge_reject
                result = bridge_reject(mission_id, note)
                return _ok(result)
            except Exception as e:
                log.warning("canonical_reject_fallback", err=str(e)[:80])

        from core.mission_system import get_mission_system
        ms = get_mission_system()
        result = ms.reject(mission_id, note=note)
        if result is None:
            return _err(f"Mission '{mission_id}' not found or already terminal.", status=404)
        return _ok(result.to_dict())

    except Exception as e:
        return _err(str(e)[:200], status=500)


# ═══════════════════════════════════════════════════════════════
# SYSTEM ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/system/status")
async def system_status():
    """
    Unified system status.

    Merges:
    - Mission system stats
    - Orchestration bridge status
    - Observability intelligence (if available)
    - Capability expansion status (if available)
    """
    status_data = {
        "timestamp": time.time(),
        "canonical_orchestrator": _use_canonical(),
        "components": {},
    }

    # Mission system
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        status_data["components"]["mission_system"] = ms.stats()
    except Exception as e:
        status_data["components"]["mission_system"] = {"error": str(e)[:80]}

    # Orchestration bridge
    if _use_canonical():
        try:
            from core.orchestration_bridge import get_orchestration_bridge
            bridge = get_orchestration_bridge()
            status_data["components"]["orchestration_bridge"] = bridge.get_status()
        except Exception as e:
            status_data["components"]["orchestration_bridge"] = {"error": str(e)[:80]}

    # Observability
    try:
        from core.observability_intelligence import get_system_health
        status_data["components"]["observability"] = get_system_health()
    except ImportError:
        status_data["components"]["observability"] = {"status": "not_available"}
    except Exception as e:
        status_data["components"]["observability"] = {"error": str(e)[:80]}

    # Capability expansion
    try:
        from core.capability_expansion import get_expansion_status
        status_data["components"]["capability_expansion"] = get_expansion_status()
    except ImportError:
        status_data["components"]["capability_expansion"] = {"status": "not_available"}
    except Exception as _exc:
        log.warning("swallowed_exception", action="capability_expansion_check", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Intelligence hooks
    try:
        from core.intelligence_hooks import periodic_health
        status_data["components"]["intelligence"] = periodic_health()
    except ImportError as _exc:
        log.warning("swallowed_exception", action="intelligence_periodic_health", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    except Exception as _exc:
        log.warning("swallowed_exception", action="intelligence_periodic_log", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Legacy compatibility info
    try:
        from core.legacy_compat import get_authority_map, get_deprecations
        status_data["authority_map"] = get_authority_map()
        status_data["deprecations"] = len(get_deprecations())
    except ImportError as _exc:
        log.warning("swallowed_exception", action="deprecations_count_fetch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return _ok(status_data)


@router.get("/system/health")
async def system_health():
    """Deep health check."""
    checks = {}

    # Core import check
    for module_name in ["core.mission_system", "core.orchestrator_v2",
                        "core.meta_orchestrator", "core.planner"]:
        try:
            __import__(module_name)
            checks[module_name] = "ok"
        except Exception as e:
            checks[module_name] = f"error: {str(e)[:40]}"

    # Approval queue
    try:
        from core.approval_queue import get_pending
        pending = get_pending()
        checks["approval_queue"] = {"ok": True, "pending": len(pending)}
    except Exception as e:
        checks["approval_queue"] = {"ok": False, "error": str(e)[:40]}

    healthy = all(
        v == "ok" or (isinstance(v, dict) and v.get("ok"))
        for v in checks.values()
    )

    return _ok({
        "status": "healthy" if healthy else "degraded",
        "checks": checks,
    })


@router.get("/system/liveness")
async def system_liveness():
    """
    Liveness check — verifies live infrastructure connectivity (LLM + Qdrant + orchestrator).

    Returns HTTP 200 if all infra probes pass, HTTP 503 if any probe fails.
    Use this for deeper health monitoring, NOT for Docker HEALTHCHECK (use
    /api/v3/system/readiness from api.routes.system_readiness for that).

    Checks:
      - At least one LLM API key is configured
      - Qdrant is reachable (if configured)
      - Core orchestrator initializes without error
    """
    import socket
    from fastapi.responses import JSONResponse as _JSONResponse

    probes: dict[str, dict] = {}
    ready = True

    # 1. LLM key availability — report which providers are active
    try:
        from config.settings import get_settings
        import os
        s = get_settings()
        active_providers = []
        if getattr(s, "openrouter_api_key", ""):
            active_providers.append("openrouter")
        if getattr(s, "anthropic_api_key", ""):
            active_providers.append("anthropic")
        if getattr(s, "openai_api_key", ""):
            active_providers.append("openai")
        has_llm = bool(active_providers)
        # Determine primary provider (from MODEL_STRATEGY env, or first available)
        model_strategy = os.environ.get("MODEL_STRATEGY", "") or (active_providers[0] if active_providers else "none")
        model_fallback = os.environ.get("MODEL_FALLBACK", "")
        if has_llm:
            detail = f"providers={active_providers} strategy={model_strategy}"
            if model_fallback:
                detail += f" fallback={model_fallback}"
        else:
            detail = "no LLM key — cannot process missions (set ANTHROPIC_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY)"
        probes["llm_key"] = {"ok": has_llm, "detail": detail, "providers": active_providers, "strategy": model_strategy}
        if not has_llm:
            ready = False
    except Exception as e:
        probes["llm_key"] = {"ok": False, "detail": str(e)[:80]}
        ready = False

    # 2. Qdrant connectivity (non-blocking TCP check, 2s timeout)
    try:
        from config.settings import get_settings
        s = get_settings()
        qdrant_host = getattr(s, "qdrant_host", "") or "qdrant"
        qdrant_port = getattr(s, "qdrant_port", 6333) or 6333
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((qdrant_host, int(qdrant_port)))
        sock.close()
        qdrant_ok = result == 0
        probes["qdrant"] = {
            "ok": qdrant_ok,
            "host": f"{qdrant_host}:{qdrant_port}",
            "detail": "reachable" if qdrant_ok else "unreachable — vector memory unavailable",
        }
        if not qdrant_ok:
            ready = False
    except Exception as e:
        probes["qdrant"] = {"ok": False, "detail": str(e)[:80]}
        ready = False

    # 3. MetaOrchestrator importable and initializable
    try:
        from core.meta_orchestrator import get_meta_orchestrator
        mo = get_meta_orchestrator()
        probes["orchestrator"] = {"ok": True, "detail": f"circuit_breaker={mo._circuit_breaker.status()['open']}"}
    except Exception as e:
        probes["orchestrator"] = {"ok": False, "detail": str(e)[:80]}
        ready = False

    status_code = 200 if ready else 503
    body = {
        "ok": ready,
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "probes": probes,
    }
    return _JSONResponse({"ok": ready, "data": body}, status_code=status_code)


# ═══════════════════════════════════════════════════════════════
# APPROVAL QUEUE
# ═══════════════════════════════════════════════════════════════

@router.get("/approvals/pending")
async def get_pending_approvals():
    """Get all pending approval items."""
    try:
        from core.approval_queue import get_pending
        items = get_pending()
        return _ok({"pending": items, "count": len(items)})
    except Exception as e:
        return _err(str(e)[:200], status=500)


# ═══════════════════════════════════════════════════════════════
# AGENT STATUS
# ═══════════════════════════════════════════════════════════════

@router.get("/agents/status")
async def get_agent_status():
    """Get agent registry status."""
    try:
        agents = {}
        # Try crew registry
        try:
            from agents.crew import AgentCrew
            crew = AgentCrew()
            agents["crew"] = {
                "available": True,
                "agents": list(crew.agents.keys()) if hasattr(crew, "agents") else [],
            }
        except Exception:
            agents["crew"] = {"available": False}

        # Try bea team
        try:
            from agents.bea_team.tools import AGENT_TOOL_ACCESS
            agents["bea_team"] = {
                "available": True,
                "agents": list(AGENT_TOOL_ACCESS.keys()),
            }
        except Exception:
            agents["bea_team"] = {"available": False}

        return _ok(agents)

    except Exception as e:
        return _err(str(e)[:200], status=500)


# ═══════════════════════════════════════════════════════════════
# MISSION CONTROL — v3 equivalents (Flutter migration targets)
# ═══════════════════════════════════════════════════════════════
# These mirror POST/GET /api/v1/missions/{id}/pause|resume|stream.
# v1 endpoints remain until beamax_app ships an APK using these URLs.
# Migration tracker: docs/FRONTEND_SURFACES.md § Active v1 calls.


def _ms_canonical_status(legacy_status: str) -> str:
    """Map legacy mission status to canonical string. Fail-open."""
    try:
        from core.canonical_types import map_legacy_mission_status
        return map_legacy_mission_status(legacy_status, "mission_system").value
    except Exception:
        return str(legacy_status)


@router.post("/missions/{mission_id}/pause")
async def pause_mission_v3(mission_id: str):
    """Pause a mission.

    v3 equivalent of POST /api/v1/missions/{id}/pause.
    Acknowledgement-only — full pause semantics pending backend queue support.
    """
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        mission = ms.get(mission_id)
        if not mission:
            return _err(f"Mission '{mission_id}' not found.", status=404)
        status = _ms_canonical_status(str(mission.status))
        return _ok({"mission_id": mission_id, "action": "pause", "status": status})
    except Exception as e:
        log.warning("swallowed_exception", action="v3_pause_mission", exc_type=type(e).__name__, exc_msg=str(e)[:200])
        return _err(str(e)[:200], status=500)


@router.post("/missions/{mission_id}/resume")
async def resume_mission_v3(mission_id: str):
    """Resume a mission.

    v3 equivalent of POST /api/v1/missions/{id}/resume.
    Acknowledgement-only — full resume semantics pending backend queue support.
    """
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        mission = ms.get(mission_id)
        if not mission:
            return _err(f"Mission '{mission_id}' not found.", status=404)
        status = _ms_canonical_status(str(mission.status))
        return _ok({"mission_id": mission_id, "action": "resume", "status": status})
    except Exception as e:
        log.warning("swallowed_exception", action="v3_resume_mission", exc_type=type(e).__name__, exc_msg=str(e)[:200])
        return _err(str(e)[:200], status=500)


@router.get("/missions/{mission_id}/stream")
async def stream_mission_v3(mission_id: str):
    """Real-time SSE stream for a mission.

    v3 equivalent of GET /api/v1/missions/{id}/stream.
    Identical wire format — same JSON event objects, same text/event-stream
    content type. One-line URL change in beamax_app/lib/services/api_service.dart
    once the APK is rebuilt.
    """
    from api.routes.mission_control import _sse_generator
    return StreamingResponse(
        _sse_generator(mission_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
