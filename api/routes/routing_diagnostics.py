"""
JARVIS MAX — Routing Diagnostics API

Exposes routing policy state and recent decisions for debugging.
"""
from __future__ import annotations

try:
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    from api._deps import require_auth
except ImportError:
    APIRouter = None

if APIRouter:
    router = APIRouter(prefix="/api/routing", tags=["routing"], dependencies=[Depends(require_auth)])

    @router.get("/decisions")
    async def get_routing_decisions(limit: int = 20):
        """Return recent routing decisions."""
        try:
            from core.llm_routing_policy import get_recent_decisions
            return JSONResponse(content={
                "ok": True,
                "decisions": get_recent_decisions(limit=min(limit, 50)),
            })
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)

    @router.get("/health")
    async def get_model_health():
        """Return model health scores."""
        try:
            from core.llm_routing_policy import get_health_tracker
            return JSONResponse(content={
                "ok": True,
                "model_health": get_health_tracker().get_all(),
            })
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)

    @router.post("/simulate")
    async def simulate_route(
        role: str = "default",
        task_description: str = "",
        complexity: float = 0.5,
        budget: str = "balanced",
        latency: str = "normal",
    ):
        """Simulate a routing decision without executing it."""
        try:
            from core.llm_routing_policy import resolve_role
            decision = resolve_role(
                role=role,
                budget=budget,
                latency=latency,
                task_description=task_description,
                complexity=complexity,
            )
            return JSONResponse(content={
                "ok": True,
                "decision": {
                    "resolved_role": decision.resolved_role,
                    "model_id": decision.model_id,
                    "dimension": decision.dimension.value,
                    "score": decision.score,
                    "reason": decision.reason,
                    "budget_mode": decision.budget_mode,
                    "latency_mode": decision.latency_mode,
                    "locality": decision.locality,
                    "rejected": decision.rejected,
                    "expected_cost_tier": decision.expected_cost_tier,
                },
            })
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)
else:
    router = None
