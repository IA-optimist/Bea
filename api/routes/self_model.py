"""
api/routes/self_model.py — Self-Model API endpoints.

Exposes the Self-Model to REST consumers (admin UI, mobile, MetaOrchestrator).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from api._deps import require_auth

log = structlog.get_logger()
router = APIRouter(prefix="/api/v3/self-model", tags=["self-model"])


@router.get("")
async def get_self_model(_user: dict = Depends(require_auth)):
    """Full Self-Model snapshot."""
    from core.self_model import build_self_model, serialize
    model = build_self_model()
    return {"ok": True, "data": serialize.to_full_dict(model)}


@router.get("/compact")
async def get_compact(_user: dict = Depends(require_auth)):
    """Compact summary for lightweight consumers."""
    from core.self_model import build_self_model, serialize
    model = build_self_model()
    return {"ok": True, "data": serialize.to_compact(model)}


@router.get("/health-card")
async def get_health_card(_user: dict = Depends(require_auth)):
    """Health card for dashboard display."""
    from core.self_model import build_self_model, serialize
    model = build_self_model()
    return {"ok": True, "data": serialize.to_health_card(model)}


@router.get("/llm-context")
async def get_llm_context(_user: dict = Depends(require_auth)):
    """LLM-consumable text for injection into reasoning."""
    from core.self_model import build_self_model, serialize
    model = build_self_model()
    return {"ok": True, "data": {"context": serialize.to_llm_context(model)}}


@router.get("/capabilities")
async def get_capabilities(_user: dict = Depends(require_auth)):
    """All capabilities with their current status."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    return {
        "ok": True,
        "data": {
            "ready": query.what_can_i_do(model),
            "unavailable": query.what_cannot_i_do(model),
            "degraded": query.what_is_degraded(model),
            "approval_required": query.what_requires_approval(model),
            "summary": query.capability_summary(model),
        },
    }


@router.get("/boundaries")
async def get_boundaries(_user: dict = Depends(require_auth)):
    """Modification boundaries and autonomy envelope."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    return {
        "ok": True,
        "data": {
            "unsafe_to_modify": query.what_is_unsafe_to_modify(model),
            "autonomy": model.autonomy.to_dict(),
        },
    }


@router.get("/readiness")
async def get_readiness(_user: dict = Depends(require_auth)):
    """Overall readiness score and breakdown."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    return {
        "ok": True,
        "data": {
            "score": query.readiness_score(model),
            "capabilities": query.capability_summary(model),
            "components": query.component_summary(model),
            "health": query.health_summary(model),
        },
    }


@router.get("/summary")
async def get_summary(_user: dict = Depends(require_auth)):
    """Concise self-model summary with readiness, limitations, autonomy."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    return {
        "ok": True,
        "data": {
            "readiness_score": query.readiness_score(model),
            "capabilities": query.capability_summary(model),
            "components": query.component_summary(model),
            "health": query.get_runtime_health(model),
            "autonomy": query.get_autonomy_limits(model),
            "limitations_count": len(query.get_known_limitations(model)),
            "generation_ms": round(model.generation_duration_ms, 1),
        },
    }


@router.get("/runtime")
async def get_runtime(_user: dict = Depends(require_auth)):
    """Runtime health signals and component status."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    return {
        "ok": True,
        "data": {
            "health": query.get_runtime_health(model),
            "components": query.component_summary(model),
            "degraded": query.what_is_degraded(model),
            "missing": query.what_is_missing(model),
        },
    }


@router.get("/limitations")
async def get_limitations(_user: dict = Depends(require_auth)):
    """Known operational limitations derived from runtime state."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    limitations = query.get_known_limitations(model)
    return {
        "ok": True,
        "data": {
            "total": len(limitations),
            "limitations": limitations,
        },
    }


@router.get("/autonomy")
async def get_autonomy(_user: dict = Depends(require_auth)):
    """Current autonomy envelope and modification boundaries."""
    from core.self_model import build_self_model, query
    model = build_self_model()
    return {
        "ok": True,
        "data": {
            "autonomy": query.get_autonomy_limits(model),
            "boundaries": query.what_is_unsafe_to_modify(model),
            "blocked_capabilities": query.get_blocked_capabilities(model),
        },
    }
