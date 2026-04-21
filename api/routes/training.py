"""
JARVIS MAX — Training & Cognitive Consolidation API Routes
Exposes bio-inspired learning mechanisms over HTTP.

Routes:
    POST /api/v3/training/consolidate  — Run nightly consolidation (admin only)
    GET  /api/v3/training/workspace     — Get global workspace stats
    GET  /api/v3/training/workspace/recent — Get recent workspace broadcasts
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import Depends, APIRouter, Query
from api._deps import require_auth, require_admin

log = structlog.get_logger(__name__)


router = APIRouter(prefix="/api/v3/training", tags=["training"])


# ── Cognitive Consolidation ───────────────────────────────────────

@router.post("/consolidate")
async def run_consolidation(user: dict = Depends(require_admin)):
    """
    Trigger nightly cognitive consolidation (hippocampal replay).
    
    Mimics the brain's sleep consolidation process:
    - Reads recent mission traces (last 24h)
    - Extracts patterns by domain (count, avg_score, top lessons, failures)
    - Computes dopamine signals (reward prediction error)
    - Saves summary to workspace/consolidation_log.jsonl
    
    Admin-only. Normally runs via cron at 3am UTC.
    """
    try:
        from core.cognitive_consolidation import run_nightly_consolidation
        
        log.info("consolidation.triggered_via_api", trigger="manual")
        result = await run_nightly_consolidation()
        
        return {
            "ok": True,
            "data": result,
            "message": "Consolidation complete"
        }
    except Exception as e:
        log.error("consolidation.endpoint_failed", error=str(e)[:200])
        return {
            "ok": False,
            "error": str(e)[:200]
        }


# ── Global Workspace Theory ───────────────────────────────────────

@router.get("/workspace")
async def get_workspace_stats(user: dict = Depends(require_auth)):
    """
    Get global workspace statistics.
    
    Global Workspace Theory: Agents publish outputs to a shared "conscious"
    workspace where other agents can read and coordinate.
    
    Returns:
        - Total entries in workspace
        - Unique agents seen
        - Average confidence
        - Age of oldest entry
    """
    try:
        from core.global_workspace import get_workspace
        
        workspace = get_workspace()
        stats = await workspace.get_stats()
        
        return {
            "ok": True,
            "data": stats
        }
    except Exception as e:
        log.error("workspace_stats.endpoint_failed", error=str(e)[:200])
        return {
            "ok": False,
            "error": str(e)[:200]
        }


@router.get("/workspace/recent")
async def get_recent_broadcasts(
    limit: int = Query(10, ge=1, le=50),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    agent: Optional[str] = Query(None),
    user: dict = Depends(require_auth)
):
    """
    Get recent broadcasts from the global workspace.
    
    Allows agents and users to see what other agents have recently published,
    enabling coordination and shared context (consciousness metaphor).
    
    Query params:
        - limit: Max entries to return (1-50, default 10)
        - min_confidence: Filter by minimum confidence (0.0-1.0)
        - agent: Filter by specific agent name
    """
    try:
        from core.global_workspace import get_workspace
        
        workspace = get_workspace()
        broadcasts = await workspace.get_recent(
            limit=limit,
            min_confidence=min_confidence,
            agent_filter=agent
        )
        
        return {
            "ok": True,
            "data": {
                "broadcasts": broadcasts,
                "count": len(broadcasts)
            }
        }
    except Exception as e:
        log.error("workspace_recent.endpoint_failed", error=str(e)[:200])
        return {
            "ok": False,
            "error": str(e)[:200]
        }


@router.get("/workspace/high_confidence")
async def get_high_confidence_broadcasts(
    threshold: float = Query(0.8, ge=0.0, le=1.0),
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(require_auth)
):
    """
    Get high-confidence broadcasts (attention mechanism).
    
    In Global Workspace Theory, high-confidence broadcasts are more
    "prominent" in the workspace, analogous to attentional selection.
    """
    try:
        from core.global_workspace import get_workspace
        
        workspace = get_workspace()
        broadcasts = await workspace.get_high_confidence(
            threshold=threshold,
            limit=limit
        )
        
        return {
            "ok": True,
            "data": {
                "broadcasts": broadcasts,
                "count": len(broadcasts),
                "threshold": threshold
            }
        }
    except Exception as e:
        log.error("workspace_high_confidence.endpoint_failed", error=str(e)[:200])
        return {
            "ok": False,
            "error": str(e)[:200]
        }


# ── Training Data Collection Statistics ───────────────────────────

@router.get("/stats")
async def get_training_stats(user: dict = Depends(require_auth)):
    """
    Get training data collection statistics.
    
    Returns progress toward the 1000-example goal for fine-tuning Qwen 2.5 Coder 32B.
    Shows breakdown by domain (security, code, business, research, ops, general).
    
    Example response:
    ```json
    {
        "ok": true,
        "data": {
            "total": 127,
            "by_domain": {
                "code": 45,
                "security": 23,
                "business": 18,
                "research": 15,
                "ops": 12,
                "general": 14
            },
            "progress": 12.7,
            "next_milestone": 250,
            "goal": 1000
        }
    }
    ```
    """
    try:
        from core.training_data_collector import get_training_stats
        stats = get_training_stats()
        log.info(
            "training_stats.requested",
            user_id=user.get("sub"),
            total=stats.get("total", 0)
        )
        return {
            "ok": True,
            "data": stats
        }
    except Exception as e:
        log.error("training_stats.failed", error=str(e)[:200], exc_info=True)
        return {
            "ok": False,
            "error": str(e)[:200],
            "data": {
                "total": 0,
                "by_domain": {},
                "progress": 0.0,
                "next_milestone": 100,
                "goal": 1000
            }
        }
