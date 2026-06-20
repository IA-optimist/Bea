"""
BEA MAX — Action Console API
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

import structlog
from fastapi import Depends, APIRouter, HTTPException
from pydantic import BaseModel

from api._deps import require_auth

logger = structlog.get_logger(__name__)
log = logger  # M3 emitter alias

router = APIRouter(prefix="/api/v3/console", tags=["action-console"],
    dependencies=[Depends(require_auth)]
)


class FeedbackRequest(BaseModel):
    feedback: str = ""


# ── Approval Console ──

@router.get("/pending")
async def list_pending(
):
    """List all pending tool/action approval requests."""
    try:
        from core.tool_permissions import get_tool_permissions
        reg = get_tool_permissions()
        pending = [r.to_dict() for r in reg.get_pending()]
        # Also include module approval tickets
        try:
            from core.modules.approval_notifier import ApprovalNotifier
            ApprovalNotifier()
            # Module tickets are separate — include if available
        except Exception as _exc:
            log.warning("swallowed_exception", action="action_console_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        logger.warning(f"pending_list_failed: {e}")
        return {"pending": [], "count": 0, "error": str(e)}


@router.get("/history")
async def approval_history(
    limit: int = 50
):
    """Recent approval decisions."""
    try:
        from core.tool_permissions import get_tool_permissions
        return {"history": get_tool_permissions().get_history(limit=limit)}
    except Exception as e:
        return {"history": [], "error": str(e)}


@router.post("/approve/{request_id}")
async def approve_request(
    request_id: str,
    body: FeedbackRequest = FeedbackRequest()
):
    """Approve a pending tool execution request."""
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
    body: FeedbackRequest = FeedbackRequest()
):
    """Deny a pending tool execution request."""
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
):
    """Approval system statistics."""
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
    except Exception:
        result["active_budgets"] = 0
    return result


@router.get("/permissions")
async def list_permissions(
):
    """List all tool permission declarations."""
    try:
        from core.tool_permissions import get_tool_permissions
        return {"permissions": get_tool_permissions().list_all()}
    except Exception as e:
        return {"permissions": [], "error": str(e)}


@router.get("/deps")
async def dependency_health(
):
    """Module dependency health overview."""
    try:
        from core.tool_config_registry import get_config_registry
        return {"dependencies": get_config_registry().check_all(),
                "stats": get_config_registry().stats()}
    except Exception as e:
        return {"dependencies": {}, "error": str(e)}


@router.get("/budget/{mission_id}")
async def mission_budget(
    mission_id: str
):
    """Get budget status for a running mission."""
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
