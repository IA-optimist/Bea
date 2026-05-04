"""
api/routes/debug.py — Debugging and inspection endpoints.

Provides operator visibility into execution internals:
learning memory, model selection, execution traces, pipeline health.
"""
from fastapi import APIRouter, Depends

from api._deps import require_auth

router = APIRouter(prefix="/api/v3/debug", tags=["debug"], dependencies=[Depends(require_auth)])


@router.get("/learning-memory")
def get_learning_memory_stats():
    """Learning memory stats and recent records."""
    try:
        from core.planning.learning_memory import get_learning_memory
        lm = get_learning_memory()
        stats = lm.get_stats()
        lm._ensure_loaded()
        recent_missions = lm._missions[-10:] if lm._missions else []
        recent_steps = lm._steps[-20:] if lm._steps else []
        return {
            "ok": True,
            "stats": stats,
            "recent_missions": recent_missions,
            "recent_steps": recent_steps,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/model-selection/{task_class}")
def debug_model_selection(task_class: str, budget_mode: str = "normal"):
    """Show what model would be selected for a task class."""
    try:
        from core.model_intelligence.selector import get_model_selector
        sel = get_model_selector()
        result = sel.select(task_class, budget_mode)
        return {
            "ok": True,
            "task_class": task_class,
            "budget_mode": budget_mode,
            "model_id": result.model_id,
            "is_fallback": result.is_fallback,
            "score": result.final_score,
            "rationale": result.rationale,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/fallback-chain/{task_class}")
def debug_fallback_chain(task_class: str, budget_mode: str = "normal"):
    """Show the full fallback chain for a task class."""
    try:
        from core.model_intelligence.fallback_chain import get_fallback_manager
        mgr = get_fallback_manager()
        chain = mgr.get_chain(task_class, budget_mode)
        return {
            "ok": True,
            "chain": chain.to_dict(),
            "failures": mgr.get_stats(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/execution-memory")
def get_execution_memory():
    """Original execution memory history."""
    try:
        from core.planning.execution_memory import get_execution_memory
        mem = get_execution_memory()
        return {
            "ok": True,
            "stats": mem.stats(),
            "recent": mem.get_history(limit=20),
            "patterns": mem.get_successful_patterns()[:10],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/pipeline-health")
def pipeline_health():
    """Comprehensive pipeline health check."""
    checks = {}

    # LLM factory
    try:
        from core.llm_factory import LLMFactory
        from config.settings import get_settings
        factory = LLMFactory(get_settings())
        for role in ["analyst", "fast", "director"]:
            provider = factory.available_for_role(role)
            checks[f"llm_{role}"] = {"provider": provider, "ok": provider != "none"}
    except Exception as e:
        checks["llm"] = {"ok": False, "error": str(e)[:100]}

    # Model selector
    try:
        from core.model_intelligence.selector import get_model_selector
        sel = get_model_selector()
        for bm in ["budget", "normal", "critical"]:
            r = sel.select("business_reasoning", bm)
            checks[f"selector_{bm}"] = {
                "model": r.model_id,
                "is_fallback": r.is_fallback,
                "ok": bool(r.model_id),
            }
    except Exception as e:
        checks["selector"] = {"ok": False, "error": str(e)[:100]}

    # Domain skills
    try:
        from core.skills.domain_loader import DomainSkillRegistry
        reg = DomainSkillRegistry()
        reg.scan()
        checks["domain_skills"] = {"count": len(reg._skills), "ok": len(reg._skills) > 0}
    except Exception as e:
        checks["domain_skills"] = {"ok": False, "error": str(e)[:100]}

    # Playbooks
    try:
        from core.planning.playbook import get_playbook_registry
        reg = get_playbook_registry()
        checks["playbooks"] = {"count": len(reg._playbooks), "ok": len(reg._playbooks) > 0}
    except Exception as e:
        checks["playbooks"] = {"ok": False, "error": str(e)[:100]}

    # Output enforcer
    try:
        from core.planning.output_enforcer import OutputEnforcer
        e = OutputEnforcer()
        r = e.validate_against_schema({"test": "ok"}, [{"name": "test", "type": "text"}])
        checks["output_enforcer"] = {"ok": r.valid}
    except Exception as e:
        checks["output_enforcer"] = {"ok": False, "error": str(e)[:100]}

    # Quality gate
    try:
        from core.execution.quality_gate import ArtifactQualityGate
        ArtifactQualityGate()
        checks["quality_gate"] = {"ok": True}
    except Exception as e:
        checks["quality_gate"] = {"ok": False, "error": str(e)[:100]}

    # Learning memory
    try:
        from core.planning.learning_memory import get_learning_memory
        lm = get_learning_memory()
        stats = lm.get_stats()
        checks["learning_memory"] = {
            "ok": True,
            "missions": stats["total_missions"],
            "steps": stats["total_steps"],
        }
    except Exception as e:
        checks["learning_memory"] = {"ok": False, "error": str(e)[:100]}

    all_ok = all(c.get("ok", False) for c in checks.values())
    return {
        "ok": all_ok,
        "checks": checks,
        "total_checks": len(checks),
        "passing": sum(1 for c in checks.values() if c.get("ok")),
    }


@router.post("/strategy-lookup")
def strategy_lookup(goal: str = ""):
    """Look up recommended strategy for a goal."""
    try:
        from core.planning.learning_memory import get_learning_memory
        lm = get_learning_memory()
        strategy = lm.get_strategy_for_goal(goal)
        if strategy:
            return {
                "ok": True,
                "found": True,
                "strategy": strategy.to_dict(),
            }
        return {"ok": True, "found": False}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


@router.get("/retry-stats")
def retry_stats():
    """Show retry statistics from learning memory."""
    try:
        from core.planning.learning_memory import get_learning_memory
        lm = get_learning_memory()
        lm._ensure_loaded()

        retried_steps = [s for s in lm._steps if s.get("retry_count", 0) > 0]
        total_retries = sum(s.get("retry_count", 0) for s in lm._steps)

        return {
            "ok": True,
            "steps_with_retries": len(retried_steps),
            "total_retries": total_retries,
            "recent_retried": retried_steps[-5:] if retried_steps else [],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
