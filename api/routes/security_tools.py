"""
api/routes/security_tools.py — HexStrike V2 security tool API.

Routes:
    GET  /api/v3/security/tools                        — list all tools + availability
    GET  /api/v3/security/tools/stats                  — registry stats
    GET  /api/v3/security/tools/{tool_name}            — single tool details
    POST /api/v3/security/tools/{tool_name}/execute    — execute tool (approval-gated)
    GET  /api/v3/security/tools/categories             — list available categories

All execution requires authentication. High-risk tools additionally require
'X-Operator-Approval: true' header or an active operator session.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Optional

from api._deps import require_auth

log = structlog.get_logger("api.security_tools")

router = APIRouter(prefix="/api/v3/security/tools", tags=["security-tools"])


# ── Request / Response models ─────────────────────────────────────────────────

class ToolExecuteRequest(BaseModel):
    target: str
    options: Optional[str] = ""
    # Tool-specific parameters (e.g. module for metasploit, level for sqlmap)
    extra: Optional[dict[str, Any]] = None


class ToolExecuteResponse(BaseModel):
    ok: bool
    tool: str
    target: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None
    risk_level: str
    available: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_connector():
    from core.connectors.hexstrike import (
        list_security_tools,
        check_tool_availability,
        execute_security_tool,
        get_registry_stats,
    )
    return list_security_tools, check_tool_availability, execute_security_tool, get_registry_stats


def _is_operator_approved(x_operator_approval: Optional[str]) -> bool:
    return (x_operator_approval or "").lower() in ("true", "1", "yes")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_tools(
    category: Optional[str] = Query(None, description="Filter by category: recon, scanning, web, exploitation"),
    available_only: bool = Query(False, description="Return only installed tools"),
    _user: dict = Depends(require_auth),
):
    """List all HexStrike security tools with installation status."""
    try:
        list_fn, _, _, _ = _get_connector()
        tools = list_fn(category=category)
        if available_only:
            tools = [t for t in tools if t["available"]]
        return {
            "ok": True,
            "data": tools,
            "count": len(tools),
            "category_filter": category,
        }
    except Exception as exc:
        log.error("security_tools_list_error", err=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats")
async def registry_stats(_user: dict = Depends(require_auth)):
    """Return hexstrike registry statistics."""
    try:
        _, _, _, stats_fn = _get_connector()
        return {"ok": True, "data": stats_fn()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/categories")
async def list_categories(_user: dict = Depends(require_auth)):
    """List available tool categories."""
    try:
        from mcp.hexstrike_v2.registry import registry
        return {"ok": True, "data": registry.get_categories()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{tool_name}")
async def get_tool(tool_name: str, _user: dict = Depends(require_auth)):
    """Get details and availability for a specific tool."""
    try:
        _, check_fn, _, _ = _get_connector()
        info = check_fn(tool_name)
        if not info.get("available") and "Tool not registered" in str(info.get("error", "")):
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not registered")
        # Also get full tool spec
        from mcp.hexstrike_v2.registry import registry
        tool = registry.get_tool(tool_name)
        if tool:
            info["parameters"] = tool.parameters
            info["description"] = tool.description
            info["tags"] = tool.tags
        return {"ok": True, "data": info}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{tool_name}/execute")
async def execute_tool(
    tool_name: str,
    body: ToolExecuteRequest,
    x_operator_approval: Optional[str] = Header(None, alias="X-Operator-Approval"),
    _user: dict = Depends(require_auth),
):
    """
    Execute a HexStrike security tool.

    High-risk tools (sqlmap, metasploit, ZAP) require the header:
        X-Operator-Approval: true

    The 'target' field is required. Use 'options' for extra CLI flags.
    Tool-specific params (e.g. 'module' for metasploit) go in 'extra'.
    """
    try:
        _, check_fn, execute_fn, _ = _get_connector()

        # Check availability before attempting execution
        avail = check_fn(tool_name)
        if avail.get("error") == "Tool not registered":
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not registered")

        approved = _is_operator_approved(x_operator_approval)
        params: dict[str, Any] = {"target": body.target}
        if body.options:
            params["options"] = body.options
        if body.extra:
            params.update(body.extra)

        log.info(
            "security_tool_execute_request",
            tool=tool_name,
            target=body.target[:60],
            approved=approved,
            user=_user.get("sub", "?"),
        )

        result = execute_fn(tool_name, params, approved=approved)

        if not result.success and "requires operator approval" in (result.error or ""):
            raise HTTPException(
                status_code=403,
                detail=result.error,
                headers={"X-Approval-Required": "true"},
            )

        data = result.data or {}
        return ToolExecuteResponse(
            ok=result.success,
            tool=tool_name,
            target=body.target,
            output=data.get("output") if isinstance(data, dict) else str(data or ""),
            error=result.error or None,
            duration_seconds=data.get("duration_seconds") if isinstance(data, dict) else None,
            risk_level=avail.get("risk_level", "unknown"),
            available=avail.get("available", False),
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.error("security_tool_execute_error", tool=tool_name, err=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
