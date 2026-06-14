"""
api/router_mount.py — Centralized router registration for the FastAPI app.

Extracted from api/main.py (refactor M1) to keep main.py focused on
app instantiation, middleware, and startup/shutdown only.

Call mount_all_routers(app, enable_stub_routes=...) from api/main.py.
"""
from __future__ import annotations

import importlib
import structlog

log = structlog.get_logger(__name__)


def _mount_critical(app, module_path: str, var_name: str = "router") -> None:
    """Mount a router that MUST load — raises RuntimeError on import failure."""
    try:
        mod = importlib.import_module(module_path)
        router = getattr(mod, var_name)
        app.include_router(router)
    except Exception as exc:
        raise RuntimeError(
            f"CRITICAL ROUTER FAILED [{module_path}.{var_name}] — "
            f"startup aborted. Fix the import error before restarting. "
            f"Cause: {exc}"
        ) from exc


def mount_all_routers(app, enable_stub_routes: bool = False) -> None:
    """Mount all API routers onto the FastAPI app.

    Critical routers abort startup on failure.
    Optional routers log a warning and continue.
    """
    # ── WebSockets v3 ─────────────────────────────────────────────
    try:
        from api.ws import router as ws_router
        app.include_router(ws_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── SSE Streaming ─────────────────────────────────────────────
    try:
        from api.stream_router import router as stream_router
        app.include_router(stream_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Learning ──────────────────────────────────────────────────
    try:
        from api.routes.learning import router as learning_router
        app.include_router(learning_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Training (Phase 3 — Bio-inspired AGI) ─────────────────────
    try:
        from api.routes.training import router as training_router
        app.include_router(training_router)
    except Exception as _e:
        log.warning("training_router_unavailable", err=str(_e)[:120])

    # ── Autonomy daemon control plane ─────────────────────────────
    try:
        from api.routes.autonomy import router as autonomy_router
        app.include_router(autonomy_router)
    except Exception as _e:
        log.warning("autonomy_router_unavailable", err=str(_e)[:120])

    # ── Multimodal ────────────────────────────────────────────────
    try:
        from api.routes.multimodal import router as multimodal_router
        app.include_router(multimodal_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── RAG ───────────────────────────────────────────────────────
    try:
        from api.routes.rag import router as rag_router
        app.include_router(rag_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Chat + Webhook + LLM metrics ─────────────────────────────
    try:
        from api.routes.chat import router as chat_router
        app.include_router(chat_router)
        from api.routes.webhook import router as webhook_router
        app.include_router(webhook_router)
        from api.routes.metrics_llm import router as metrics_llm_router
        app.include_router(metrics_llm_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Business Performance (Phase 7.3) ──────────────────────────
    try:
        from api.routes.business import router as business_router
        app.include_router(business_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Agent Builder ─────────────────────────────────────────────
    try:
        from api.routes.agent_builder import router as agent_builder_router
        app.include_router(agent_builder_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Mission Control (Phase 9) ──────────────────────────────────
    try:
        from api.routes.mission_control import router as mission_control_router
        app.include_router(mission_control_router)
    except Exception as _e:
        log.warning("mission_control_router_unavailable", err=str(_e))

    # ── Browser (Phase 8) — STUB ──────────────────────────────────
    if enable_stub_routes:
        try:
            from api.routes.browser import router as browser_router
            app.include_router(browser_router)
        except Exception as _e:
            log.warning("router_import_failed", err=str(_e)[:120])

    # ── Routing Diagnostics ───────────────────────────────────────
    try:
        from api.routes.routing_diagnostics import router as routing_diag_router
        if routing_diag_router:
            app.include_router(routing_diag_router)
    except Exception as _e:
        log.warning("routing_diagnostics_router_unavailable", err=str(_e))

    # ── Monitoring (Phase 3 + Phase 8) ───────────────────────────
    try:
        from api.routes.monitoring import router as monitoring_router
        app.include_router(monitoring_router)
    except Exception as _e:
        log.warning("monitoring_router_unavailable", err=str(_e))

    # ── Projects (Phase 2.1) ──────────────────────────────────────
    try:
        from api.routes.projects import router as projects_router
        app.include_router(projects_router)
    except Exception as _e:
        log.warning("projects_router_unavailable", err=str(_e))

    # ── Voice & Call (Phase 10) — STUB ───────────────────────────
    if enable_stub_routes:
        try:
            from api.routes.voice import router as voice_router
            app.include_router(voice_router)
        except Exception as _e:
            log.warning("router_import_failed", err=str(_e)[:120])

    # ── Objective Engine ──────────────────────────────────────────
    try:
        from api.routes.objectives import router as objectives_router
        app.include_router(objectives_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Self-Improvement Loop ──────────────────────────────────────
    try:
        from api.routes.self_improvement import router as self_improvement_router
        app.include_router(self_improvement_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Dashboard ─────────────────────────────────────────────────
    try:
        from api.routes.dashboard import router as dashboard_router
        app.include_router(dashboard_router)
    except ImportError as _e:
        log.warning("dashboard_router_unavailable", err=str(_e))

    _mount_critical(app, "api.routes.approval")  # CRITICAL: human-in-the-loop gate

    # ── Convergence (v3 orchestration bridge) ─────────────────────
    try:
        from api.routes.convergence import router as convergence_router
        app.include_router(convergence_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Performance Intelligence (v3) ─────────────────────────────
    try:
        from api.routes.performance import router as performance_router
        if performance_router:
            app.include_router(performance_router)
    except Exception as _e:
        log.warning("router_import_failed", err=str(_e)[:120])

    # ── Observability (V3) ────────────────────────────────────────
    try:
        from api.routes.observability import router as observability_router
        if observability_router:
            app.include_router(observability_router)
    except Exception as _e:
        log.warning("observability_router_unavailable", err=str(_e))

    # ── Mobile Metrics ────────────────────────────────────────────
    try:
        from api.routes.metrics_mobile import router as metrics_mobile_router
        if metrics_mobile_router:
            app.include_router(metrics_mobile_router)
    except Exception as _e:
        log.warning("metrics_mobile_router_unavailable", err=str(_e))

    # ── Extensions ────────────────────────────────────────────────
    try:
        from api.routes.extensions import router as extensions_router
        app.include_router(extensions_router)
    except Exception as _e:
        log.warning("extensions_router_unavailable", err=str(_e))

    # ── Token Management ──────────────────────────────────────────
    try:
        from api.routes.token_management import router as token_mgmt_router
        if token_mgmt_router:
            app.include_router(token_mgmt_router)
    except Exception as _exc:
        log.warning("swallowed_exception", action="main_1",
                    exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Skills ────────────────────────────────────────────────────
    try:
        from api.routes.skills import router as skills_router
        app.include_router(skills_router)
    except Exception as _e:
        log.warning("skills_router_unavailable", err=str(_e))

    # ── System ────────────────────────────────────────────────────
    try:
        from api.routes.system import router as system_router
        app.include_router(system_router)
    except Exception as _e:
        log.warning("system_router_unavailable", err=str(_e))

    # ── Finance webhook (always mounted, Stripe sig verification) ─
    try:
        from api.routes.finance import webhook_router as finance_webhook_router
        app.include_router(finance_webhook_router)
    except Exception as _e:
        log.warning("finance_webhook_router_unavailable", err=str(_e))

    if enable_stub_routes:
        try:
            from api.routes.finance import router as finance_router
            app.include_router(finance_router)
        except Exception as _e:
            log.warning("finance_router_unavailable", err=str(_e))

    _mount_critical(app, "api.routes.missions")  # CRITICAL: core mission operations

    # ── Vault ─────────────────────────────────────────────────────
    try:
        from api.routes.vault import router as vault_router
        app.include_router(vault_router)
    except Exception as _e:
        log.warning("vault_router_unavailable", err=str(_e))

    # ── Identity ──────────────────────────────────────────────────
    try:
        from api.routes.identity import router as identity_router
        app.include_router(identity_router)
    except Exception as _e:
        log.warning("identity_router_unavailable", err=str(_e))

    # NOTE: connectors_router MUST be mounted before modules_v3_router —
    # modules_v3 defines GET /api/v3/connectors which would shadow
    # connectors.py's prefix if mounted first.
    try:
        from api.routes.connectors import router as connectors_router
        app.include_router(connectors_router)
    except Exception as _e:
        log.warning("connectors_router_unavailable", err=str(_e))

    try:
        from api.routes.modules_v3 import router as modules_v3_router
        app.include_router(modules_v3_router)
    except Exception as _e:
        log.warning("modules_v3_router_unavailable", err=str(_e))

    # ── Cognitive ─────────────────────────────────────────────────
    try:
        from api.routes.cognitive import router as cognitive_router
        app.include_router(cognitive_router)
    except Exception as _e:
        log.warning("cognitive_router_unavailable", err=str(_e))

    # ── Action Console ────────────────────────────────────────────
    try:
        from api.routes.action_console import router as console_router
        app.include_router(console_router)
    except Exception as _e:
        log.warning("console_router_unavailable", err=str(_e))

    # ── MCP Management ────────────────────────────────────────────
    try:
        from api.routes.mcp_management import router as mcp_mgmt_router
        app.include_router(mcp_mgmt_router)
    except Exception as _e:
        log.warning("mcp_mgmt_router_unavailable", err=str(_e))

    # ── Self Model ────────────────────────────────────────────────
    try:
        from api.routes.self_model import router as self_model_router
        app.include_router(self_model_router)
    except Exception as _e:
        log.warning("self_model_router_unavailable", err=str(_e))

    # ── Capability Routing ────────────────────────────────────────
    try:
        from api.routes.capability_routing import router as capability_routing_router
        app.include_router(capability_routing_router)
    except Exception as _e:
        log.warning("capability_routing_router_unavailable", err=str(_e))

    # ── Cognitive Events ──────────────────────────────────────────
    try:
        from api.routes.cognitive_events import router as cognitive_events_router
        app.include_router(cognitive_events_router)
    except Exception as _e:
        log.warning("cognitive_events_router_unavailable", err=str(_e))

    # ── Mission Persistence ───────────────────────────────────────
    try:
        from api.routes.mission_persistence import router as mission_persistence_router
        app.include_router(mission_persistence_router)
    except Exception as _e:
        log.warning("mission_persistence_router_unavailable", err=str(_e))

    # ── Business Actions / Artifacts / Opportunities / Products ───
    try:
        from api.routes.business_actions import router as business_actions_router
        app.include_router(business_actions_router)
    except Exception as _e:
        log.warning("business_actions_router_unavailable", err=str(_e))

    try:
        from api.routes.business_artifacts import router as business_artifacts_router
        app.include_router(business_artifacts_router)
    except Exception as _e:
        log.warning("business_artifacts_router_unavailable", err=str(_e))

    try:
        from api.routes.opportunities import router as opportunities_router
        app.include_router(opportunities_router)
    except Exception as _e:
        log.warning("opportunities_router_unavailable", err=str(_e))

    try:
        from api.routes.products import router as products_router
        app.include_router(products_router)
    except Exception as _e:
        log.warning("products_router_unavailable", err=str(_e))

    # ── Domain Skills ─────────────────────────────────────────────
    try:
        from api.routes.domain_skills import router as domain_skills_router
        app.include_router(domain_skills_router)
    except Exception as _e:
        log.warning("domain_skills_router_unavailable", err=str(_e))

    # ── Operational Tools ─────────────────────────────────────────
    try:
        from api.routes.operational_tools import router as operational_tools_router
        app.include_router(operational_tools_router)
    except Exception as _e:
        log.warning("operational_tools_router_unavailable", err=str(_e))

    _mount_critical(app, "api.routes.system_readiness")  # CRITICAL: Docker healthcheck

    # ── Plan Runner ───────────────────────────────────────────────
    try:
        from api.routes.plan_runner import router as plan_runner_router
        app.include_router(plan_runner_router)
    except Exception as _e:
        log.warning("plan_runner_router_unavailable", err=str(_e))

    # ── Playbooks — STUB ──────────────────────────────────────────
    if enable_stub_routes:
        try:
            from api.routes.playbooks import router as playbooks_router
            app.include_router(playbooks_router)
        except Exception as _e:
            log.warning("playbooks_router_unavailable", err=str(_e))

    # ── Economic ──────────────────────────────────────────────────
    try:
        from api.routes.economic import router as economic_router
        app.include_router(economic_router)
    except Exception as _e:
        log.warning("economic_router_unavailable", err=str(_e))

    # ── Models ────────────────────────────────────────────────────
    try:
        from api.routes.models import router as models_router
        app.include_router(models_router)
    except Exception as _e:
        log.warning("models_router_unavailable", err=str(_e))

    # ── Execution ─────────────────────────────────────────────────
    try:
        from api.routes.execution import router as execution_router
        app.include_router(execution_router)
    except Exception as _e:
        log.warning("execution_router_unavailable", err=str(_e))

    # ── Venture ───────────────────────────────────────────────────
    try:
        from api.routes.venture import router as venture_router
        app.include_router(venture_router)
    except Exception as _e:
        log.warning("venture_router_unavailable", err=str(_e))

    # ── Strategy ──────────────────────────────────────────────────
    try:
        from api.routes.strategy import router as strategy_router
        app.include_router(strategy_router)
    except Exception as _e:
        log.warning("strategy_router_unavailable", err=str(_e))

    # ── Kernel ────────────────────────────────────────────────────
    try:
        from api.routes.kernel import router as kernel_router
        app.include_router(kernel_router)
    except Exception as _e:
        log.warning("kernel_router_unavailable", err=str(_e))

    _mount_critical(app, "api.routes.security_audit")  # CRITICAL: security audit endpoints

    # ── Debug ─────────────────────────────────────────────────────
    try:
        from api.routes.debug import router as debug_router
        app.include_router(debug_router)
    except Exception as _e:
        log.warning("debug_router_unavailable", err=str(_e))

    # ── Previously unregistered routes (2026-03-30) ───────────────
    try:
        from api.routes.system_v2 import router as system_v2_router
        app.include_router(system_v2_router)
    except Exception as _e:
        log.warning("system_v2_router_unavailable", err=str(_e))

    try:
        from api.routes.self_improvement_v2 import router as self_improvement_v2_router
        app.include_router(self_improvement_v2_router)
    except Exception as _e:
        log.warning("self_improvement_v2_router_unavailable", err=str(_e))

    try:
        from api.routes.modules import router as modules_router
        app.include_router(modules_router)
    except Exception as _e:
        log.warning("modules_router_unavailable", err=str(_e))

    # ── Misc endpoints (Prometheus /metrics, chat v2 alias, registry) ─
    try:
        from api.routes.misc_endpoints import router as misc_router
        app.include_router(misc_router)
    except Exception as _e:
        log.warning("misc_endpoints_router_unavailable", err=str(_e))

    # ── Auth routes ───────────────────────────────────────────────
    from api.routes import auth as _auth_routes
    app.include_router(_auth_routes.router)
