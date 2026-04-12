"""
JARVIS MAX — Convergence API Router
======================================
Provides /api/v3/ endpoints that route through the OrchestrationBridge
to MetaOrchestrator (canonical authority) when JARVIS_USE_CANONICAL_ORCHESTRATOR=1.

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

import json
import os
import time
from typing import Optional
from api._deps import _check_auth
_silent_log = __import__("structlog").get_logger(__name__)

try:
    from fastapi import BackgroundTasks, Depends, APIRouter, Body, Header, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse
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
    Body = lambda **k: None
    WebSocket = object
    WebSocketDisconnect = Exception
    JSONResponse = dict

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)



def _auth(x_jarvis_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_jarvis_token, authorization)


router = APIRouter(prefix="/api/v3", tags=["convergence"], dependencies=[Depends(_auth)])


def _use_canonical() -> bool:
    # Default TRUE — v3 API always uses the canonical orchestrator bridge.
    # Set JARVIS_USE_CANONICAL_ORCHESTRATOR=0 to fall back to legacy MissionSystem.
    val = os.environ.get("JARVIS_USE_CANONICAL_ORCHESTRATOR", "1").lower()
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
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='convergence.py')
                # Trigger real execution in background — without this, mission stays READY forever
                if background_tasks and mission_id and result.get("ok"):
                    _goal_capture = goal
                    _mid_capture = mission_id
                    _ctx_capture = str(body.get("context", "") or "")
                    async def _execute_canonical():
                        try:
                            from core.meta_orchestrator import get_meta_orchestrator
                            mo = get_meta_orchestrator()
                            import inspect
                            _sig = inspect.signature(mo.run_mission)
                            if "extra_metadata" in _sig.parameters and _ctx_capture:
                                await mo.run_mission(
                                    _goal_capture,
                                    mission_id=_mid_capture,
                                    extra_metadata={"context": _ctx_capture},
                                )
                            else:
                                await mo.run_mission(_goal_capture, mission_id=_mid_capture)
                        except Exception as _exc:
                            log.warning("canonical_execution_failed", mission_id=_mid_capture, err=str(_exc)[:120])
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
        except Exception:
            _silent_log.debug("suppressed_exception", src='convergence.py')

        return _ok(data, status=201)

    except Exception as e:
        log.warning("submit_mission_err", err=str(e)[:80])
        return _err(str(e)[:200], status=500)


@router.get("/missions")
async def list_missions(
    status: Optional[str] = None,
    limit: int = 20,
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
    domain: Optional[str] = None,
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
    except Exception:
        _silent_log.debug("suppressed_exception", src='convergence.py')

    # Intelligence hooks
    try:
        from core.intelligence_hooks import periodic_health
        status_data["components"]["intelligence"] = periodic_health()
    except ImportError:
        _silent_log.debug("suppressed_exception", src='convergence.py')
    except Exception:
        _silent_log.debug("suppressed_exception", src='convergence.py')

    # Legacy compatibility info
    try:
        from core.legacy_compat import get_authority_map, get_deprecations
        status_data["authority_map"] = get_authority_map()
        status_data["deprecations"] = len(get_deprecations())
    except ImportError:
        _silent_log.debug("suppressed_exception", src='convergence.py')

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


@router.get("/system/readiness")
async def system_readiness():
    """
    Readiness probe — returns HTTP 200 only when the system can process missions.

    Unlike /system/health (which checks imports), this checks LIVE connectivity
    to external infrastructure required for real mission execution.

    HTTP 200 → system is ready to process missions
    HTTP 503 → system is not ready (infra missing or LLM unavailable)

    Checks:
      - At least one LLM API key is configured
      - Qdrant is reachable (if configured)
      - Core orchestrator initializes without error

    Designed for Kubernetes readinessProbe / load balancer health gates.
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

        # Try jarvis team
        try:
            from agents.jarvis_team.tools import AGENT_TOOL_ACCESS
            agents["jarvis_team"] = {
                "available": True,
                "agents": list(AGENT_TOOL_ACCESS.keys()),
            }
        except Exception:
            agents["jarvis_team"] = {"available": False}

        return _ok(agents)

    except Exception as e:
        return _err(str(e)[:200], status=500)
