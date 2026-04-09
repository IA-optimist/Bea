"""
JARVIS MAX — Extension Management API
========================================
Admin-only CRUD for Agents, MCP Connectors, Skills, and Tools.

28 endpoints:
  7 per type (list, create, update, enable, disable, test, delete)
  + GET /health (summary)
  + GET /audit (audit trail)
"""
from __future__ import annotations

from pathlib import Path

try:
    from fastapi import APIRouter, Depends, HTTPException, Request, Body
    from fastapi.responses import JSONResponse
    from api._deps import require_auth
except ImportError:
    # Stub for environments without FastAPI
    class _Stub:
        def __getattr__(self, name):
            return lambda *a, **kw: lambda f: f
    APIRouter = _Stub  # type: ignore
    HTTPException = Exception  # type: ignore
    Request = object  # type: ignore
    Body = lambda *a, **kw: None  # type: ignore
    Depends = lambda *a, **kw: None  # type: ignore
    require_auth = None  # type: ignore
    class JSONResponse:  # type: ignore
        def __init__(self, *a, **kw): pass

from core.extension_registry import get_extension_registry


# Defense-in-depth: router-level auth (in addition to global middleware).
# Prevents exposure if middleware fails to load.
router = APIRouter(
    prefix="/api/v3/extensions",
    tags=["extensions"],
    dependencies=[Depends(require_auth)] if require_auth else [],
)


# ── Helpers ──────────────────────────────────────────────────

def _require_admin(request: Request) -> str:
    """Check admin permission. Returns actor identifier."""
    # Auth is enforced by global middleware; we check role here
    token_info = getattr(request.state, "user", None)
    if not token_info:
        raise HTTPException(status_code=401, detail="Authentication required")
    role = token_info.get("role", "viewer")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return token_info.get("username", token_info.get("sub", "admin"))


EXT_TYPES = ("agents", "mcp", "skills", "tools")
# Plural → singular mapping for registry
_SINGULAR = {"agents": "agent", "mcp": "mcp", "skills": "skill", "tools": "tool"}


# ── Generic CRUD factory ────────────────────────────────────

def _list(ext_type_plural: str):
    async def handler(request: Request):
        _require_admin(request)
        reg = get_extension_registry()
        items = reg.list_all(_SINGULAR[ext_type_plural], include_core=True)
        return {"items": items, "count": len(items)}
    return handler


def _create(ext_type_plural: str):
    async def handler(request: Request, data: dict = Body(...)):
        actor = _require_admin(request)
        reg = get_extension_registry()
        result = reg.create(_SINGULAR[ext_type_plural], data, actor=actor)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result)
        return result
    return handler


def _update(ext_type_plural: str):
    async def handler(request: Request, ext_id: str, data: dict = Body(...)):
        actor = _require_admin(request)
        reg = get_extension_registry()
        result = reg.update(_SINGULAR[ext_type_plural], ext_id, data, actor=actor)
        if not result.get("ok"):
            status = 404 if "Not found" in result.get("error", "") else 422
            raise HTTPException(status_code=status, detail=result)
        return result
    return handler


def _enable(ext_type_plural: str):
    async def handler(request: Request, ext_id: str):
        actor = _require_admin(request)
        reg = get_extension_registry()
        result = reg.enable(_SINGULAR[ext_type_plural], ext_id, actor=actor)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result)
        return result
    return handler


def _disable(ext_type_plural: str):
    async def handler(request: Request, ext_id: str):
        actor = _require_admin(request)
        reg = get_extension_registry()
        result = reg.disable(_SINGULAR[ext_type_plural], ext_id, actor=actor)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result)
        return result
    return handler


def _test(ext_type_plural: str):
    async def handler(request: Request, ext_id: str):
        actor = _require_admin(request)
        reg = get_extension_registry()
        result = reg.test(_SINGULAR[ext_type_plural], ext_id, actor=actor)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result)
        return result
    return handler


def _delete(ext_type_plural: str):
    async def handler(request: Request, ext_id: str):
        actor = _require_admin(request)
        reg = get_extension_registry()
        result = reg.delete(_SINGULAR[ext_type_plural], ext_id, actor=actor)
        if not result.get("ok"):
            status = 404 if "Not found" in result.get("error", "") else 403
            raise HTTPException(status_code=status, detail=result)
        return result
    return handler


# ── Register all 28 CRUD routes ─────────────────────────────

for _type in EXT_TYPES:
    _s = _SINGULAR[_type]

    router.add_api_route(f"/{_type}", _list(_type), methods=["GET"],
                         summary=f"List {_type}")
    router.add_api_route(f"/{_type}", _create(_type), methods=["POST"],
                         summary=f"Create {_s}")
    router.add_api_route(f"/{_type}/{{ext_id}}", _update(_type), methods=["PUT"],
                         summary=f"Update {_s}")
    router.add_api_route(f"/{_type}/{{ext_id}}/enable", _enable(_type), methods=["POST"],
                         summary=f"Enable {_s}")
    router.add_api_route(f"/{_type}/{{ext_id}}/disable", _disable(_type), methods=["POST"],
                         summary=f"Disable {_s}")
    router.add_api_route(f"/{_type}/{{ext_id}}/test", _test(_type), methods=["POST"],
                         summary=f"Test {_s}")
    router.add_api_route(f"/{_type}/{{ext_id}}", _delete(_type), methods=["DELETE"],
                         summary=f"Delete {_s}")


# ── Health + Audit ───────────────────────────────────────────

@router.get("/health", summary="Extension health summary")
async def extension_health(request: Request):
    _require_admin(request)
    reg = get_extension_registry()
    return reg.health_summary()


@router.get("/audit", summary="Extension audit log")
async def extension_audit(request: Request, limit: int = 50):
    _require_admin(request)
    reg = get_extension_registry()
    return {"entries": reg.get_audit(limit=min(limit, 200))}
