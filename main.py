"""
BEA MAX — Canonical Entrypoint
Launches FastAPI backend on port 8000.

Usage:
    python main.py
    DRY_RUN=true python main.py
"""
from __future__ import annotations

import asyncio
import logging
import sys

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException



# ── Logging ───────────────────────────────────────────────────

logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=logging.INFO,
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("beamax.main")


# ── FastAPI ───────────────────────────────────────────────────

def create_api(settings) -> FastAPI:
    """Returns the unified BeaMax FastAPI app."""
    s = settings
    from api.main import app

    @app.on_event("startup")
    async def _bea_startup():
        try:
            s.ensure_dirs()
        except Exception as _dir_err:
            log.warning("startup_ensure_dirs_failed", err=str(_dir_err)[:120])

        # ── 1. Boot kernel runtime (FIRST — kernel is the foundation) ──────────
        # The kernel provides: capabilities, policy, memory interfaces, events.
        # API is an adapter on top of the kernel, not an independent system.
        try:
            from kernel.runtime.boot import get_runtime as _get_kernel
            _kernel = _get_kernel()
            log.info(
                "kernel_booted",
                version=_kernel.version,
                capabilities=len(_kernel.capabilities.list_all()),
                uptime_s=_kernel.uptime_seconds,
            )
            # Register core policy callable with kernel adapter (breaks circular dependency).
            # kernel/ never imports core/ — core registers itself here at boot.
            try:
                from kernel.adapters.policy_adapter import register_core_policy_fn
                from core.policy_engine import PolicyEngine
                register_core_policy_fn(PolicyEngine(s).check_action)
                log.info("kernel_policy_registered", source="core.policy_engine")
            except Exception as _pe:
                log.debug("kernel_policy_register_skipped", err=str(_pe)[:80])
            # Register core planner with kernel planning layer (breaks circular dep).
            # Uses core.planner.build_plan — canonical wrapper with keyword defaults:
            #   build_plan(goal, mission_type="coding_task", complexity="medium", mission_id="unknown") → dict
            # KernelPlanner calls it with just goal.description (other args use defaults).
            # MissionPlanner().build_plan was previously registered here but required 4 positional
            # args — KernelPlanner only passed 1 → TypeError silently fell to heuristic.
            try:
                from kernel.planning.planner import register_core_planner
                from core.planner import build_plan as _core_planner_build
                register_core_planner(_core_planner_build)
                log.info("kernel_planner_registered", source="core.planner")
            except Exception as _pp:
                log.debug("kernel_planner_register_skipped", err=str(_pp)[:80])
            # Register MetaOrchestrator as execution backend in BeaKernel (Phase 4).
            # kernel/ never imports MetaOrchestrator directly — it registers itself here.
            try:
                from kernel.runtime.kernel import get_kernel, register_orchestrator
                from core.meta_orchestrator import get_meta_orchestrator
                _jk = get_kernel()
                _meta_orch = get_meta_orchestrator()
                register_orchestrator(_meta_orch.run_mission)
                log.info("bea_kernel_ready",
                         status=_jk.status().to_dict()["booted"],
                         orchestrator=True)
                
                # Register business mission handlers
                try:
                    from core.orchestration.business_missions import register_business_handlers
                    register_business_handlers(_meta_orch)
                    log.info("business_handlers_registered")
                except Exception as _biz_err:
                    log.warning("business_handlers_register_failed", err=str(_biz_err)[:120])
            except Exception as _jke:
                # BLOC F: orchestrator registration failure is critical — kernel cannot run missions.
                log.warning("bea_kernel_orchestrator_register_failed", err=str(_jke)[:80])
            # Phase 5: Register core classifier with kernel (breaks circular dep).
            try:
                from kernel.classifier.mission_classifier import register_core_classifier
                from core.orchestration.mission_classifier import classify as _core_classify
                register_core_classifier(_core_classify)
                log.info("kernel_classifier_registered", source="core.orchestration.mission_classifier")
            except Exception as _clf_e:
                log.debug("kernel_classifier_register_skipped", err=str(_clf_e)[:80])
            # Phase 5: Register improvement history provider with kernel gate.
            try:
                from kernel.improvement.gate import register_history_provider
                from core.self_improvement import load_improvement_history as _load_hist
                register_history_provider(_load_hist)
                log.info("kernel_gate_history_registered", source="core.self_improvement")
            except Exception as _gate_e:
                log.debug("kernel_gate_history_register_skipped", err=str(_gate_e)[:80])
            # Phase 5: Register core evaluator with kernel evaluation layer.
            try:
                from kernel.evaluation.scorer import register_core_evaluator
                from core.evaluation_engine import EvaluationEngine as _EvalEng
                register_core_evaluator(_EvalEng().evaluate_result)
                log.info("kernel_evaluator_registered", source="core.evaluation_engine")
            except Exception as _eval_e:
                # BLOC F: evaluator failure → degraded evaluation pipeline.
                log.warning("kernel_evaluator_register_failed", err=str(_eval_e)[:80])
            # Phase 8: Register core reflection + critique with kernel evaluator.
            try:
                from kernel.evaluation.scorer import register_core_reflection
                from core.orchestration.reflection import reflect as _reflect_fn
                register_core_reflection(_reflect_fn)
                log.info("kernel_evaluator_reflection_registered", source="core.orchestration.reflection")
            except Exception as _refl_e:
                log.debug("kernel_evaluator_reflection_register_skipped", err=str(_refl_e)[:80])
            try:
                from kernel.evaluation.scorer import register_core_critique
                from core.orchestration.reasoning_engine import critique_output as _critique_fn
                register_core_critique(_critique_fn)
                log.info("kernel_evaluator_critique_registered", source="core.orchestration.reasoning_engine")
            except Exception as _crit_e:
                log.debug("kernel_evaluator_critique_register_skipped", err=str(_crit_e)[:80])
            # Phase 10: Register core lesson store with kernel learning layer.
            # kernel.learner calls store_lesson() (→ memory_facade.store_failure) via this slot.
            # Never blocks boot if core.orchestration.learning_loop is unavailable.
            try:
                from kernel.learning.learner import register_lesson_store
                from core.orchestration.learning_loop import store_lesson as _store_lesson_fn
                register_lesson_store(_store_lesson_fn)
                log.info("kernel_lesson_store_registered", source="core.orchestration.learning_loop")
            except Exception as _ls_e:
                # BLOC F: lesson store failure → system cannot persist learned lessons.
                log.warning("kernel_lesson_store_register_failed", err=str(_ls_e)[:80])
            # Phase 10b: Register lesson retrieval with kernel.memory (Pass 13).
            # kernel.memory.retrieve_lessons() calls this to feed past lessons
            # into run_cognitive_cycle() → enriched_goal → closes cognitive loop.
            try:
                from kernel.memory.interfaces import register_lesson_retrieve
                from core.orchestration.learning_loop import find_relevant_lessons as _find_lessons_fn
                register_lesson_retrieve(_find_lessons_fn)
                log.info("kernel_lesson_retrieve_registered", source="core.orchestration.learning_loop")
            except Exception as _lr_e:
                # BLOC F: lesson retrieval failure → cognitive loop broken (no past lessons fed to cycle).
                log.warning("kernel_lesson_retrieve_register_failed", err=str(_lr_e)[:80])
            # Phase 10c: Register execution memory functions (K1 fix for kernel/memory, Pass 13).
            try:
                from kernel.memory.interfaces import register_execution_persist, register_execution_patterns
                from core.planning.execution_memory import get_execution_memory as _get_exec_mem
                def _exec_persist(record_id: str, goal: str, success: bool) -> None:
                    from core.planning.execution_memory import ExecutionRecord
                    _get_exec_mem().record(ExecutionRecord(record_id=record_id, goal=goal, success=success))
                register_execution_persist(_exec_persist)
                register_execution_patterns(lambda: _get_exec_mem().get_successful_patterns())
                log.info("kernel_execution_memory_registered")
            except Exception as _em_e:
                log.debug("kernel_execution_memory_register_skipped", err=str(_em_e)[:80])
            # Phase 10d: Register MemoryFacade with kernel.memory (Pass 19 — R6).
            # R6: all kernel long-term persistence goes through MemoryFacade.
            # BLOC 1 fix: MemoryFacade.search() signature is search(query, content_type, top_k).
            # Kernel calls _facade_search_fn(query, top_k) — top_k must be passed as keyword
            # or it becomes content_type (second positional), breaking all search results.
            # Wrapper also normalises MemoryEntry → dict so kernel consumers get plain dicts.
            try:
                from kernel.memory.interfaces import register_facade_store, register_facade_search
                from core.memory_facade import get_memory_facade as _get_mf
                _mf = _get_mf()
                register_facade_store(_mf.store)

                def _facade_search_wrapper(query: str, top_k: int = 5) -> list:
                    """
                    K1-compliant MemoryFacade search slot.
                    Passes top_k as keyword to skip content_type positional arg.
                    Converts MemoryEntry objects → dicts for kernel consumers.
                    """
                    try:
                        entries = _mf.search(query, top_k=top_k)
                        result = []
                        for e in entries:
                            if isinstance(e, dict):
                                result.append(e)
                            elif hasattr(e, "to_dict"):
                                result.append(e.to_dict())
                            else:
                                result.append({
                                    "content": getattr(e, "content", str(e))[:500],
                                    "score": float(getattr(e, "score", 0.0) or 0.0),
                                    "content_type": getattr(e, "content_type", "general"),
                                })
                        return result
                    except Exception:
                        return []

                register_facade_search(_facade_search_wrapper)
                log.info("kernel_facade_memory_registered", source="core.memory_facade")
            except Exception as _mfe:
                # BLOC F: facade memory failure is critical — kernel memory is completely blind.
                log.warning("kernel_facade_memory_register_failed", err=str(_mfe)[:80])
            # Phase 5: Register core capability router with kernel routing layer.
            try:
                from kernel.routing.router import register_core_router
                from core.capability_routing.router import route_mission as _route_mission
                register_core_router(_route_mission)
                log.info("kernel_router_registered", source="core.capability_routing.router")
            except Exception as _rtr_e:
                log.debug("kernel_router_register_skipped", err=str(_rtr_e)[:80])
            # Phase 11 (Pass 27 — R7): Register kernel-dispatchable agents with KernelAgentRegistry.
            # Agents conform to KernelAgentContract (structural Protocol).
            # kernel/ never imports agents/ — registration happens here at boot.
            try:
                from agents.kernel_bridge import build_and_register_kernel_agents
                _registered_agents = build_and_register_kernel_agents()
                log.info("kernel_agents_registered", agents=_registered_agents,
                         count=len(_registered_agents))
            except Exception as _ka_e:
                # BLOC C: kernel agent registration failure → WARNING (not DEBUG).
                # If agents are not registered, the KernelAgentRegistry has no authority.
                log.warning("kernel_agents_register_failed", err=str(_ka_e)[:80])
        except Exception as _ke:
            log.warning("kernel_boot_skipped", err=str(_ke)[:120])

        # ── 2. Vector store ───────────────────────────────────────────────────
        try:
            from memory.vector_store import VectorStore
            await VectorStore(s).ensure_table()
        except Exception as _e:
            log.warning("vector_store_boot_skipped", err=str(_e)[:80])

        # ── 3. Action executor daemon ─────────────────────────────────────────
        try:
            from core.action_executor import get_executor
            executor = get_executor()
            executor.start()
            log.info("action_executor_started")
        except Exception as _ex:
            log.warning("action_executor_start_failed", err=str(_ex)[:80])

        # ── 4. Improvement daemon (BLOC G) ──────────────────────────────────────
        # Background thread — non-blocking, daemon=True, idempotent.
        # Runs SelfImprovementLoop.run_cycle() on an interval so the system
        # learns from past missions without any manual trigger.
        try:
            from core.improvement_daemon import start_daemon as _start_daemon
            _daemon_info = _start_daemon()
            log.info("improvement_daemon_started", status=_daemon_info.get("status"))
        except Exception as _id_e:
            log.warning("improvement_daemon_start_failed", err=str(_id_e)[:80])

        log.info("api_ready",
                 name=getattr(s, "bea_name", "bea"),
                 version=getattr(s, "bea_version", "2.0.0"))

    @app.get("/kernel/status", tags=["system"])
    async def kernel_status():
        """Return kernel runtime status — capabilities, memory, policy, uptime."""
        try:
            from kernel.runtime.boot import get_runtime as _get_kernel
            rt = _get_kernel()
            return rt.status()
        except Exception as e:
            return {"error": str(e), "booted": False}

    @app.get("/workspace", tags=["system"])
    async def workspace_info():
        try:
            from observer.watcher import SystemObserver
            snap = await SystemObserver(s).snapshot_workspace()
            return {"snapshot": snap}
        except Exception as e:
            return {"snapshot": None, "error": str(e)}

    @app.post("/run", tags=["system"])
    async def run_mission(body: dict):
        """Launch a mission programmatically."""
        mission = body.get("mission", "")
        mode    = body.get("mode", "auto")
        if not mission:
            raise HTTPException(400, "mission required")
        from core.meta_orchestrator import get_meta_orchestrator
        orch = get_meta_orchestrator()
        session = await orch.run(user_input=mission, mode=mode)
        # orch.run() returns MissionContext (mode="auto") or BeaSession (other modes).
        # MissionContext uses mission_id/result; BeaSession uses session_id/final_report.
        _sid    = getattr(session, "session_id", None) or getattr(session, "mission_id", "")
        _report = getattr(session, "final_report", None) or getattr(session, "result", "") or ""
        return {
            "session_id":   _sid,
            "status":       session.status.value,
            "final_report": _report[:2000],
        }

    return app


