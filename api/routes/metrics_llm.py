"""metrics_llm — stats du LLMTracer pour le monitoring (app mobile + cockpit).

Expose les métriques d'observabilité LLM (coût / latence / erreurs / par modèle)
agrégées par le `LLMTracer`. On utilise le traceur PERSISTANT partagé
(`core.observability.get_tracer`, DB `workspace/llm_traces.db`) pour que l'API voie
les appels tracés par les autres process (bot Telegram, cognition…).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api._deps import require_auth
from core.observability import get_tracer

router = APIRouter(tags=["metrics"], dependencies=[Depends(require_auth)])


@router.get("/api/v3/metrics/llm")
def llm_metrics(hours: Optional[int] = Query(None, description="Restrict to last N hours. Omit for all-time.")) -> dict:
    """Stats agrégées : {calls, cost_usd, total_tokens, error_rate, by_model}.
    Pass ?hours=24 to get current-day stats (excludes historical failures)."""
    return get_tracer().stats(since_hours=hours)


@router.get("/api/v3/metrics/llm/mission/{mission_id}")
def llm_cost(mission_id: str) -> dict:
    """Coût LLM cumulé d'une mission donnée."""
    return {"mission_id": mission_id, "cost_usd": get_tracer().cost_by_mission(mission_id)}
