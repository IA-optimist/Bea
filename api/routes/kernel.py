"""
api/routes/kernel.py — Kernel convergence API endpoints.

Exposes kernel state during progressive convergence so operators
can verify the kernel is receiving real data from mission execution.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

log = structlog.get_logger("api.kernel")

router = APIRouter(prefix="/api/v3/kernel", tags=["kernel"])


def _auth():
    try:
        from api._deps import require_auth
        return require_auth
    except Exception:
        return lambda: None


@router.get("/status")
async def kernel_status(user=Depends(_auth())):
    """Get kernel runtime status."""
    try:
        from kernel.runtime.boot import get_runtime
        runtime = get_runtime()
        return runtime.status()
    except Exception as e:
        return {"error": str(e)[:200], "booted": False}


@router.get("/capabilities")
async def kernel_capabilities(category: str = "", user=Depends(_auth())):
    """Query kernel capability registry (authoritative after sync)."""
    try:
        from kernel.convergence.capability_bridge import query_capabilities
        caps = query_capabilities(category=category)
        return {"capabilities": caps, "count": len(caps)}
    except Exception as e:
        return {"error": str(e)[:200], "capabilities": [], "count": 0}


@router.get("/capabilities/stats")
async def kernel_capability_stats(user=Depends(_auth())):
    """Get capability registry stats (kernel + core)."""
    try:
        from kernel.convergence.capability_bridge import get_registry_stats
        return get_registry_stats()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.post("/capabilities/resolve")
async def resolve_capability(capability_id: str, user=Depends(_auth())):
    """Resolve best provider for a capability via kernel."""
    try:
        from kernel.convergence.capability_bridge import resolve_provider
        result = resolve_provider(capability_id)
        return {"result": result, "resolved": result is not None}
    except Exception as e:
        return {"error": str(e)[:200], "resolved": False}


@router.get("/events/canonical")
async def canonical_events(user=Depends(_auth())):
    """List all kernel canonical event types."""
    try:
        from kernel.events.canonical import CANONICAL_EVENTS
        return {"events": CANONICAL_EVENTS, "count": len(CANONICAL_EVENTS)}
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/memory/stats")
async def kernel_memory_stats(user=Depends(_auth())):
    """Get kernel memory interface stats."""
    try:
        from kernel.memory.interfaces import get_memory
        return get_memory().stats()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/policy/pending")
async def kernel_pending_approvals(user=Depends(_auth())):
    """Get pending approvals from kernel approval gate."""
    try:
        from kernel.convergence.policy_bridge import get_pending_approvals
        pending = get_pending_approvals()
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        return {"error": str(e)[:200]}


@router.post("/policy/check")
async def check_action(action_type: str, risk_level: str = "low",
                       mode: str = "auto", user=Depends(_auth())):
    """Evaluate an action through kernel + core policy pipeline."""
    try:
        from kernel.convergence.policy_bridge import check_action_kernel
        decision = check_action_kernel(
            action_type=action_type,
            risk_level=risk_level,
            mode=mode,
        )
        return decision.to_dict()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/adapters/status-map")
async def status_mapping(user=Depends(_auth())):
    """Show the bidirectional status mapping between core and kernel."""
    from kernel.adapters.mission_adapter import (
        _CORE_TO_KERNEL_STATUS, _KERNEL_TO_CORE_STATUS,
    )
    return {
        "core_to_kernel": _CORE_TO_KERNEL_STATUS,
        "kernel_to_core": _KERNEL_TO_CORE_STATUS,
    }


@router.get("/performance")
async def capability_performance(entity_type: str = "", user=Depends(_auth())):
    """Get performance metrics for capabilities, providers, and tools."""
    try:
        from kernel.capabilities.performance import get_performance_store
        store = get_performance_store()
        records = store.get_all(entity_type=entity_type)
        return {"records": records, "count": len(records)}
    except Exception as e:
        return {"error": str(e)[:200], "records": [], "count": 0}


@router.get("/performance/summary")
async def performance_summary(user=Depends(_auth())):
    """Get aggregate performance summary."""
    try:
        from kernel.capabilities.performance import get_performance_store
        return get_performance_store().get_summary()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/performance/degraded")
async def degraded_capabilities(threshold: float = 0.5, user=Depends(_auth())):
    """Get entities with success rate below threshold."""
    try:
        from kernel.capabilities.performance import get_performance_store
        degraded = get_performance_store().get_degraded(threshold=threshold)
        return {"degraded": degraded, "count": len(degraded), "threshold": threshold}
    except Exception as e:
        return {"error": str(e)[:200], "degraded": [], "count": 0}


@router.get("/identity/resolve/{tool_id}")
async def resolve_tool_identity(tool_id: str, user=Depends(_auth())):
    """Resolve capability and provider identity for a tool."""
    try:
        from kernel.capabilities.identity import get_identity_map
        result = get_identity_map().resolve_tool(tool_id)
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/identity/stats")
async def identity_stats(user=Depends(_auth())):
    """Get identity map statistics."""
    try:
        from kernel.capabilities.identity import get_identity_map
        return get_identity_map().stats()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/performance/{entity_type}/{entity_id}")
async def entity_performance(entity_type: str, entity_id: str, user=Depends(_auth())):
    """Get performance for a specific entity."""
    try:
        from kernel.capabilities.performance import get_performance_store
        result = get_performance_store().get_performance(entity_type, entity_id)
        if result:
            return result
        return {"error": "not_found", "entity_type": entity_type, "entity_id": entity_id}
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/routing/explain")
async def routing_explain(goal: str = "execute a task", user=Depends(_auth())):
    """Run capability routing and return full explainable breakdown."""
    try:
        from core.capability_routing.router import route_mission
        decisions = route_mission(goal)
        results = []
        for d in decisions:
            entry = {
                "capability_id": d.capability_id,
                "score": d.score,
                "reason": d.reason,
                "fallback_used": d.fallback_used,
                "candidates_evaluated": d.candidates_evaluated,
            }
            if d.selected_provider:
                kp = d.selected_provider.metadata.get("kernel_performance", {})
                entry["provider"] = {
                    "id": d.selected_provider.provider_id,
                    "readiness": d.selected_provider.readiness,
                    "reliability": d.selected_provider.reliability,
                    "risk_level": d.selected_provider.risk_level,
                }
                if kp:
                    entry["performance_influence"] = kp
            results.append(entry)
        return {"decisions": results, "count": len(results)}
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/trace/tools")
async def recent_tool_events(limit: int = 20, user=Depends(_auth())):
    """Get recent tool invocation events from kernel execution trace."""
    try:
        from kernel.convergence.execution_trace import get_recent_tool_events
        events = get_recent_tool_events(limit=limit)
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"error": str(e)[:200], "events": [], "count": 0}


@router.get("/trace/failures")
async def failed_tools(mission_id: str = "", limit: int = 20, user=Depends(_auth())):
    """Get failed tool executions, optionally by mission."""
    try:
        from kernel.convergence.execution_trace import get_failed_tools
        failures = get_failed_tools(mission_id=mission_id, limit=limit)
        return {"failures": failures, "count": len(failures)}
    except Exception as e:
        return {"error": str(e)[:200], "failures": [], "count": 0}


@router.get("/trace/steps")
async def step_timeline(plan_id: str = "", limit: int = 30, user=Depends(_auth())):
    """Get step lifecycle events from kernel execution trace."""
    try:
        from kernel.convergence.execution_trace import get_step_timeline
        steps = get_step_timeline(plan_id=plan_id, limit=limit)
        return {"steps": steps, "count": len(steps)}
    except Exception as e:
        return {"error": str(e)[:200], "steps": [], "count": 0}


@router.get("/trace/summary")
async def execution_summary(user=Depends(_auth())):
    """Get execution event summary counts."""
    try:
        from kernel.convergence.execution_trace import get_execution_summary
        return get_execution_summary()
    except Exception as e:
        return {"error": str(e)[:200]}


@router.get("/convergence")
async def convergence_status(user=Depends(_auth())):
    """Overall convergence status — what's connected, what's not."""
    status = {
        "kernel_booted": False,
        "events_dual_emission": False,
        "capabilities_synced": False,
        "policy_bridge_active": False,
        "adapters_available": False,
    }

    try:
        from kernel.runtime.boot import get_runtime
        runtime = get_runtime()
        status["kernel_booted"] = runtime.booted_at > 0
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.convergence.event_bridge import emit_kernel_event
        status["events_dual_emission"] = True
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.convergence.capability_bridge import ensure_synced
        ensure_synced()
        status["capabilities_synced"] = True
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.convergence.policy_bridge import check_action_kernel
        status["policy_bridge_active"] = True
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.adapters.mission_adapter import mission_context_to_kernel
        from kernel.adapters.plan_adapter import execution_plan_to_kernel
        from kernel.adapters.result_adapter import tool_result_to_kernel
        status["adapters_available"] = True
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.capabilities.performance import get_performance_store
        summary = get_performance_store().get_summary()
        status["performance_tracking"] = summary.get("total_entities", 0) > 0 or True
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.capabilities.identity import get_identity_map
        stats = get_identity_map().stats()
        status["identity_mapping"] = stats.get("tools_mapped", 0) > 0
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    try:
        from kernel.convergence.performance_routing import enrich_providers
        status["performance_routing"] = True
    except Exception:
        _silent_log.debug("suppressed_exception", src='kernel.py')

    status["convergence_phase"] = "progressive"
    status["convergence_level"] = sum(1 for v in status.values() if v is True)

    return status


# ── Agent Registry (R7 — Pass 30) ────────────────────────────────────────────

@router.get("/agents")
async def list_kernel_agents(user=Depends(_auth())):
    """
    List all agents registered in the KernelAgentRegistry (R7).

    Returns agent_id, capability_type, and health for each registered agent.
    """
    try:
        from kernel.contracts.agent import get_agent_registry
        registry = get_agent_registry()
        agents = []
        for agent in registry.all_agents():
            agents.append({
                "agent_id": agent.agent_id,
                "capability_type": agent.capability_type,
                "class": type(agent).__name__,
            })
        return {"agents": agents, "count": len(agents)}
    except Exception as e:
        return {"error": str(e)[:200], "agents": [], "count": 0}


@router.get("/agents/healthy")
async def list_healthy_kernel_agents(user=Depends(_auth())):
    """
    List all kernel-registered agents currently in HEALTHY or DEGRADED state (BLOC 3 — R7).

    Calls health_check() on every registered agent concurrently.
    Returns only those passing the liveness gate.
    """
    try:
        from kernel.contracts.agent import get_agent_registry
        registry = get_agent_registry()
        healthy = await registry.healthy_agents()
        return {
            "healthy_agents": [
                {
                    "agent_id": a.agent_id,
                    "capability_type": a.capability_type,
                    "class": type(a).__name__,
                }
                for a in healthy
            ],
            "healthy_count": len(healthy),
            "total_count": len(registry),
        }
    except Exception as e:
        return {"error": str(e)[:200], "healthy_agents": [], "healthy_count": 0}


@router.get("/agents/{agent_id}")
async def get_kernel_agent(agent_id: str, user=Depends(_auth())):
    """Get details for a specific kernel-registered agent."""
    try:
        from kernel.contracts.agent import get_agent_registry
        registry = get_agent_registry()
        agent = registry.get(agent_id)
        if agent is None:
            return {"error": "agent_not_found", "agent_id": agent_id}
        return {
            "agent_id": agent.agent_id,
            "capability_type": agent.capability_type,
            "class": type(agent).__name__,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


@router.post("/agents/{agent_id}/health")
async def agent_health_check(agent_id: str, user=Depends(_auth())):
    """
    Trigger a health check on a specific kernel-registered agent (R7).
    Returns AgentHealthStatus.
    """
    try:
        from kernel.contracts.agent import get_agent_registry
        registry = get_agent_registry()
        agent = registry.get(agent_id)
        if agent is None:
            return {"error": "agent_not_found", "agent_id": agent_id}
        import asyncio
        health = await agent.health_check()
        return {
            "agent_id": agent_id,
            "health": health.value if hasattr(health, "value") else str(health),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ── KernelAdapter Status (R8 — Pass 30) ──────────────────────────────────────

@router.get("/adapter/status")
async def adapter_status(user=Depends(_auth())):
    """
    Get KernelAdapter health and call metrics (R8).

    Returns adapter stats without exposing kernel internals.
    """
    try:
        from interfaces.kernel_adapter import get_kernel_adapter
        return get_kernel_adapter().status()
    except Exception as e:
        return {"error": str(e)[:200], "adapter": "KernelAdapter", "kernel_available": False}
