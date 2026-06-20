"""
BEA MAX — Mobile Metrics API
==================================
Lightweight, structured endpoints optimized for the mobile dashboard.

Routes (all under /api/v3/metrics):
  GET /summary         — high-level system health overview
  GET /routing         — model routing status and performance
  GET /tools           — tool reliability and latency
  GET /improvement     — self-improvement experiment stats
  GET /failures        — recent failure patterns

All responses follow: {"ok": true, "data": {...}}
Auth: BEA_API_TOKEN if set. No secrets in responses.
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

try:
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    from api._deps import require_auth
except ImportError:
    APIRouter = None

if APIRouter:
    router = APIRouter(
        prefix="/api/v3/metrics",
        tags=["metrics-mobile"],
        dependencies=[Depends(require_auth)],
    )

    # ── Summary ───────────────────────────────────────────────

    @router.get("/summary")
    async def metrics_summary():
        """System health overview for mobile dashboard."""
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()

            submitted = m.get_counter_total("missions_submitted_total")
            completed = m.get_counter_total("missions_completed_total")
            failed = m.get_counter_total("missions_failed_total")
            success_rate = round(completed / submitted, 3) if submitted > 0 else 0

            dur = m.get_histogram("mission_duration_ms")
            tool_total = m.get_counter_total("tool_invocations_total")
            tool_fail = m.get_counter_total("tool_failures_total")
            tool_rate = round(1 - tool_fail / tool_total, 3) if tool_total > 0 else 1.0

            costs = m.costs.snapshot()

            # Active models
            model_counter = m._counters.get("model_selected_total")
            active_models = []
            if model_counter:
                for lk, v in sorted(model_counter.get_all().items(),
                                     key=lambda x: -x[1]):
                    if lk and lk != "_total":
                        name = lk.replace("model_id=", "")
                        active_models.append({"model": name, "calls": int(v)})

            # Alerts
            try:
                from core.metrics_bridge import evaluate_alerts
                alerts = evaluate_alerts()
            except Exception:
                alerts = []

            return JSONResponse(content={"ok": True, "data": {
                "health": "healthy" if success_rate >= 0.7 else "degraded" if success_rate >= 0.4 else "critical",
                "success_rate": success_rate,
                "missions": {"submitted": int(submitted), "completed": int(completed), "failed": int(failed)},
                "duration_avg_ms": dur.get("avg", 0) if isinstance(dur, dict) else 0,
                "tool_reliability": tool_rate,
                "cost_today_usd": costs["total_estimated_usd"],
                "active_models": active_models[:5],
                "alerts": [{"alert": a["alert"], "severity": a["severity"],
                            "current": a.get("current", 0)} for a in alerts],
                "uptime_s": m.snapshot()["uptime_s"],
            }})
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]}, status_code=500)

    # ── Routing ───────────────────────────────────────────────

    @router.get("/routing")
    async def metrics_routing():
        """Model routing performance for mobile dashboard."""
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()

            models: list[dict] = []
            sel = m._counters.get("model_selected_total")
            fail = m._counters.get("model_failure_total")
            lat = m._histograms.get("model_latency_ms")

            if sel:
                for lk, calls in sorted(sel.get_all().items(), key=lambda x: -x[1]):
                    if not lk or lk == "_total":
                        continue
                    model_id = lk.replace("model_id=", "")
                    failures = fail.get(lk) if fail else 0
                    lat_stats = lat.stats(lk) if lat and lk in (lat.get_all_keys()) else {}
                    models.append({
                        "model": model_id,
                        "calls": int(calls),
                        "failures": int(failures),
                        "success_rate": round(1 - failures / calls, 3) if calls > 0 else 1.0,
                        "avg_latency_ms": lat_stats.get("avg", 0),
                        "p95_latency_ms": lat_stats.get("p95", 0),
                    })

            fallbacks = m.get_counter_total("fallback_used_total")
            local = m.get_counter_total("local_only_route_total")
            cloud = m.get_counter_total("cloud_route_total")

            # Live health from adaptive routing
            live_health = {}
            try:
                from core.adaptive_routing import get_enhanced_tracker
                live_health = get_enhanced_tracker().get_all()
            except Exception as _exc:
                log.warning("swallowed_exception", action="metrics_mobile_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            costs = m.costs.snapshot()

            return JSONResponse(content={"ok": True, "data": {
                "models": models,
                "fallbacks_used": int(fallbacks),
                "local_routes": int(local),
                "cloud_routes": int(cloud),
                "live_health": {k: round(v, 3) for k, v in live_health.items()},
                "cost_by_model": costs.get("by_model", {}),
            }})
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]}, status_code=500)

    # ── Tools ─────────────────────────────────────────────────

    @router.get("/tools")
    async def metrics_tools():
        """Tool reliability and latency for mobile dashboard."""
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()

            tools: list[dict] = []
            inv = m._counters.get("tool_invocations_total")
            fail = m._counters.get("tool_failures_total")
            timeout = m._counters.get("tool_timeout_total")
            lat = m._histograms.get("tool_latency_ms")

            if inv:
                for lk, calls in sorted(inv.get_all().items(), key=lambda x: -x[1]):
                    if not lk or lk == "_total":
                        continue
                    tool_name = lk.replace("tool=", "")
                    failures = fail.get(lk) if fail else 0
                    timeouts = timeout.get(lk) if timeout else 0
                    lat_stats = lat.stats(lk) if lat and lk in (lat.get_all_keys()) else {}
                    tools.append({
                        "tool": tool_name,
                        "calls": int(calls),
                        "failures": int(failures),
                        "timeouts": int(timeouts),
                        "success_rate": round(1 - failures / calls, 3) if calls > 0 else 1.0,
                        "avg_latency_ms": lat_stats.get("avg", 0),
                        "p95_latency_ms": lat_stats.get("p95", 0),
                    })

            retries = m.get_counter_total("retry_attempts_total")

            return JSONResponse(content={"ok": True, "data": {
                "tools": tools,
                "total_invocations": int(m.get_counter_total("tool_invocations_total")),
                "total_failures": int(m.get_counter_total("tool_failures_total")),
                "total_timeouts": int(m.get_counter_total("tool_timeout_total")),
                "retries": int(retries),
            }})
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]}, status_code=500)

    # ── Improvement ───────────────────────────────────────────

    @router.get("/improvement")
    async def metrics_improvement():
        """Self-improvement experiment stats for mobile dashboard."""
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()

            started = m.get_counter_total("experiments_started_total")
            promoted = m.get_counter_total("experiments_promoted_total")
            rejected = m.get_counter_total("experiments_rejected_total")
            blocked = m.get_counter_total("regressions_blocked_total")
            lessons = m.get_counter_total("lessons_learned_total")

            score_hist = m.get_histogram("score_delta")

            # Daemon status
            daemon_status = {}
            try:
                from core.improvement_daemon import get_daemon_status
                daemon_status = get_daemon_status()
            except Exception as _exc:
                log.warning("swallowed_exception", action="metrics_mobile_3", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            return JSONResponse(content={"ok": True, "data": {
                "experiments": {
                    "started": int(started),
                    "promoted": int(promoted),
                    "rejected": int(rejected),
                    "blocked": int(blocked),
                },
                "promotion_rate": round(promoted / started, 3) if started > 0 else 0,
                "lessons_learned": int(lessons),
                "score_delta_avg": score_hist.get("avg", 0),
                "daemon": daemon_status,
            }})
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]}, status_code=500)

    # ── Failures ──────────────────────────────────────────────

    @router.get("/failures")
    async def metrics_failures():
        """Recent failure patterns for mobile dashboard."""
        try:
            from core.metrics_store import get_metrics
            m = get_metrics()

            by_cat = m.failures.by_category(window_s=3600)
            top = m.failures.top_failures(limit=5, window_s=3600)
            recent = m.failures.recent(limit=10)

            return JSONResponse(content={"ok": True, "data": {
                "by_category": by_cat,
                "top_failures": top,
                "recent": recent,
                "total_1h": sum(by_cat.values()),
            }})
        except Exception as e:
            return JSONResponse(content={"ok": False, "error": str(e)[:200]}, status_code=500)

else:
    router = None
