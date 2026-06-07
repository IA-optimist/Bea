"""
BeaMax - Projects API Routes
RESTful API for project management with Bearer token authentication.

Endpoints:
- POST   /api/v3/projects       - Create project
- GET    /api/v3/projects       - List all projects
- GET    /api/v3/projects/{id}  - Get project by ID
- PUT    /api/v3/projects/{id}  - Update project
- DELETE /api/v3/projects/{id}  - Delete project (soft delete)
"""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Header, Query, Depends, Response
from pydantic import BaseModel, Field

from api._deps import require_auth

log = structlog.get_logger(__name__)

# Import project model
try:
    from models.project import (
        Project,  # noqa: F401
        ProjectConfig,  # noqa: F401
        ProjectMetadata,  # noqa: F401
        create_project,
        get_project,
        get_project_by_name,
        list_projects,
        update_project,
        delete_project
    )
except ImportError as e:
    log.error("failed_to_import_project_model", err=str(e))
    raise

# Create router with real auth dependency (uses canonical require_auth from api._deps)
router = APIRouter(
    prefix="/api/v3/projects",
    tags=["projects"],
    dependencies=[Depends(require_auth)],
)


# Request/Response Models

class CreateProjectRequest(BaseModel):
    """Request body for creating a project."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


class UpdateProjectRequest(BaseModel):
    """Request body for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    """Response model for project data."""
    id: str
    name: str
    description: Optional[str]
    config: dict[str, Any]
    metadata: dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    """Response model for project list."""
    projects: list[ProjectResponse]
    total: int


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    details: Optional[str] = None


# Authentication is now enforced at router level via api._deps.require_auth.
# The previous verify_token() function was a CRITICAL BYPASS that accepted
# any Bearer token starting with 'jv-' without backend verification.
# All endpoints now rely on the canonical require_auth (constant-time compare,
# JWT validation, access token verification via TokenManager).
#
# For backward compatibility with internal in-function calls, we keep a
# fail-closed stub that always rejects. Endpoints should use the router-level
# dependency instead.

def verify_token(authorization: Optional[str]) -> bool:
    """DEPRECATED — always returns False.

    The canonical auth is Depends(require_auth) from api._deps at the router
    level. This stub exists only for backward compatibility with legacy
    in-function auth checks. Do not use for new code.
    """
    return False


# Route Handlers

@router.post("", response_model=ProjectResponse, status_code=201, dependencies=[])
async def create_project_endpoint(
    request: CreateProjectRequest,
    authorization: Optional[str] = Header(None)
) -> ProjectResponse:
    """
    Create a new project.
    
    Requires Bearer token authentication.
    """
    try:
        project = create_project(
            name=request.name,
            description=request.description,
            config=request.config,
            metadata=request.metadata
        )
        
        return ProjectResponse(
            id=str(project.id),
            name=project.name,
            description=project.description,
            config=project.config.model_dump(),
            metadata=project.metadata.model_dump(),
            is_active=project.is_active,
            created_at=project.created_at.isoformat(),
            updated_at=project.updated_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("create_project_endpoint_failed", err=str(e))
        raise HTTPException(status_code=500, detail="Failed to create project")


@router.get("", response_model=ProjectListResponse, dependencies=[])
async def list_projects_endpoint(
    authorization: Optional[str] = Header(None),
    active_only: bool = Query(True, description="Only return active projects")
) -> ProjectListResponse:
    """
    List all projects.
    
    Requires Bearer token authentication.
    """
    try:
        projects = list_projects(active_only=active_only)
        
        return ProjectListResponse(
            projects=[
                ProjectResponse(
                    id=str(p.id),
                    name=p.name,
                    description=p.description,
                    config=p.config.model_dump(),
                    metadata=p.metadata.model_dump(),
                    is_active=p.is_active,
                    created_at=p.created_at.isoformat(),
                    updated_at=p.updated_at.isoformat()
                )
                for p in projects
            ],
            total=len(projects)
        )
    except Exception as e:
        log.error("list_projects_endpoint_failed", err=str(e))
        raise HTTPException(status_code=500, detail="Failed to list projects")


@router.get("/{project_id}", response_model=ProjectResponse, dependencies=[])
async def get_project_endpoint(
    project_id: str,
    authorization: Optional[str] = Header(None)
) -> ProjectResponse:
    """
    Get a project by ID.
    
    Requires Bearer token authentication.
    """
    try:
        # Try UUID lookup first, then name lookup
        try:
            UUID(project_id)
            project = get_project(project_id)
        except ValueError:
            # Not a UUID, try as name
            project = get_project_by_name(project_id)
        
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        
        return ProjectResponse(
            id=str(project.id),
            name=project.name,
            description=project.description,
            config=project.config.model_dump(),
            metadata=project.metadata.model_dump(),
            is_active=project.is_active,
            created_at=project.created_at.isoformat(),
            updated_at=project.updated_at.isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("get_project_endpoint_failed", project_id=project_id, err=str(e))
        raise HTTPException(status_code=500, detail="Failed to get project")


@router.put("/{project_id}", response_model=ProjectResponse, dependencies=[])
async def update_project_endpoint(
    project_id: str,
    request: UpdateProjectRequest,
    authorization: Optional[str] = Header(None)
) -> ProjectResponse:
    """
    Update a project.
    
    Requires Bearer token authentication.
    """
    try:
        project = update_project(
            project_id=project_id,
            name=request.name,
            description=request.description,
            config=request.config,
            metadata=request.metadata,
            is_active=request.is_active
        )
        
        if not project:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        
        return ProjectResponse(
            id=str(project.id),
            name=project.name,
            description=project.description,
            config=project.config.model_dump(),
            metadata=project.metadata.model_dump(),
            is_active=project.is_active,
            created_at=project.created_at.isoformat(),
            updated_at=project.updated_at.isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("update_project_endpoint_failed", project_id=project_id, err=str(e))
        raise HTTPException(status_code=500, detail="Failed to update project")


@router.delete(
    "/{project_id}",
    status_code=204,
    # C4 (FastAPI 0.115 bump): 0.115 asserts that a 204 endpoint cannot
    # ship a response_model. The default response model is inferred from
    # the function signature; even with `-> None` the inference can flag
    # this as needing a body. We pin response_model=None explicitly and
    # use the body-less Response class so the contract is unambiguous.
    response_model=None,
    response_class=Response,
    dependencies=[],
)
async def delete_project_endpoint(
    project_id: str,
    authorization: Optional[str] = Header(None),
    hard_delete: bool = Query(False, description="Permanently delete instead of soft delete")
) -> None:
    """
    Delete a project (soft delete by default).
    
    Requires Bearer token authentication.
    Use ?hard_delete=true to permanently delete.
    """
    try:
        success = delete_project(project_id, hard_delete=hard_delete)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        
        return None
    except HTTPException:
        raise
    except Exception as e:
        log.error("delete_project_endpoint_failed", project_id=project_id, err=str(e))
        raise HTTPException(status_code=500, detail="Failed to delete project")


# Health check endpoint (no auth required)
@router.get("/health", status_code=200, include_in_schema=False)
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "projects"}

# Project context switching endpoint
@router.post("/{project_id}/switch")
async def switch_project(
    project_id: str,
    authorization: Optional[str] = Header(None)
):
    """Switch current project context."""
    from core.project_context import set_project
    # get_project imported from models.project at top
    
    # Validate project exists
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Set context
    set_project(project_id)
    
    return {
        "ok": True,
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description
        },
        "message": f"Switched to project: {project.name}"
    }
