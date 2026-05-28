"""
api/routes/economic.py — Economic intelligence API.

Endpoints under /api/v3/economic/:
  GET  /memory           — list strategic records
  GET  /memory/{id}      — get specific record
  GET  /recommendations  — strategy recommendations
  GET  /chains           — list built-in playbook chains
  POST /chains/{id}/run  — execute a playbook chain
  GET  /kpis/{obj_id}    — KPI summary for objective
  GET  /trace/{run_id}   — decision trace for a run
  GET  /validation/{pb}  — validate playbook output schema
  GET  /stats            — all strategy type stats
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("jarvis.api.economic")

# Fail-hard on auth import: silent fail-open to no-auth is a HIGH severity bug.
# Canonical auth helper lives in api._deps, not api.auth.
from api._deps import require_auth
_auth = Depends(require_auth)

router = APIRouter(
    prefix="/api/v3/economic",
    tags=["economic"],
    dependencies=[_auth],
)


# ── Strategic Memory ──────────────────────────────────────────

@router.get("/memory")
async def list_strategic_records(
    strategy_type: str = "",
    min_score: float = 0.0,
    limit: int = Query(20, ge=1, le=100),
):
    """List strategic memory records."""
    try:
        from core.economic.strategic_memory import get_strategic_memory
        mem = get_strategic_memory()
        records = mem.query(
            strategy_type=strategy_type,
            min_score=min_score,
            limit=limit,
        )
        return {
            "records": [r.to_dict() for r in records],
            "total": mem.count,
        }
    except Exception as e:
        return {"records": [], "total": 0, "error": str(e)[:100]}


@router.get("/memory/similar")
async def find_similar_strategies(goal: str = "", limit: int = 5):
    """Find similar past strategies."""
    try:
        from core.economic.strategic_memory import get_strategic_memory
        return get_strategic_memory().find_similar(goal, limit=limit)
    except Exception as e:
        return {"results": [], "error": str(e)[:100]}


# ── Strategy Recommendations ──────────────────────────────────

@router.get("/recommendations")
async def get_recommendations():
    """Get strategy evaluations and recommendations for all types."""
    try:
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        results = evaluator.evaluate_all()
        return {
            "evaluations": [r.to_dict() for r in results],
        }
    except Exception as e:
        return {"evaluations": [], "error": str(e)[:100]}


@router.get("/recommendations/suggest")
async def suggest_playbook(goal: str = ""):
    """Suggest best playbook for a goal."""
    try:
        from core.economic.strategy_evaluation import get_strategy_evaluator
        rec = get_strategy_evaluator().suggest_next_playbook(goal)
        return rec.to_dict() if rec else {"recommendation": None}
    except Exception as e:
        return {"error": str(e)[:100]}


# ── Playbook Chains ───────────────────────────────────────────

@router.get("/chains")
async def list_chains():
    """List built-in playbook chains."""
    try:
        from core.economic.playbook_composition import BUILT_IN_CHAINS
        return {
            "chains": {
                cid: c.to_dict() for cid, c in BUILT_IN_CHAINS.items()
            }
        }
    except Exception as e:
        return {"chains": {}, "error": str(e)[:100]}


class ChainRunRequest(BaseModel):
    goal: str


@router.post("/chains/{chain_id}/run")
async def run_chain(chain_id: str, req: ChainRunRequest):
    """Execute a playbook chain."""
    try:
        from core.economic.playbook_composition import BUILT_IN_CHAINS, execute_chain
        chain = BUILT_IN_CHAINS.get(chain_id)
        if not chain:
            raise HTTPException(status_code=404, detail=f"Chain not found: {chain_id}")
        result = execute_chain(chain, req.goal)
        return result
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── KPIs ──────────────────────────────────────────────────────

@router.get("/kpis/{objective_id}")
async def get_kpis(objective_id: str):
    """Get KPI summary for an objective."""
    try:
        from core.objectives.objective_horizon import get_horizon_manager
        mgr = get_horizon_manager()
        overview = mgr.get_overview(objective_id)
        return overview
    except Exception as e:
        return {"objective_id": objective_id, "error": str(e)[:100]}


# ── Stats ─────────────────────────────────────────────────────

@router.get("/stats")
async def get_strategy_stats():
    """All strategy type stats from strategic memory."""
    try:
        from core.economic.strategic_memory import get_strategic_memory
        return {
            "stats": get_strategic_memory().get_all_stats(),
        }
    except Exception as e:
        return {"stats": [], "error": str(e)[:100]}


# ── Validation ────────────────────────────────────────────────

@router.get("/status")
async def get_economic_status():
    """Economic layer operational status summary."""
    try:
        from core.self_model.queries import get_economic_status
        return get_economic_status()
    except Exception as e:
        return {"error": str(e)[:100]}


@router.get("/validation/{playbook_id}")
async def validate_playbook_schema(playbook_id: str):
    """Check what schema a playbook produces and its requirements."""
    try:
        from core.economic.economic_output import (
            PLAYBOOK_SCHEMA_MAP, SCHEMA_REQUIRED_FIELDS,
        )
        schema = PLAYBOOK_SCHEMA_MAP.get(playbook_id, "")
        if not schema:
            raise HTTPException(404, f"No schema mapping for: {playbook_id}")
        required = SCHEMA_REQUIRED_FIELDS.get(schema, [])
        return {
            "playbook_id": playbook_id,
            "schema_type": schema,
            "required_fields": required,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)[:100]}
