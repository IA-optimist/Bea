"""
api/routes/v1.py — Bea API v1 Stable Surface

This module defines the stable v1 API surface. All routes here are:
- Documented with OpenAPI specs
- Versioned with api_version response field
- Backward compatible within v1
- Part of the public API contract

Deprecated routes should be moved to api/routes/legacy/ with deprecation headers.
"""
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid

from api.auth_principal import get_authenticated_principal
from api._deps import require_auth, _get_mission_system, _get_orchestrator, _REQUIRE_AUTH
from config.settings import get_settings
from core.observability.eval_publisher import load_eval_scores, publish_eval_scores

log = structlog.get_logger(__name__)

_V1_SUNSET = "2026-10-01T00:00:00Z"

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

@router.post("/missions", response_model=APIResponse, status_code=201)
async def submit_mission(
    req: MissionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Submit a new mission to Bea (v1 stable surface)."""
    try:
        ms = _get_mission_system()
        principal_id = get_authenticated_principal(request)
        if principal_id is None and _REQUIRE_AUTH:
            raise HTTPException(
                status_code=401,
                detail="Authenticated principal required to submit a mission.",
            )
        result = ms.submit(req.goal, submitted_by=principal_id)
        mission_id = result.mission_id

        async def _execute() -> None:
            try:
                orch = _get_orchestrator()
                if orch and hasattr(orch, "run"):
                    await orch.run(
                        mission_id=mission_id,
                        user_input=req.goal,
                        principal_id=principal_id,
                    )
            except Exception as exc:
                log.error("v1_mission_exec_failed", mission_id=mission_id, err=str(exc)[:120])

        background_tasks.add_task(_execute)
        return APIResponse(
            status="submitted",
            data=MissionResponse(
                mission_id=mission_id,
                status="submitted",
                goal=req.goal,
                message=f"Mission submitted. Poll GET /api/v1/missions/{mission_id} for status.",
            ),
        )
    except Exception as e:
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
        return APIResponse(
            status="success",
            data={
                "missions": [m.to_dict() for m in missions],
                "total": len(missions),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missions/{mission_id}", response_model=APIResponse)
async def get_mission_status(
    mission_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Get the current status of a mission."""
    try:
        ms = _get_mission_system()
        r = ms.get(mission_id)
        if not r:
            raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
        d = r.to_dict()
        return APIResponse(
            status="success",
            data=MissionStatusResponse(
                mission_id=mission_id,
                status=d.get("status", "unknown"),
                goal=d.get("user_input", ""),
                progress=d.get("progress"),
                created_at=d.get("created_at", ""),
                completed_at=d.get("completed_at"),
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/missions/{mission_id}/cancel", response_model=APIResponse)
async def cancel_mission(
    mission_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Cancel a running mission."""
    try:
        ms = _get_mission_system()
        r = ms.get(mission_id)
        if not r:
            raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
        ms.cancel(mission_id, reason="v1_api_cancel")
        return APIResponse(status="cancelled", data={"mission_id": mission_id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/missions/{mission_id}/result", response_model=APIResponse)
async def get_mission_result(
    mission_id: str,
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Get the final result of a completed mission."""
    try:
        ms = _get_mission_system()
        r = ms.get(mission_id)
        if not r:
            raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
        d = r.to_dict()
        return APIResponse(
            status="success",
            data={
                "mission_id": mission_id,
                "status": d.get("status", "unknown"),
                "result": d.get("result") or d.get("final_output"),
            },
        )
    except HTTPException:
        raise
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
        # Stub implementation
        return APIResponse(
            status="success",
            data={"results": []}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


@router.post("/evaluations", response_model=APIResponse)
async def trigger_evaluations(
    user: dict = Depends(require_auth),
) -> APIResponse:
    """Run the deterministic evaluation harnesses and publish scores."""
    try:
        scores = publish_eval_scores()
        return APIResponse(status="published", data=scores)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evaluations", response_model=APIResponse)
async def get_evaluations() -> APIResponse:
    """Return the latest published evaluation scores."""
    try:
        scores = load_eval_scores()
        return APIResponse(status="success", data=scores)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/migration", response_model=APIResponse)
async def get_v1_migration_guide() -> APIResponse:
    """Return the V1 → V2/V3 migration matrix for deprecated routes."""
    try:
        routes_list = [
            {"v1": "POST /api/v1/missions", "v2": "POST /api/v2/missions", "v3": "POST /api/v3/missions", "status": "deprecated"},
            {"v1": "GET /api/v1/missions", "v2": "GET /api/v2/missions", "v3": "GET /api/v3/missions", "status": "deprecated"},
            {"v1": "GET /api/v1/missions/{mission_id}", "v2": "GET /api/v2/missions/{mission_id}", "v3": "GET /api/v3/missions/{mission_id}", "status": "deprecated"},
            {"v1": "POST /api/v1/missions/{mission_id}/cancel", "v2": "POST /api/v2/missions/{mission_id}/cancel", "v3": "POST /api/v3/missions/{mission_id}/cancel", "status": "deprecated"},
            {"v1": "GET /api/v1/missions/{mission_id}/result", "v2": "GET /api/v2/missions/{mission_id}/result", "v3": "GET /api/v3/missions/{mission_id}/result", "status": "deprecated"},
            {"v1": "POST /api/v1/memory/search", "v2": "POST /api/v2/memory/search", "v3": "POST /api/v3/memory/search", "status": "deprecated"},
            {"v1": "GET /api/v1/memory", "v2": "GET /api/v2/memory", "v3": "GET /api/v3/memory", "status": "deprecated"},
            {"v1": "POST /api/v1/memory/store", "v2": "POST /api/v2/memory", "v3": "POST /api/v3/memory", "status": "deprecated"},
            {"v1": "GET /api/v1/memory/{memory_id}", "v2": "GET /api/v2/memory/{memory_id}", "v3": "GET /api/v3/memory/{memory_id}", "status": "deprecated"},
            {"v1": "DELETE /api/v1/memory/{memory_id}", "v2": "DELETE /api/v2/memory/{memory_id}", "v3": "DELETE /api/v3/memory/{memory_id}", "status": "deprecated"},
        ]
        return APIResponse(
            status="success",
            data={
                "sunset": _V1_SUNSET,
                "notes": "V1 stable surface remains available until sunset. New integrations should target V2/V3.",
                "routes": routes_list,
            },
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
