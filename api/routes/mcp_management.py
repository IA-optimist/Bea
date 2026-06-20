"""
BEA MAX — MCP Management API
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
from fastapi import Depends, APIRouter, HTTPException, Header

from api._deps import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/mcp", tags=["mcp"],
    dependencies=[Depends(require_auth)]
)


def _get_registry():
    try:
        from core.mcp.mcp_registry import get_mcp_registry
        return get_mcp_registry()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MCP registry unavailable: {e}")


@router.get("/servers")
async def list_servers(
    category: str = "", trust: str = ""
):
    """List all registered MCP servers."""
    reg = _get_registry()
    servers = reg.list_all(category=category, trust=trust)
    return {"servers": [s.to_safe_dict() for s in servers],
            "total": len(servers)}


@router.get("/servers/{mcp_id}")
async def get_server(mcp_id: str, x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Get MCP server details."""
    entry = _get_registry().get(mcp_id)
    if not entry:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return entry.to_safe_dict()


@router.post("/servers/{mcp_id}/enable")
async def enable_server(mcp_id: str, x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Enable an MCP server (checks dependencies first)."""
    result = _get_registry().enable(mcp_id)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if result.startswith("Cannot"):
        raise HTTPException(status_code=409, detail=result)
    return {"status": result, "mcp_id": mcp_id}


@router.post("/servers/{mcp_id}/disable")
async def disable_server(mcp_id: str, x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Disable an MCP server."""
    result = _get_registry().disable(mcp_id)
    if result is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"status": result, "mcp_id": mcp_id}


@router.get("/servers/{mcp_id}/health")
async def server_health(mcp_id: str, x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Check health of a specific MCP server."""
    result = _get_registry().check_health(mcp_id)
    if result.get("health") == "not_found":
        raise HTTPException(status_code=404, detail="MCP server not found")
    return result


@router.get("/servers/{mcp_id}/tools")
async def discover_tools(mcp_id: str, x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Discover tools from an MCP server."""
    entry = _get_registry().get(mcp_id)
    if not entry:
        raise HTTPException(status_code=404, detail="MCP server not found")
    tools = _get_registry().discover_tools(mcp_id)
    return {"mcp_id": mcp_id, "tools": tools, "count": len(tools)}


@router.get("/health")
async def all_health(x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Health check for all MCP servers."""
    return {"health": _get_registry().check_all_health()}


@router.get("/stats")
async def registry_stats(x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """MCP registry statistics."""
    return _get_registry().stats()


@router.get("/servers/{mcp_id}/probe")
async def probe_spawn(mcp_id: str, x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Probe whether an MCP server binary can actually start."""
    return _get_registry().probe_spawn(mcp_id)


@router.get("/probe-all")
async def probe_all(x_bea_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Probe all MCP servers for spawn capability."""
    return {"probes": _get_registry().probe_all_spawnable()}


from pydantic import BaseModel  # noqa: E402

class AddMcpServerRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    command: str = ""
    args: list[str] = []
    transport: str = "stdio"
    endpoint: str = ""
    category: str = "community"
    trust_level: str = "community"
    risk_level: str = "medium"
    required_secrets: list[str] = []
    source: str = ""
    source_url: str = ""


@router.post("/servers")
async def add_server(
    req: AddMcpServerRequest
):
    """Register a new MCP server."""
    from core.mcp.mcp_registry import MCPServerEntry
    reg = _get_registry()
    if reg.get(req.id):
        raise HTTPException(status_code=409, detail=f"MCP server '{req.id}' already exists")
    entry = MCPServerEntry(
        id=req.id,
        name=req.name,
        description=req.description,
        command=req.command,
        args=req.args,
        transport=req.transport,
        endpoint=req.endpoint,
        category=req.category,
        trust_level=req.trust_level,
        risk_level=req.risk_level,
        required_secrets=req.required_secrets,
        source=req.source,
        source_url=req.source_url,
        status="disabled",
    )
    reg.register(entry)
    return {"status": "registered", "server": entry.to_safe_dict()}


@router.delete("/servers/{mcp_id}")
async def delete_server(
    mcp_id: str
):
    """Unregister an MCP server."""
    removed = _get_registry().unregister(mcp_id)
    if not removed:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"status": "removed", "mcp_id": mcp_id}
