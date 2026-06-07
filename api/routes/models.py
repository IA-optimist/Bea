"""
api/routes/models.py — Model intelligence API.

Endpoints under /api/v3/models/:
  GET  /catalog        — list available models
  POST /catalog/refresh — refresh from OpenRouter
  GET  /profiles       — model task profiles
  GET  /performance    — model performance stats
  GET  /recommendations — recommended models per task
  GET  /status         — model intelligence status
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

logger = structlog.get_logger("bea.api.models")
log = logger  # M3 emitter alias

# Fail-hard on auth import: silent fail-open to no-auth is a HIGH severity bug.
# Canonical auth helper lives in api._deps, not api.auth.
from api._deps import require_auth
_auth = Depends(require_auth)

router = APIRouter(
    prefix="/api/v3/models",
    tags=["models"],
    dependencies=[_auth],
)


@router.get("/catalog")
async def list_catalog(
    provider: str = "",
    cost_tier: str = "",
    search: str = "",
    limit: int = Query(50, ge=1, le=500),
):
    """List available models from catalog."""
    try:
        from core.model_intelligence.catalog import get_model_catalog
        catalog = get_model_catalog()
        if search:
            models = catalog.search(search)
        elif provider:
            models = catalog.list_by_provider(provider)
        elif cost_tier:
            models = catalog.list_by_cost_tier(cost_tier)
        else:
            models = catalog.list_all()
        return {
            "models": [m.to_dict() for m in models[:limit]],
            "total": len(models),
            "catalog_status": catalog.status(),
        }
    except Exception as e:
        logger.exception("model_catalog_list_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.post("/catalog/refresh")
async def refresh_catalog():
    """Refresh model catalog from OpenRouter."""
    try:
        from core.model_intelligence.catalog import get_model_catalog
        catalog = get_model_catalog()
        count = catalog.refresh()
        return {
            "refreshed": count >= 0,
            "model_count": count if count >= 0 else catalog.count,
            "status": catalog.status(),
        }
    except Exception as e:
        logger.exception("model_catalog_refresh_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.get("/profiles")
async def list_profiles(task_class: str = "", limit: int = 20):
    """List model profiles with task suitability scores."""
    try:
        from core.model_intelligence.catalog import get_model_catalog
        from core.model_intelligence.selector import build_profile
        catalog = get_model_catalog()
        profiles = []
        for entry in catalog.list_all():
            profile = build_profile(entry)
            if task_class and profile.score_for(task_class) < 0.3:
                continue
            profiles.append(profile.to_dict())
        profiles.sort(
            key=lambda p: p["scores"].get(task_class, 0) if task_class else max(p["scores"].values()),
            reverse=True,
        )
        return {"profiles": profiles[:limit]}
    except Exception as e:
        logger.exception("model_profiles_list_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.get("/performance")
async def list_performance(model_id: str = "", task_class: str = ""):
    """List model performance stats."""
    try:
        from core.model_intelligence.selector import get_model_performance
        perf = get_model_performance()
        if model_id:
            return {"stats": perf.get_stats(model_id, task_class)}
        if task_class:
            return {"stats": perf.get_best_for_task(task_class)}
        return {"stats": perf.get_all()}
    except Exception as e:
        logger.exception("model_performance_list_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.get("/recommendations")
async def get_recommendations(budget_mode: str = "normal"):
    """Get recommended models per task class for a given budget mode."""
    try:
        from core.model_intelligence.selector import get_model_selector, TASK_CLASSES
        selector = get_model_selector()
        valid_modes = ("budget", "normal", "critical")
        if budget_mode not in valid_modes:
            budget_mode = "normal"
        recs = []
        for tc in TASK_CLASSES:
            result = selector.select(tc, budget_mode)
            recs.append({
                "task_class": tc,
                "recommended_model": result.model_id,
                "score": result.final_score,
                "is_fallback": result.is_fallback,
                "rationale": result.rationale,
                "budget_mode": budget_mode,
            })
        return {"recommendations": recs, "budget_mode": budget_mode}
    except Exception as e:
        logger.exception("model_recommendations_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.get("/status")
async def model_status():
    """Model intelligence status summary."""
    try:
        from core.model_intelligence.catalog import get_model_catalog
        from core.model_intelligence.selector import get_model_performance
        catalog = get_model_catalog()
        perf = get_model_performance()
        auto_status = {}
        try:
            from core.model_intelligence.auto_update import get_model_auto_update
            auto_status = get_model_auto_update().get_status()
        except Exception as _exc:
            log.warning("swallowed_exception", action="models_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return {
            "catalog": catalog.status(),
            "performance_records": len(perf.get_all()),
            "active": catalog.count > 0,
            "auto_update": auto_status,
        }
    except Exception as e:
        logger.exception("model_status_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.get("/ab-tests")
async def list_ab_tests():
    """List active and completed A/B model tests."""
    try:
        from core.model_intelligence.auto_update import get_model_auto_update
        engine = get_model_auto_update()
        return {
            "ok": True,
            "active": {k: v.to_dict() for k, v in engine._active_tests.items()},
            "completed": [t.to_dict() for t in engine._completed_tests[-20:]],
            "candidates": engine.detect_ab_candidates(),
        }
    except Exception as e:
        logger.exception("model_auto_update_endpoint_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e


@router.get("/costs")
async def model_costs():
    """Real cost tracking across models."""
    try:
        from core.model_intelligence.auto_update import get_model_auto_update
        return {"ok": True, "costs": get_model_auto_update().get_real_cost_stats()}
    except Exception as e:
        logger.exception("model_costs_failed")
        raise HTTPException(status_code=500, detail="model_intelligence_error") from e
