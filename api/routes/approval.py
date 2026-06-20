"""API routes for approval queue."""
from fastapi import APIRouter, Depends
import logging

from api._deps import require_auth

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
async def approve_action(item_id: str, approved_by: str = "human"):
    """Approuve une action en attente."""
    try:
        from core.approval_queue import approve
        success = approve(item_id, approved_by)
        return {"success": success, "item_id": item_id}
    except Exception as e:
        logger.warning(f"[API] approval/approve error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/reject/{item_id}")
async def reject_action(item_id: str, rejected_by: str = "human"):
    """Rejette une action en attente."""
    try:
        from core.approval_queue import reject
        success = reject(item_id, rejected_by)
        return {"success": success, "item_id": item_id}
    except Exception as e:
        logger.warning(f"[API] approval/reject error: {e}")
        return {"success": False, "error": str(e)}
