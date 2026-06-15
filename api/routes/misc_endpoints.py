"""
BEA MAX — Miscellaneous inline endpoints

Extracted from api/main.py (refactor M1).

Contains endpoints that did not belong to any existing domain router:
  - GET  /metrics             — Prometheus metrics (auth-protected)
  - POST /api/v2/chat         — v2→v3 chat alias (frontend compat)
  - GET  /api/v3/system/registry — router registry status (admin)
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from api._deps import require_auth

log = structlog.get_logger()

router = APIRouter()


# ── Prometheus Metrics Endpoint ────────────────────────────────

@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(user: dict = Depends(require_auth)):
    """
    Prometheus-compatible metrics endpoint.

    Exposes all registered Prometheus metrics including:
    - Business engine metrics (scans, builds, deploys)
    - System metrics (CPU, memory, etc.)
    - API metrics (requests, latency, etc.)
    """
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── v2 Chat Alias (frontend compatibility) ────────────────────

@router.post("/api/v2/chat", include_in_schema=False)
async def chat_v2_alias(request: Request, user: dict = Depends(require_auth)):
    """Alias for /api/v3/chat to maintain frontend compatibility.

    Hardening (audit Mo4): auth déclarée explicitement dans la signature.
    L'auth était précédemment implicite (déléguée à chat() via les headers),
    ce qui (a) cachait la contrainte d'OpenAPI/Swagger et (b) devenait silencieusement
    ouverte si chat() était refactorisé.
    """
    try:
        from api.routes.chat import chat
        from pydantic import BaseModel
        from typing import List, Optional

        class ChatMessage(BaseModel):
            role: str
            content: str
            timestamp: Optional[str] = None

        class ChatRequest(BaseModel):
            message: str
            project_id: int = 1
            conversation_history: List[ChatMessage] = []
            enable_tot: bool = True
            enable_self_correction: bool = True

        body = await request.json()
        req = ChatRequest(**body)
        x_bea_token = request.headers.get("x-bea-token")
        authorization = request.headers.get("authorization")
        return await chat(req, x_bea_token, authorization)
    except Exception as e:
        log.error("chat_v2_alias_error", err=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ── Router Registry Status ────────────────────────────────────

@router.get("/api/v3/system/registry", tags=["system"])
async def router_registry_status(user: dict = Depends(require_auth)):
    """Show status of all registered API routers. Admin-only (exposes API surface)."""
    try:
        from api.router_registry import get_registry_status
        return get_registry_status()
    except Exception as e:
        return {"error": str(e)}
