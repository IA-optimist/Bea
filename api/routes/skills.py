"""
api/routes/skills.py — Skill system API endpoints.

Minimal introspection API for the skill system.
"""
from __future__ import annotations


import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from api._deps import _check_auth
from typing import Optional as _Opt
from fastapi import Header

def _auth(x_jarvis_token: _Opt[str] = Header(None), authorization: _Opt[str] = Header(None)):
    _check_auth(x_jarvis_token, authorization)


log = structlog.get_logger("api.skills")
router = APIRouter(tags=["skills"], dependencies=[Depends(_auth)])


def _svc():
    from core.skills import get_skill_service
    return get_skill_service()


@router.get("/api/v2/skills")
async def list_skills(limit: int = Query(50, ge=1, le=200)):
    """List all stored skills."""
    return {"ok": True, "data": _svc().list_skills(limit=limit)}


@router.get("/api/v2/skills/stats")
async def skills_stats():
    """Skill system statistics."""
    return {"ok": True, "data": _svc().stats()}


@router.get("/api/v2/skills/search")
async def search_skills(
    q: str = Query(..., min_length=2),
    top_k: int = Query(5, ge=1, le=20),
):
    """Search skills by semantic similarity."""
    results = _svc().search_skills(query=q, top_k=top_k)
    return {"ok": True, "data": results, "count": len(results)}


@router.get("/api/v2/skills/{skill_id}")
async def get_skill(skill_id: str):
    """Get one skill by ID."""
    skill = _svc().get_skill(skill_id)
    if not skill:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"ok": True, "data": skill}


@router.delete("/api/v2/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """Delete a skill."""
    ok = _svc().delete_skill(skill_id)
    if not ok:
        raise HTTPException(404, f"Skill {skill_id} not found")
    return {"ok": True}