# ── Entry point ───────────────────────────────────────────────

async def main() -> None:
    from config.settings import get_settings
    s = get_settings()
    s.ensure_dirs()

    # Hard-fail if no LLM key is configured (and not in DRY_RUN mode).
    # Without an LLM key the system can boot but will fail on every mission.
    # Fail early rather than silently booting into a broken state.
    s.enforce_llm_key()

    # Hard-fail if BEA_PRODUCTION=true and secrets are insecure.
    # This raises RuntimeError immediately — no partial boot allowed.
    s.enforce_production_secrets()

    # ── Bounded self-improvement: force off in production mode ───────────────
    # SELF_IMPROVE_ENABLED=true is allowed in dev/alpha but must never activate
    # autonomously in production. This override prevents .env drift from enabling
    # it accidentally. An operator must make an explicit, deliberate decision.
    import os as _os
    if s.production_mode and s.self_improve_enabled:
        _os.environ["SELF_IMPROVE_ENABLED"] = "false"
        log.warning(
            "si_forced_off_in_production",
            reason=(
                "SELF_IMPROVE_ENABLED overridden to false in BEA_PRODUCTION mode. "
                "Self-improvement must not run autonomously in production without explicit review."
            ),
        )

    for warn in s.validate_security():
        log.warning("security_config_warning", detail=warn)

    log.info(
        "beamax_starting",
        name=s.bea_name,
        version=s.bea_version,
        dry_run=s.dry_run,
        model_strategy=s.model_strategy,
        self_improve_active=s.self_improve_enabled and not s.production_mode,
        production_mode=s.production_mode,
    )

    # ── Model catalog auto-refresh ────────────────────────────────────────────
    # If OPENROUTER_API_KEY is set and the catalog is stale (>24h), trigger a
    # background refresh so the selector has current model availability and pricing.
    # Fail-open: a failed or slow refresh never blocks startup or serves a request.
    if getattr(s, "openrouter_api_key", ""):
        import threading as _threading
        import time as _time

        def _bg_catalog_refresh() -> None:
            try:
                from core.model_intelligence.catalog import ModelCatalog
                cat = ModelCatalog()
                stale_threshold = 24 * 3600  # 24 hours
                age = _time.time() - cat._last_refresh
                if age > stale_threshold:
                    log.info(
                        "catalog_refresh_triggered",
                        age_hours=round(age / 3600, 1),
                        reason="stale_on_startup",
                    )
                    count = cat.refresh(api_key=s.openrouter_api_key)
                    log.info("catalog_refresh_complete", models_loaded=count)
                else:
                    log.debug(
                        "catalog_refresh_skipped",
                        age_hours=round(age / 3600, 1),
                        reason="fresh_enough",
                    )
            except Exception as _exc:
                log.warning("catalog_refresh_error", err=str(_exc)[:120])

        _threading.Thread(target=_bg_catalog_refresh, daemon=True, name="catalog-refresh").start()

    api    = create_api(s)
    config = uvicorn.Config(
        api,
        host="0.0.0.0",
        port=8000,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(config)

    log.info("beamax_ready", api="http://0.0.0.0:8000")

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
