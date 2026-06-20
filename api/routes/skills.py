"""
api/routes/skills.py — Skill system API endpoints.

Minimal introspection API for the skill system.
"""
from __future__ import annotations

from typing import Any, Optional
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Header

from api._deps import _check_auth

def _auth(x_bea_token: Optional[str] = Header(None), authorization: Optional[str] = Header(None)) -> None:
    _check_auth(x_bea_token, authorization)


log = structlog.get_logger("api.skills")
router = APIRouter(tags=["skills"], dependencies=[Depends(_auth)])


def _svc() -> Any:
    from core.skills import get_skill_service
    return get_skill_service()


@router.get("/api/v2/skills")  # type: ignore[untyped-decorator]
async def list_skills(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """List all stored skills."""
    return {"ok": True, "data": _svc().list_skills(limit=limit)}


@router.get("/api/v2/skills/stats")  # type: ignore[untyped-decorator]
async def skills_stats() -> dict[str, Any]:
    """Skill system statistics."""
    return {"ok": True, "data": _svc().stats()}


@router.get("/api/v2/skills/search")  # type: ignore[untyped-decorator]
async def search_skills(
    q: str = Query(..., min_length=2),
    top_k: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Search skills by semantic similarity."""
    results = _svc().search_skills(query=q, top_k=top_k)
    return {"ok": True, "data": results, "count": len(results)}


@router.get("/api/v2/skills/{skill_id}")  # type: ignore[untyped-decorator]
async def get_skill(skill_id: str) -> dict[str, Any]:
    """Get one skill by ID."""
    skill = _svc().get_skill(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"ok": True, "data": skill}


@router.delete("/api/v2/skills/{skill_id}")  # type: ignore[untyped-decorator]
async def delete_skill(skill_id: str) -> dict[str, Any]:
    """Delete a skill."""
    ok = _svc().delete_skill(skill_id)
    if not ok:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"ok": True}
