"""
Objective Engine — API Router.
Endpoints GET/POST pour la gestion des objectifs.
Fail-open : si l'engine est indisponible, retourne 503 gracieux.
Aucun breaking change sur les routes existantes.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api._deps import _check_auth
from typing import Optional as _Opt
from fastapi import Header

def _auth(x_jarvis_token: _Opt[str] = Header(None), authorization: _Opt[str] = Header(None)):
    _check_auth(x_jarvis_token, authorization)


logger = logging.getLogger("jarvis.api.objectives")

router = APIRouter(prefix="/api/v2/objectives", tags=["objectives"], dependencies=[Depends(_auth)])

# ── Import fail-open ───────────────────────────────────────────────────────────

_ENGINE_AVAILABLE = False
try:
    from core.objectives.objective_engine import get_objective_engine
    from core.objectives.objective_cleanup import run_cleanup
    _ENGINE_AVAILABLE = True
except ImportError as _e:
    logger.warning(f"[API_OBJECTIVES] engine not available: {_e}")


def _engine():
    """Retourne l'engine ou lève 503."""
    if not _ENGINE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Objective Engine not available")
    try:
        return get_objective_engine()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Engine error: {str(e)[:100]}")


# ── Schémas Pydantic ───────────────────────────────────────────────────────────

class CreateObjectiveRequest(BaseModel):
    title:           str             = Field(..., min_length=1, max_length=200)
    description:     str             = Field("", max_length=1000)
    category:        str             = Field("general")
    priority_score:  float           = Field(0.5, ge=0.0, le=1.0)
    source:          str             = Field("user")
    owner:           str             = Field("jarvis")
    success_criteria: str            = Field("")
    depends_on:      List[str]       = Field(default_factory=list)
    auto_breakdown:  bool            = Field(True)


class ObjectiveResponse(BaseModel):
    objective_id:    str
    title:           str
    status:          str
    priority_score:  float
    difficulty_score: float
    category:        str
    current_progress: float
    sub_objectives_count: int
    created_at:      float
    updated_at:      float


# ── Helpers ────────────────────────────────────────────────────────────────────

def _obj_to_response(obj_dict: dict) -> dict:
    """Convertit un dict d'objectif en réponse API allégée."""
    subs = obj_dict.get("sub_objectives", [])
    return {
        "objective_id":        obj_dict.get("objective_id"),
        "title":               obj_dict.get("title"),
        "description":         obj_dict.get("description", ""),
        "status":              obj_dict.get("status"),
        "priority_score":      obj_dict.get("priority_score"),
        "difficulty_score":    obj_dict.get("difficulty_score"),
        "category":            obj_dict.get("category"),
        "current_progress":    obj_dict.get("current_progress"),
        "sub_objectives_count": len(subs),
        "next_recommended_action": obj_dict.get("next_recommended_action", ""),
        "blocked_by":          obj_dict.get("blocked_by", []),
        "created_at":          obj_dict.get("created_at"),
        "updated_at":          obj_dict.get("updated_at"),
        "archived":            obj_dict.get("archived", False),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", summary="Liste tous les objectifs")
async def list_objectives(include_archived: bool = False) -> dict:
    """Retourne tous les objectifs triés par priorité."""
    try:
        eng = _engine()
        objectives = eng.get_all(include_archived=include_archived)
        return {
            "ok":    True,
            "count": len(objectives),
            "objectives": [_obj_to_response(o.to_dict()) for o in objectives],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active", summary="Liste les objectifs actifs")
async def list_active_objectives() -> dict:
    """Retourne les objectifs actifs (NEW, ACTIVE, WAITING_APPROVAL)."""
    try:
        eng = _engine()
        objectives = eng.get_active()
        return {
            "ok":    True,
            "count": len(objectives),
            "objectives": [_obj_to_response(o.to_dict()) for o in objectives],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{objective_id}", summary="Détail d'un objectif")
async def get_objective(objective_id: str) -> dict:
    """Retourne le détail complet d'un objectif avec ses sous-objectifs."""
    try:
        eng = _engine()
        obj = eng.get(objective_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=f"Objective {objective_id} not found")
        return {"ok": True, "objective": obj.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", summary="Créer un objectif")
async def create_objective(req: CreateObjectiveRequest) -> dict:
    """Crée un nouvel objectif et lance son breakdown automatique."""
    try:
        eng = _engine()
        obj = eng.create(
            title           = req.title,
            description     = req.description,
            category        = req.category,
            priority_score  = req.priority_score,
            source          = req.source,
            owner           = req.owner,
            success_criteria = req.success_criteria,
            depends_on      = req.depends_on,
            auto_breakdown  = req.auto_breakdown,
        )
        if obj is None:
            raise HTTPException(status_code=500, detail="Failed to create objective")
        return {
            "ok":           True,
            "objective_id": obj.objective_id,
            "objective":    _obj_to_response(obj.to_dict()),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{objective_id}/pause", summary="Mettre en pause un objectif")
async def pause_objective(objective_id: str, reason: str = "") -> dict:
    try:
        eng = _engine()
        ok = eng.pause(objective_id, reason)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Objective {objective_id} not found or cannot be paused")
        return {"ok": True, "objective_id": objective_id, "status": "PAUSED"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{objective_id}/resume", summary="Reprendre un objectif")
async def resume_objective(objective_id: str) -> dict:
    try:
        eng = _engine()
        ok = eng.resume(objective_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Objective {objective_id} not found or not paused")
        return {"ok": True, "objective_id": objective_id, "status": "ACTIVE"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{objective_id}/archive", summary="Archiver un objectif")
async def archive_objective(objective_id: str, reason: str = "") -> dict:
    try:
        eng = _engine()
        ok = eng.archive(objective_id, reason)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Objective {objective_id} not found")
        return {"ok": True, "objective_id": objective_id, "status": "ARCHIVED"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{objective_id}/next-action", summary="Prochaine action recommandée")
async def get_next_action(objective_id: str) -> dict:
    """Retourne la next best action pour un objectif spécifique."""
    try:
        eng = _engine()
        obj = eng.get(objective_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=f"Objective {objective_id} not found")
        nba = eng.get_next_best_action(goal_hint=obj.title)
        return {"ok": True, "next_action": nba}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{objective_id}/history", summary="Historique d'un objectif")
async def get_objective_history(objective_id: str) -> dict:
    """Retourne l'historique complet d'un objectif."""
    try:
        eng = _engine()
        history = eng.get_history(objective_id)
        summary = eng.get_history_summary(objective_id)
        return {
            "ok":            True,
            "objective_id":  objective_id,
            "history_count": len(history),
            "summary":       summary,
            "history":       history,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
