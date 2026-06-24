"""API routes for approval queue."""
from fastapi import APIRouter, Depends, Request
import logging

from api._deps import require_auth
from api.auth_principal import get_authenticated_principal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/approval", tags=["approval"], dependencies=[Depends(require_auth)])


@router.get("/pending")
async def get_pending_approvals():
    """Liste toutes les actions en attente d'approbation humaine."""
    try:
        from core.approval_queue import get_pending
        items = get_pending()
        return {"pending": items, "count": len(items)}
    except Exception as e:
        logger.warning(f"[API] approval/pending error: {e}")
        return {"pending": [], "count": 0, "error": str(e)}


@router.post("/approve/{item_id}")
async def approve_action(request: Request, item_id: str):
    """Approuve une action en attente.

    approved_by is derived from the authenticated request context, never
    accepted as a client-supplied query parameter.
    """
    approved_by = get_authenticated_principal(request) or "authenticated_user"
    try:
        from core.approval_queue import approve
        success = approve(item_id, approved_by)
        return {"success": success, "item_id": item_id}
    except Exception as e:
        logger.warning(f"[API] approval/approve error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/reject/{item_id}")
async def reject_action(request: Request, item_id: str):
    """Rejette une action en attente.

    rejected_by is derived from the authenticated request context, never
    accepted as a client-supplied query parameter.
    """
    rejected_by = get_authenticated_principal(request) or "authenticated_user"
    try:
        from core.approval_queue import reject
        success = reject(item_id, rejected_by)
        return {"success": success, "item_id": item_id}
    except Exception as e:
        logger.warning(f"[API] approval/reject error: {e}")
        return {"success": False, "error": str(e)}
