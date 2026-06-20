"""
BEA MAX — Observability Endpoints
======================================
Production-grade diagnostics — metrics, traces, failure patterns, status.

Routes:
  GET /api/v3/observability/metrics       — full metrics snapshot (machine-readable)
  GET /api/v3/observability/status        — human-readable system status
  GET /api/v3/observability/failures      — failure pattern aggregation
  GET /api/v3/observability/costs         — cost visibility
  GET /api/v3/observability/trace/{id}    — mission trace analysis
  GET /api/v3/observability/health        — lightweight health check (no auth)

Security:
  - /health is unauthenticated (for load balancers / uptime monitors)
  - All other endpoints require BEA_API_TOKEN if set
  - No secrets, keys, or tokens in any response
  - Model IDs are exposed (not sensitive); API keys are never exposed
"""
from __future__ import annotations

import time

try:
    from fastapi import APIRouter, Header, Query
    from fastapi.responses import JSONResponse, PlainTextResponse
except ImportError:
    APIRouter = None

if APIRouter:
    router = APIRouter(prefix="/api/v3/observability", tags=["observability"])

    _start_time = time.time()

    from api._deps import _check_auth

    # ── Health (no auth) ──────────────────────────────────────

    @router.get("/health")
    async def health():
        """Lightweight health probe — no auth required."""
        return {"status": "ok", "uptime_s": int(time.time() - _start_time)}

    # ── Full Metrics ──────────────────────────────────────────

    @router.get("/metrics")
    async def metrics(x_bea_token: str | None = Header(None)):
        """Full metrics snapshot — counters, histograms, gauges, failures, costs."""
        _check_auth(x_bea_token)
        try:
            from core.metrics_store import get_metrics
            return JSONResponse(content={"ok": True, "data": get_metrics().snapshot()})
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)

    # ── Human Status ──────────────────────────────────────────

    @router.get("/status")
    async def status(x_bea_token: str | None = Header(None)):
        """Human-readable system status overview."""
        _check_auth(x_bea_token)
        try:
            from core.metrics_store import get_metrics
            text = get_metrics().human_summary()
            return PlainTextResponse(content=text)
        except Exception as e:
            return PlainTextResponse(content=f"Error: {e}", status_code=500)

    # ── Failure Patterns ──────────────────────────────────────

    @router.get("/failures")
    async def failures(
        x_bea_token: str | None = Header(None),
        window_hours: float = Query(1.0, ge=0.1, le=24),
        limit: int = Query(20, ge=1, le=100),
    ):
        """Failure pattern aggregation."""
        _check_auth(x_bea_token)
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()
            window_s = window_hours * 3600
            return JSONResponse(content={
                "ok": True,
                "window_hours": window_hours,
                "by_category": m.failures.by_category(window_s),
                "top_failures": m.failures.top_failures(limit=limit, window_s=window_s),
                "recent": m.failures.recent(limit=min(limit, 20)),
            })
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)

    # ── Cost Visibility ───────────────────────────────────────

    @router.get("/costs")
    async def costs(x_bea_token: str | None = Header(None)):
        """Estimated cost breakdown by model and mission."""
        _check_auth(x_bea_token)
        try:
            from core.metrics_store import get_metrics
            return JSONResponse(content={
                "ok": True,
                "data": get_metrics().costs.snapshot(),
            })
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)

    # ── Trace Intelligence ────────────────────────────────────

    @router.get("/trace/{mission_id}")
    async def trace(mission_id: str, x_bea_token: str | None = Header(None)):
        """Structured trace analysis for a mission."""
        _check_auth(x_bea_token)
        try:
            from core.trace_intelligence import TraceSummarizer
            summary = TraceSummarizer.summarize(mission_id)
            return JSONResponse(content={
                "ok": True,
                "summary": summary.to_dict(),
                "digest": summary.digest(),
            })
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]},
                                status_code=500)

else:
    router = None
