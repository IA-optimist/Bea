"""
JARVIS MAX — MCP Management API
====================================
REST API for MCP server registry management.

GET  /api/v3/mcp/servers           — List all MCP servers
GET  /api/v3/mcp/servers/{id}      — Get MCP server details
POST /api/v3/mcp/servers/{id}/enable  — Enable MCP server
POST /api/v3/mcp/servers/{id}/disable — Disable MCP server
GET  /api/v3/mcp/servers/{id}/health  — Check MCP health
GET  /api/v3/mcp/servers/{id}/tools   — Discover tools
GET  /api/v3/mcp/health            — All servers health
GET  /api/v3/mcp/stats             — Registry stats
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Header

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/mcp", tags=["mcp"])


def _check_auth(authorization: str | None) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")


def _get_registry():
    try:
        from core.mcp.mcp_registry import get_mcp_registry
        return get_mcp_registry()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MCP registry unavailable: {e}")


@router.get("/servers")
async def list_servers(
    category: str = "", trust: str = "",
    authorization: str | None = Header(None),
):
    """List all registered MCP servers."""
    _check_auth(authorization)
    reg = _get_registry()
    servers = reg.list_all(category=category, trust=trust)
    return {"servers": [s.to_safe_dict() for s in servers],
            "total": len(servers)}


@router.get("/servers/{mcp_id}")
async def get_server(mcp_id: str, authorization: str | None = Header(None)):
    """Get MCP server details."""
    _check_auth(authorization)
    entry = _get_registry().get(mcp_id)
    if not entry:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return entry.to_safe_dict()


@router.post("/servers/{mcp_id}/enable")
async def enable_server(mcp_id: str, authorization: str | None = Header(None)):
    """Enable an MCP server (checks dependencies first)."""
    _check_auth(authorization)
    result = _get_registry().enable(mcp_id)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if result.startswith("Cannot"):
        raise HTTPException(status_code=409, detail=result)
    return {"status": result, "mcp_id": mcp_id}


@router.post("/servers/{mcp_id}/disable")
async def disable_server(mcp_id: str, authorization: str | None = Header(None)):
    """Disable an MCP server."""
    _check_auth(authorization)
    result = _get_registry().disable(mcp_id)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"status": result, "mcp_id": mcp_id}


@router.get("/servers/{mcp_id}/health")
async def server_health(mcp_id: str, authorization: str | None = Header(None)):
    """Check health of a specific MCP server."""
    _check_auth(authorization)
    result = _get_registry().check_health(mcp_id)
    if result.get("health") == "not_found":
        raise HTTPException(status_code=404, detail="MCP server not found")
    return result


@router.get("/servers/{mcp_id}/tools")
async def discover_tools(mcp_id: str, authorization: str | None = Header(None)):
    """Discover tools from an MCP server."""
    _check_auth(authorization)
    entry = _get_registry().get(mcp_id)
    if not entry:
        raise HTTPException(status_code=404, detail="MCP server not found")
    tools = _get_registry().discover_tools(mcp_id)
    return {"mcp_id": mcp_id, "tools": tools, "count": len(tools)}


@router.get("/health")
async def all_health(authorization: str | None = Header(None)):
    """Health check for all MCP servers."""
    _check_auth(authorization)
    return {"health": _get_registry().check_all_health()}


@router.get("/stats")
async def registry_stats(authorization: str | None = Header(None)):
    """MCP registry statistics."""
    _check_auth(authorization)
    return _get_registry().stats()


@router.get("/servers/{mcp_id}/probe")
async def probe_spawn(mcp_id: str, authorization: str | None = Header(None)):
    """Probe whether an MCP server binary can actually start."""
    _check_auth(authorization)
    return _get_registry().probe_spawn(mcp_id)


@router.get("/probe-all")
async def probe_all(authorization: str | None = Header(None)):
    """Probe all MCP servers for spawn capability."""
    _check_auth(authorization)
    return {"probes": _get_registry().probe_all_spawnable()}
