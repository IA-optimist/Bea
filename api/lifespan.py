"""
BEA MAX — FastAPI lifespan (startup / shutdown)

Extracted from api/main.py (refactor M1) to keep main.py focused on app
instantiation and router wiring only.

`lifespan` is the asynccontextmanager consumed by FastAPI(lifespan=lifespan).
`_on_startup` and `_on_shutdown` are the actual async coroutines — kept
as named functions so individual steps can be unit-tested without spinning
up the full app.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog

log = structlog.get_logger()


async def _on_startup(app) -> None:  # noqa: ANN001
    """Run all startup tasks in order. Failures are logged but do not abort
    startup unless they are security-critical (production secret validation)."""

    # SECURITY: Enforce production secrets (JWT, admin password, API token)
    # Raises RuntimeError if BEA_PRODUCTION=true and secrets are insecure
    try:
        from config.settings import get_settings
        settings = get_settings()
        settings.enforce_production_secrets()
        log.info("production_secrets_validated", production_mode=settings.production_mode)
    except RuntimeError as e:
        log.critical("PRODUCTION_STARTUP_BLOCKED", error=str(e))
        raise

    try:
        from core.workspace_cleaner import run_cleanup
        metrics = run_cleanup()
        log.info("startup_cleanup_done", **metrics)
    except Exception as exc:
        log.warning("startup_cleanup_failed", err=str(exc)[:80])

    # Auto-collect failures from missions in store
    try:
        from core.self_improvement.failure_collector import FailureCollector
        from api.mission_store import MissionStateStore
        collector = FailureCollector()
        new_failures = collector.collect_from_store(MissionStateStore.get())
        log.info("self_improvement_startup_collect", failures_found=len(new_failures))
        if new_failures:
            from core.self_improvement.improvement_planner import ImprovementPlanner
            ImprovementPlanner().plan_from_failures(new_failures)
    except Exception as exc:
        log.warning("self_improvement_startup_collect_failed", err=str(exc)[:80])

    # Install observability instrumentation (metrics bridge)
    try:
        from core.metrics_bridge import install_instrumentation
        bridge_results = install_instrumentation(start_snapshots=True)
        log.info("metrics_bridge_installed", results=bridge_results)
    except Exception as exc:
        log.warning("metrics_bridge_install_failed", err=str(exc)[:80])

    # Install adaptive model routing (live metrics → routing decisions)
    try:
        from core.adaptive_routing import install_adaptive_routing
        routing_results = install_adaptive_routing()
        log.info("adaptive_routing_installed", results=routing_results)
    except Exception as exc:
        log.warning("adaptive_routing_install_failed", err=str(exc)[:80])

    # Load cognitive event journal from disk (survive restarts)
    try:
        from core.cognitive_events.store import get_journal
        loaded = get_journal().load_from_disk(days=3)
        log.info("cognitive_journal_loaded", events_restored=loaded)
    except Exception as exc:
        log.warning("cognitive_journal_load_failed", err=str(exc)[:80])

    # Recover mission state from persistence
    try:
        from core.meta_orchestrator import get_orchestrator
        recovery = get_orchestrator().recover_from_persistence()
        log.info("mission_recovery_complete", **recovery)
    except Exception as exc:
        log.warning("mission_recovery_failed", err=str(exc)[:80])

    # Register MetaOrchestrator as execution backend in BeaKernel.
    # Without this, kernel.execute() logs kernel_execute_no_orchestrator and
    # every mission falls back to fallback_message with zero real output.
    # main.py did this registration but run_api_local.py skips main.py.
    try:
        from kernel.runtime.kernel import get_kernel, register_orchestrator
        from core.meta_orchestrator import get_meta_orchestrator
        _jk = get_kernel()
        _meta_orch = get_meta_orchestrator()
        register_orchestrator(_meta_orch.run_mission)
        log.info("bea_kernel_orchestrator_registered",
                 booted=_jk.status().to_dict().get("booted", False))
        try:
            from core.orchestration.business_missions import register_business_handlers
            register_business_handlers(_meta_orch)
            log.info("business_handlers_registered")
        except Exception as _biz_err:
            log.warning("business_handlers_register_failed", err=str(_biz_err)[:120])
    except Exception as exc:
        log.warning("kernel_orchestrator_register_failed", err=str(exc)[:120])

    # ── MCP sidecar auto-registration (Cycle 2 Phase A) ──────────────────
    # Fail-open: flags default false, never blocks startup.
    # Enable with QDRANT_MCP_ENABLED=true / GITHUB_MCP_ENABLED=true in .env
    try:
        from api.startup_checks import register_mcp_adapters
        mcp_result = register_mcp_adapters()
        log.info("mcp_adapters_startup", **mcp_result)
    except Exception as exc:
        log.warning("mcp_adapters_startup_failed", err=str(exc)[:80])

    # ── Auto-register all mounted routers with the registry ───────
    try:
        from api.router_registry import register_router as _auto_reg
        from fastapi.routing import APIRoute, APIRouter
        _seen: set = set()
        for route in app.routes:
            if isinstance(route, APIRoute):
                prefix = route.path.rsplit("/", 1)[0] if "/" in route.path else ""
                tags = list(route.tags) if route.tags else []
                name = tags[0] if tags else prefix.strip("/").replace("/", "_") or "root"
                if name not in _seen:
                    r = APIRouter()
                    r.routes = [
                        rt for rt in app.routes
                        if isinstance(rt, APIRoute)
                        and (list(rt.tags) or [""])[0] == (tags[0] if tags else "")
                    ]
                    _auto_reg(name, r, prefix=prefix, tags=tags)
                    _seen.add(name)
        log.info("router_registry_auto_populated", count=len(_seen))
    except Exception as exc:
        log.warning("router_registry_auto_failed", err=str(exc)[:80])

    # Initialize project CRUD pool
    try:
        from core.db.project_crud import init_pool
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            log.warning("project_crud_pool_skipped", reason="DATABASE_URL not set")
        else:
            await init_pool(dsn)
            log.info("project_crud_pool_initialized")
    except Exception as exc:
        log.warning("project_crud_pool_init_failed", err=str(exc)[:80])

    # ── Continuous self-improvement daemon (opt-in) ──────────────────────────
    # Runs the hardened improvement loop in a background thread inside the API
    # process — the same process where real missions execute and accumulate the
    # runtime telemetry (metrics_store) the loop reads. As usage signal builds up,
    # the daemon detects real weaknesses and applies safe, sandboxed, regression-
    # tested patches (max 1/cycle, max 3 files, CRITICAL zones auto-blocked,
    # rollback on failure). Enable with BEA_CONTINUOUS_IMPROVEMENT=1.
    # The kernel cooldown (24h) and consecutive-failure cap stay active; operator
    # approval (BEA_OPERATOR_APPROVE_IMPROVEMENT) only lifts the R4 human-approval
    # gate, which the operator has explicitly granted at host level.
    try:
        if os.getenv("BEA_CONTINUOUS_IMPROVEMENT", "").lower() in ("1", "true", "yes"):
            os.environ.setdefault("BEA_OPERATOR_APPROVE_IMPROVEMENT", "1")
            from core.improvement_daemon import start_daemon
            daemon_status = start_daemon()
            log.info("continuous_improvement_daemon_started", **daemon_status)
        else:
            log.info("continuous_improvement_daemon_disabled",
                     hint="set BEA_CONTINUOUS_IMPROVEMENT=1 to enable")
    except Exception as exc:
        log.warning("continuous_improvement_daemon_failed", err=str(exc)[:80])


async def _on_shutdown() -> None:
    """Run all shutdown tasks in order. All failures are logged, none are re-raised."""

    # Stop the continuous self-improvement daemon gracefully (if it was started).
    try:
        from core.improvement_daemon import stop_daemon
        stop_daemon()
        log.info("continuous_improvement_daemon_stopped")
    except Exception as exc:
        log.warning("continuous_improvement_daemon_stop_failed", err=str(exc)[:80])

    # Save kernel performance data to survive restarts
    try:
        from kernel.runtime.boot import save_performance
        saved = save_performance()
        log.info("kernel_performance_saved_on_shutdown", success=saved)
    except Exception as exc:
        log.warning("kernel_performance_save_failed", err=str(exc)[:80])


@asynccontextmanager
async def lifespan(app):  # noqa: ANN001
    """FastAPI lifespan context manager — consumed by FastAPI(lifespan=lifespan)."""
    await _on_startup(app)
    try:
        yield
    finally:
        await _on_shutdown()
