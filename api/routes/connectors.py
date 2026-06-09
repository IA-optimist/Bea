"""
api/routes/connectors.py — Connector management API.

Endpoints:
  GET  /api/v3/connectors              — list all connectors with status
  GET  /api/v3/connectors/{name}       — get connector detail
  POST /api/v3/connectors/{name}/toggle — enable/disable connector (runtime)
  POST /api/v3/connectors/{name}/test  — test connector connectivity
  POST /api/v3/connectors/{name}/execute — execute a connector action
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

# Fail-hard on auth import: a None fallback would make Depends(None) a
# pass-through, creating a silent auth bypass.
from api._deps import require_auth

router = APIRouter(prefix="/api/v3/connectors", tags=["connectors"])


class ConnectorActionRequest(BaseModel):
    action: str
    params: dict = {}


def _get_registry():
    from connectors.base import get_connector_registry
    from connectors.github_connector import GitHubConnector
    from connectors.filesystem_connector import FilesystemConnector
    from connectors.http_connector import HttpConnector

    reg = get_connector_registry()
    # Register built-in connectors if not already registered
    if not reg.get("github"):
        reg.register(GitHubConnector())
    if not reg.get("filesystem"):
        reg.register(FilesystemConnector())
    if not reg.get("http"):
        reg.register(HttpConnector())
    # Connecteurs intégrés additionnels (Slack/Telegram/Discord/Notion/email).
    # fail-open : register_builtin_connectors gère déjà ses erreurs par connecteur.
    if not reg.get("slack"):
        try:
            from connectors.bootstrap import register_builtin_connectors
            register_builtin_connectors(reg)
        except Exception:
            import logging
            logging.getLogger(__name__).debug("builtin_connectors_register_failed", exc_info=True)
    return reg


@router.get("")
async def list_connectors(user=Depends(require_auth)):
    """List all connectors with status."""
    reg = _get_registry()
    return {
        "ok": True,
        "connectors": reg.list_all(),
        "enabled_count": len(reg.get_enabled()),
    }


@router.get("/{name}")
async def get_connector(name: str, user=Depends(require_auth)):
    """Get connector detail."""
    reg = _get_registry()
    c = reg.get(name)
    if not c:
        return {"ok": False, "error": f"Connector '{name}' not found"}
    return {"ok": True, "connector": c.get_status()}


@router.post("/{name}/toggle")
async def toggle_connector(name: str, user=Depends(require_auth)):
    """Toggle connector enabled/disabled (runtime only, via env var)."""
    import os
    from fastapi import HTTPException
    reg = _get_registry()
    c = reg.get(name)
    if not c:
        raise HTTPException(status_code=404, detail=f"Connector '{name}' not found")
    key = f"CONNECTOR_{name.upper()}_ENABLED"
    currently_enabled = c.is_enabled()
    os.environ[key] = "0" if currently_enabled else "1"
    new_status = "disabled" if currently_enabled else "enabled"
    return {"ok": True, "status": new_status, "name": name}


@router.post("/{name}/test")
async def test_connector(name: str, user=Depends(require_auth)):
    """Test a connector connection."""
    from fastapi import HTTPException
    reg = _get_registry()
    c = reg.get(name)
    if not c:
        raise HTTPException(status_code=404, detail=f"Connector '{name}' not found")
    configured = c.is_configured()
    return {
        "ok": True,
        "status": "pass" if configured else "no_credentials",
        "name": name,
        "enabled": c.is_enabled(),
        "health": {"status": "healthy" if configured else "unconfigured"},
    }


@router.post("/{name}/execute")
async def execute_connector(
    name: str, req: ConnectorActionRequest, user=Depends(require_auth)
):
    """Execute a connector action."""
    reg = _get_registry()
    result = reg.execute(name, req.action, req.params)
    return {"ok": result.success, "result": result.to_dict()}
