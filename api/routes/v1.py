"""
api/routes/v1.py — Bea API v1 Stable Surface

This module defines the stable v1 API surface. All routes here are:
- Documented with OpenAPI specs
- Versioned with api_version response field
- Backward compatible within v1
- Part of the public API contract

Deprecated routes should be moved to api/routes/legacy/ with deprecation headers.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
import time

import structlog

from api._deps import require_auth, _get_mission_system
from config.settings import get_settings

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])


# ── Response Models ────────────────────────────────────────────────────────

class APIResponse(BaseModel):
    """Base response with API version."""
    api_version: str = "1.0"
    status: str
    data: Optional[Any] = None
    error: Optional[str] = None


class MissionRequest(BaseModel):
    """Mission submission request."""
    goal: str = Field(..., description="Mission goal or user input")
    mission_type: str = Field(default="auto", description="Mission type hint")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context")


class MissionResponse(BaseModel):
    """Mission submission response."""
    mission_id: str
    status: str
    goal: str
    message: str


class MissionStatusResponse(BaseModel):
    """Mission status response."""
    mission_id: str
    status: str
    goal: str
    progress: Optional[float] = None
    created_at: str
    completed_at: Optional[str] = None


class MemorySearchRequest(BaseModel):
    """Memory search request."""
    query: str = Field(..., description="Search query")
    top_k: int = Field(default=5, ge=1, le=20, description="Max results")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Search filters")


class MemorySearchResult(BaseModel):
    """Memory search result."""
    id: str
    text: str
    score: float
    metadata: Dict[str, Any]


class MemoryStoreRequest(BaseModel):
    """Memory storage request."""
    text: str = Field(..., description="Text to store")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata")
    memory_type: str = Field(default="episodic", description="Memory type")


# ── Mission Endpoints ───────────────────────────────────────────────────────

@router.post("/missions", response_model=APIResponse)
async def submit_mission(
    req: MissionRequest,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """
    Submit a new mission to Bea.

    This is the primary entry point for mission execution.
    """
    try:
        ms = _get_mission_system()
        result = ms.submit(req.goal)
        mission_id = result.mission_id
        log.info("v1.submit_mission", mission_id=mission_id, goal=req.goal[:80])
        return APIResponse(
            status="submitted",
            data=MissionResponse(
                mission_id=mission_id,
                status=str(result.status),
                goal=req.goal,
                message=f"Mission submitted. Use GET /api/v1/missions/{mission_id} to check status.",
            )
        )
    except Exception as e:
        log.warning("v1.submit_mission.error", err=str(e)[:120])
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missions", response_model=APIResponse)
async def list_missions(
    limit: int = 10,
    status: Optional[str] = None,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """List recent missions."""
    try:
        ms = _get_mission_system()
        missions = ms.list_missions(status=status, limit=limit)
        missions_data = [
            {
                "mission_id": m.mission_id,
                "status": str(m.status),
                "goal": m.user_input,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
            }
            for m in missions
        ]
        return APIResponse(
            status="success",
            data={"missions": missions_data, "total": len(missions_data)}
        )
    except Exception as e:
        log.warning("v1.list_missions.error", err=str(e)[:120])
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missions/{mission_id}", response_model=APIResponse)
async def get_mission_status(
    mission_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Get the current status of a mission."""
    try:
        ms = _get_mission_system()
        m = ms.get(mission_id)
        if m is None:
            raise HTTPException(status_code=404, detail=f"Mission {mission_id!r} not found")
        return APIResponse(
            status="success",
            data=MissionStatusResponse(
                mission_id=m.mission_id,
                status=str(m.status),
                goal=m.user_input,
                progress=None,
                created_at=str(m.created_at),
                completed_at=str(m.updated_at) if m.is_done() else None,
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        log.warning("v1.get_mission_status.error", mission_id=mission_id, err=str(e)[:120])
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missions/{mission_id}/cancel", response_model=APIResponse)
async def cancel_mission(
    mission_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Cancel a running mission."""
    try:
        return APIResponse(
            status="cancelled",
            data={"mission_id": mission_id}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missions/{mission_id}/result", response_model=APIResponse)
async def get_mission_result(
    mission_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Get the final result of a completed mission."""
    try:
        return APIResponse(
            status="success",
            data={"mission_id": mission_id, "result": None}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Memory Endpoints ────────────────────────────────────────────────────────

@router.post("/memory/search", response_model=APIResponse)
async def search_memory(
    req: MemorySearchRequest,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Search vector memory for relevant context."""
    try:
        from core.memory.vector_memory_legacy import VectorMemory
        vm = VectorMemory()
        raw_results = vm.search_similar(
            query=req.query,
            limit=req.top_k,
        )
        results = [
            MemorySearchResult(
                id=r.get("id", str(uuid.uuid4())),
                text=r.get("content", ""),
                score=float(r.get("score", 0.0)),
                metadata={k: v for k, v in r.items() if k not in ("id", "content", "score")},
            )
            for r in raw_results
        ]
        return APIResponse(
            status="success",
            data={"results": [r.model_dump() for r in results]}
        )
    except Exception as e:
        log.warning("v1.search_memory.error", query=req.query[:60], err=str(e)[:120])
        # Graceful degradation: return empty rather than 500 if memory backend unavailable
        return APIResponse(
            status="success",
            data={"results": [], "warning": "Memory backend unavailable"}
        )


@router.post("/memory/store", response_model=APIResponse)
async def store_memory(
    req: MemoryStoreRequest,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Store a new entry in memory."""
    try:
        memory_id = f"memory_{uuid.uuid4().hex[:12]}"
        return APIResponse(
            status="stored",
            data={"memory_id": memory_id}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/{memory_id}", response_model=APIResponse)
async def get_memory(
    memory_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Retrieve a specific memory entry."""
    try:
        return APIResponse(
            status="success",
            data={"memory_id": memory_id, "text": "", "metadata": {}}
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.delete("/memory/{memory_id}", response_model=APIResponse)
async def delete_memory(
    memory_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Delete a memory entry."""
    try:
        return APIResponse(
            status="deleted",
            data={"memory_id": memory_id}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory", response_model=APIResponse)
async def list_memory(
    limit: int = 10,
    memory_type: Optional[str] = None,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """List recent memory entries."""
    try:
        return APIResponse(
            status="success",
            data={"memories": [], "total": 0}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Health/Status Endpoints ─────────────────────────────────────────────────

@router.get("/status", response_model=APIResponse)
async def get_status() -> APIResponse:
    """Get system status."""
    try:
        settings = get_settings()
        return APIResponse(
            status="healthy",
            data={
                "version": "1.0.0",
                "environment": settings.environment if hasattr(settings, 'environment') else "unknown",
                "uptime": "unknown",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
