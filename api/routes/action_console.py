"""
JARVIS MAX — Action Console API
===================================
Operator-facing approval console for pending tool/mission actions.

GET  /api/v3/console/pending       — List pending approvals
GET  /api/v3/console/history       — Recent approval decisions
POST /api/v3/console/approve/{id}  — Approve a request
POST /api/v3/console/deny/{id}     — Deny a request
GET  /api/v3/console/stats         — Approval system stats
GET  /api/v3/console/permissions   — List tool permission registry
GET  /api/v3/console/deps          — Module dependency health
GET  /api/v3/console/budget/{mid}  — Mission budget status
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from api._deps import _check_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/console", tags=["action-console"])


class FeedbackRequest(BaseModel):
    feedback: str = ""


# ── Approval Console ──

@router.get("/pending")
async def list_pending(
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """List all pending tool/action approval requests."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.tool_permissions import get_tool_permissions
        reg = get_tool_permissions()
        pending = [r.to_dict() for r in reg.get_pending()]
        # Also include module approval tickets
        try:
            from core.modules.approval_notifier import ApprovalNotifier
            notifier = ApprovalNotifier()
            # Module tickets are separate — include if available
        except Exception:
            _silent_log.debug("suppressed_exception", src='action_console.py')
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        logger.warning(f"pending_list_failed: {e}")
        return {"pending": [], "count": 0, "error": str(e)}


@router.get("/history")
async def approval_history(
    limit: int = 50,
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """Recent approval decisions."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.tool_permissions import get_tool_permissions
        return {"history": get_tool_permissions().get_history(limit=limit)}
    except Exception as e:
        return {"history": [], "error": str(e)}


@router.post("/approve/{request_id}")
async def approve_request(
    request_id: str,
    body: FeedbackRequest = FeedbackRequest(),
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """Approve a pending tool execution request."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.tool_permissions import get_tool_permissions
        success = get_tool_permissions().approve(request_id, feedback=body.feedback)
        if not success:
            raise HTTPException(status_code=404,
                              detail="Request not found, already decided, or expired")
        return {"status": "approved", "request_id": request_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deny/{request_id}")
async def deny_request(
    request_id: str,
    body: FeedbackRequest = FeedbackRequest(),
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """Deny a pending tool execution request."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.tool_permissions import get_tool_permissions
        success = get_tool_permissions().deny(request_id, feedback=body.feedback)
        if not success:
            raise HTTPException(status_code=404,
                              detail="Request not found, already decided, or expired")
        return {"status": "denied", "request_id": request_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def console_stats(
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """Approval system statistics."""
    _check_auth(x_jarvis_token, authorization)
    result = {}
    try:
        from core.tool_permissions import get_tool_permissions
        result["permissions"] = get_tool_permissions().stats()
    except Exception as e:
        result["permissions"] = {"error": str(e)}
    try:
        from core.tool_config_registry import get_config_registry
        result["dependencies"] = get_config_registry().stats()
    except Exception as e:
        result["dependencies"] = {"error": str(e)}
    try:
        from core.mission_guards import get_guardian
        result["active_budgets"] = len(get_guardian().active_missions())
    except Exception as e:
        result["active_budgets"] = 0
    return result


@router.get("/permissions")
async def list_permissions(
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """List all tool permission declarations."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.tool_permissions import get_tool_permissions
        return {"permissions": get_tool_permissions().list_all()}
    except Exception as e:
        return {"permissions": [], "error": str(e)}


@router.get("/deps")
async def dependency_health(
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """Module dependency health overview."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.tool_config_registry import get_config_registry
        return {"dependencies": get_config_registry().check_all(),
                "stats": get_config_registry().stats()}
    except Exception as e:
        return {"dependencies": {}, "error": str(e)}


@router.get("/budget/{mission_id}")
async def mission_budget(
    mission_id: str,
    x_jarvis_token: str | None = Header(None),
    authorization: str | None = Header(None)
):
    """Get budget status for a running mission."""
    _check_auth(x_jarvis_token, authorization)
    try:
        from core.mission_guards import get_guardian
        budget = get_guardian().get_budget(mission_id)
        if not budget:
            raise HTTPException(status_code=404, detail="Mission not found")
        return budget.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
