"""metrics_llm — stats du LLMTracer pour le monitoring (app mobile + cockpit).

Expose les métriques d'observabilité LLM (coût / latence / erreurs / par modèle)
agrégées par le `LLMTracer`. On utilise le traceur PERSISTANT partagé
(`core.observability.get_tracer`, DB `workspace/llm_traces.db`) pour que l'API voie
les appels tracés par les autres process (bot Telegram, cognition…).
"""
from __future__ import annotations

from fastapi import APIRouter

from core.observability import get_tracer

router = APIRouter(tags=["metrics"])


@router.get("/api/v3/metrics/llm")
def llm_metrics() -> dict:
    """Stats agrégées : {calls, cost_usd, total_tokens, error_rate, by_model}."""
    return get_tracer().stats()


@router.get("/api/v3/metrics/llm/mission/{mission_id}")
def llm_cost(mission_id: str) -> dict:
    """Coût LLM cumulé d'une mission donnée."""
    return {"mission_id": mission_id, "cost_usd": get_tracer().cost_by_mission(mission_id)}
