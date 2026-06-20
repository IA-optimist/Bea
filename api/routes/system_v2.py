"""
api/routes/system_v2.py — Extended system management endpoints.

Complements api/routes/system.py with additional system controls.
Registered in api/main.py as system_v2_router.

NOTE: POST /api/system/mode is intentionally absent here.
      It is handled exclusively by missions.py (mounted first in main.py).
NOTE: GET /api/v2/system/capabilities is intentionally absent here.
      It is handled exclusively by monitoring.py (mounted first in main.py).

Endpoints:
  GET/POST /api/system/mode/uncensored
  GET      /api/v2/decision-memory/stats
  GET      /api/v2/decision-memory/registry
  GET      /api/v2/system/policy-mode
  POST     /api/v2/system/policy-mode
  GET      /api/v2/metrics/recent
  GET      /api/v2/knowledge/recent
  GET      /api/v2/plan/last
  GET      /api/v2/tools/registry
  POST     /api/v2/tools/test
  POST     /api/v2/tools/rollback
  GET      /health
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request

logger = logging.getLogger("bea.api.system_v2")

# Fail-hard on auth import: a silent fail-open fallback would make
# every route parameter default to None, bypassing Depends entirely.
from api._deps import require_auth
_auth = Depends(require_auth)

router = APIRouter(tags=["system"])


# ── Uncensored Mode ──────────────────────────────────────────

@router.get("/api/system/mode/uncensored")
async def get_uncensored_mode(_user: dict = _auth):
    try:
        from core.mode_system import get_mode_system
        ms = get_mode_system()
        return {
            "uncensored": ms.is_uncensored(),
            "mode": ms.get_mode().value,
        }
    except Exception as e:
        return {"uncensored": False, "error": type(e).__name__}


@router.post("/api/system/mode/uncensored")
async def set_uncensored_mode(request: Request, _user: dict = _auth):
    try:
        from core.mode_system import get_mode_system
        body = await request.json()
        enable = body.get("enable", False)
        ms = get_mode_system()
        if enable:
            ms.enable_uncensored()
        else:
            ms.disable_uncensored()
        return {"ok": True, "uncensored": ms.is_uncensored(), "mode": ms.get_mode().value}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


# ── Decision Memory ──────────────────────────────────────────

@router.get("/api/v2/decision-memory/stats")
async def decision_memory_stats(_user: dict = _auth):
    try:
        from memory.decision_memory import get_decision_memory
        dm = get_decision_memory()
        return {"ok": True, "data": dm.get_stats()}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


@router.get("/api/v2/decision-memory/registry")
async def decision_memory_registry(_user: dict = _auth):
    try:
        from memory.decision_memory import get_decision_memory
        dm = get_decision_memory()
        return {"ok": True, "data": dm.get_registry()}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


# ── Policy Mode ──────────────────────────────────────────────

@router.get("/api/v2/system/policy-mode")
async def get_policy_mode(_user: dict = _auth):
    try:
        from core.policy_mode import get_policy_mode_store
        _store = get_policy_mode_store()
        return {"ok": True, "data": _store.to_dict(), "uncensored_stats": _store.get_uncensored_stats()}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


@router.post("/api/v2/system/policy-mode")
async def set_policy_mode(request: Request, _user: dict = _auth):
    try:
        from core.policy_mode import get_policy_mode_store
        body = await request.json()
        mode = body.get("policy_mode", "BALANCED")
        ok = get_policy_mode_store().set(mode)
        return {"ok": ok, "data": get_policy_mode_store().to_dict()}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


# ── Metrics ──────────────────────────────────────────────────

@router.get("/api/v2/metrics/recent")
async def get_recent_metrics(_user: dict = _auth):
    try:
        from core.observability.store import get_observability_store
        store = get_observability_store()
        return {"stats": store.get_stats(), "recent": store.get_recent(20)}
    except Exception as e:
        return {"stats": {}, "recent": [], "error": type(e).__name__}


# ── Knowledge ────────────────────────────────────────────────

@router.get("/api/v2/knowledge/recent")
async def get_knowledge_recent(_user: dict = _auth):
    try:
        from core.knowledge_memory import get_knowledge_memory
        km = get_knowledge_memory()
        return {"stats": km.get_stats(), "solutions": km.get_recent_solutions(20)}
    except Exception as e:
        return {"stats": {}, "solutions": [], "error": type(e).__name__}


# ── Plan ─────────────────────────────────────────────────────

@router.get("/api/v2/plan/last")
async def get_last_plan(_user: dict = _auth):
    try:
        from core.mission_planner import get_last_plan, get_mission_planner
        plan = get_last_plan()
        if plan is None:
            return {"plan": None, "message": "No plan executed yet"}
        planner = get_mission_planner()
        return {"plan": planner.plan_to_dict(plan)}
    except Exception as e:
        return {"plan": None, "error": type(e).__name__}


# ── Tools ────────────────────────────────────────────────────

@router.get("/api/v2/tools/registry")
async def get_tools_registry(_user: dict = _auth):
    try:
        from core.tool_registry import get_tool_registry
        reg = get_tool_registry()
        return {"tools": reg.summary(), "count": len(reg.list_tools())}
    except Exception as e:
        return {"tools": [], "count": 0, "error": type(e).__name__}


@router.post("/api/v2/tools/test")
async def test_tool_live(payload: dict, _user: dict = _auth):
    """Test live d'un tool. Body: {"tool": "name", "params": {...}}"""
    tool_name = payload.get("tool", "")
    params = payload.get("params", {})
    if not tool_name:
        return {"ok": False, "error": "tool name required"}
    try:
        from core.tool_executor import get_tool_executor
        result = get_tool_executor().execute(tool_name, params, approval_mode="SUPERVISED")
        return {"ok": True, "tool": tool_name, "result": result}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


@router.post("/api/v2/tools/rollback")
async def rollback_file(payload: dict, _user: dict = _auth):
    """Rollback manuel. Body: {"filepath": "path/to/file.py"}"""
    filepath = payload.get("filepath", "")
    if not filepath:
        return {"ok": False, "error": "filepath required"}
    try:
        from core.rollback_manager import get_rollback_manager
        rm = get_rollback_manager()
        backups = rm.list_backups(filepath)
        if not backups:
            return {"ok": False, "error": "no_backup_found", "filepath": filepath}
        ok = rm.restore_latest(filepath)
        return {
            "ok": ok, "filepath": filepath,
            "restored_from": backups[-1] if ok else None,
            "available_backups": backups,
            "status": "rollback_success" if ok else "rollback_failed",
        }
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


# ── Health ───────────────────────────────────────────────────

@router.get("/health", include_in_schema=False)
async def health_check():
    """
    Basic health check endpoint.
    NOTE: api/main.py also defines GET /health (Docker healthcheck).
    FastAPI uses the first registered route — main.py's wins.
    This function is kept for importability by tests (test_api_structure.py).
    """
    return {"status": "ok", "service": "beamax"}


@router.get("/api/v2/system/health/llm", tags=["system"])
async def llm_health_check():
    """
    Test each configured LLM provider with a minimal ping call.
    Returns per-provider status so operators know exactly what works.
    """
    import time as _time
    results: dict = {}

    try:
        from config.settings import get_settings
        from core.llm_factory import LLMFactory
        s = get_settings()
        f = LLMFactory(s)

        providers_to_test = [
            ("openrouter", lambda: f._build_openrouter("director")),
            ("anthropic",  lambda: f._build_anthropic("director")),
            ("openai",     lambda: f._build_openai("director")),
            ("ollama",     lambda: f._build_ollama("director")),
        ]

        for name, builder in providers_to_test:
            t0 = _time.monotonic()
            try:
                llm = builder()
                if llm is None:
                    results[name] = {"status": "no_key", "ms": 0}
                    continue
                from langchain_core.messages import HumanMessage
                resp = await llm.ainvoke(
                    [HumanMessage(content="Reply with the single word: ok")],
                )
                ms = int((_time.monotonic() - t0) * 1000)
                content = getattr(resp, "content", "") or ""
                results[name] = {
                    "status": "ok",
                    "ms": ms,
                    "response_preview": content[:40],
                }
            except Exception as e:
                ms = int((_time.monotonic() - t0) * 1000)
                results[name] = {
                    "status": "error",
                    "ms": ms,
                    "error": type(e).__name__,
                }

    except Exception as e:
        return {"ok": False, "error": type(e).__name__}

    any_ok = any(v.get("status") == "ok" for v in results.values())
    return {
        "ok": any_ok,
        "providers": results,
        "summary": "at_least_one_provider_ok" if any_ok else "no_provider_available",
    }
