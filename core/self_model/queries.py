"""
core/self_model/queries.py — Structured queries against the Self-Model.

These functions answer the key questions the Self-Model exists to address.
All operate on a SelfModel snapshot — no side effects.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

from core.self_model.model import (
    SelfModel, CapabilityStatus, ComponentStatus, HealthStatus,
    ModificationZone,
)


def _performance_label(d: dict) -> str:
    """Build a human-readable performance label for self-model limitations."""
    entity = f"{d['entity_type']} '{d['entity_id']}'"
    rate = f"{d['success_rate']:.0%}"
    trend = d.get("trend", "unknown")

    if d["success_rate"] < 0.3:
        status = "failing frequently"
    elif d["success_rate"] < 0.5:
        status = "weak"
    else:
        status = "below threshold"

    label = f"{entity} {status} (success rate {rate}"
    if trend == "degrading":
        label += ", trend: degrading"
    elif trend == "improving":
        label += ", trend: improving"
    label += f", {d['total']} samples)"

    return label


# ── Capability queries ────────────────────────────────────────────────────────

def what_can_i_do(model: SelfModel) -> list[dict]:
    """What capabilities are ready right now?"""
    return [
        {"id": c.id, "name": c.name, "source": c.source, "confidence": c.confidence}
        for c in model.capabilities.values()
        if c.status == CapabilityStatus.READY
    ]


def what_cannot_i_do(model: SelfModel) -> list[dict]:
    """What capabilities are unavailable or not configured?"""
    blocked = (CapabilityStatus.UNAVAILABLE, CapabilityStatus.NOT_CONFIGURED)
    return [
        {"id": c.id, "name": c.name, "status": c.status.value, "error": c.error}
        for c in model.capabilities.values()
        if c.status in blocked
    ]


def what_is_degraded(model: SelfModel) -> list[dict]:
    """What capabilities or components are degraded?"""
    result = []
    for c in model.capabilities.values():
        if c.status == CapabilityStatus.DEGRADED:
            result.append({"id": c.id, "type": "capability", "confidence": c.confidence})
    for comp in model.components.values():
        if comp.status == ComponentStatus.ERROR:
            result.append({"id": comp.id, "type": comp.type, "error": comp.error})
    for h in model.health.values():
        if h.status == HealthStatus.DEGRADED:
            result.append({"id": h.name, "type": "health", "detail": h.detail})
    return result


def what_requires_approval(model: SelfModel) -> list[dict]:
    """What capabilities or components require human approval?"""
    result = []
    for c in model.capabilities.values():
        if c.status == CapabilityStatus.APPROVAL_REQUIRED:
            result.append({"id": c.id, "type": "capability", "risk": c.risk_level})
    for comp in model.components.values():
        if comp.status == ComponentStatus.APPROVAL_REQUIRED:
            result.append({"id": comp.id, "type": comp.type})
    return result


def what_requires_configuration(model: SelfModel) -> list[dict]:
    """What components need secrets or configuration?"""
    return [
        {
            "id": comp.id,
            "type": comp.type,
            "missing_secrets": comp.missing_secrets,
            "reason": comp.reason,
        }
        for comp in model.components.values()
        if comp.status in (ComponentStatus.NOT_CONFIGURED, ComponentStatus.MISSING_SECRET)
    ]


def what_is_unsafe_to_modify(model: SelfModel) -> list[dict]:
    """What paths/domains are restricted or forbidden for modification?"""
    return [
        b.to_dict()
        for b in model.boundaries
        if b.zone in (ModificationZone.RESTRICTED, ModificationZone.FORBIDDEN)
    ]


def what_is_reliable(model: SelfModel, min_reliability: float = 0.8) -> list[dict]:
    """What capabilities have high reliability?"""
    return [
        {"id": c.id, "reliability": round(c.reliability, 3), "usage_count": c.usage_count}
        for c in model.capabilities.values()
        if c.reliability >= min_reliability and c.usage_count > 0
    ]


def what_is_unstable(model: SelfModel, max_reliability: float = 0.5) -> list[dict]:
    """What capabilities have low reliability?"""
    return [
        {
            "id": c.id,
            "reliability": round(c.reliability, 3),
            "failure_count": c.failure_count,
            "usage_count": c.usage_count,
        }
        for c in model.capabilities.values()
        if 0 < c.reliability < max_reliability
    ]


def what_is_missing(model: SelfModel) -> list[dict]:
    """What components are missing or misconfigured?"""
    missing = []
    for comp in model.components.values():
        if comp.status in (
            ComponentStatus.UNAVAILABLE,
            ComponentStatus.NOT_CONFIGURED,
            ComponentStatus.MISSING_SECRET,
        ):
            missing.append({
                "id": comp.id,
                "type": comp.type,
                "status": comp.status.value,
                "missing_secrets": comp.missing_secrets,
            })
    for h in model.health.values():
        if h.status == HealthStatus.UNKNOWN:
            missing.append({"id": h.name, "type": "health", "status": "unknown"})
    return missing


# ── Summary queries ───────────────────────────────────────────────────────────

def readiness_score(model: SelfModel) -> float:
    """Overall system readiness as 0.0–1.0.

    Weighted average of:
      - Capability readiness (40%)
      - Component readiness (30%)
      - Health signals (30%)
    """
    # Capability score
    cap_total = len(model.capabilities)
    if cap_total > 0:
        cap_ready = sum(1 for c in model.capabilities.values()
                        if c.status == CapabilityStatus.READY)
        cap_score = cap_ready / cap_total
    else:
        cap_score = 0.0

    # Component score
    comp_total = len(model.components)
    if comp_total > 0:
        comp_ready = sum(1 for c in model.components.values()
                         if c.status == ComponentStatus.READY)
        comp_score = comp_ready / comp_total
    else:
        comp_score = 0.0

    # Health score
    health_total = len(model.health)
    if health_total > 0:
        health_ok = sum(1 for h in model.health.values()
                        if h.status == HealthStatus.HEALTHY)
        health_score = health_ok / health_total
    else:
        health_score = 0.0

    return round(0.4 * cap_score + 0.3 * comp_score + 0.3 * health_score, 3)


def capability_summary(model: SelfModel) -> dict:
    """Summary counts by capability status."""
    counts: dict[str, int] = {}
    for c in model.capabilities.values():
        key = c.status.value
        counts[key] = counts.get(key, 0) + 1
    return {
        "total": len(model.capabilities),
        "by_status": counts,
    }


def component_summary(model: SelfModel) -> dict:
    """Summary counts by component status."""
    counts: dict[str, int] = {}
    for c in model.components.values():
        key = c.status.value
        counts[key] = counts.get(key, 0) + 1
    return {
        "total": len(model.components),
        "by_status": counts,
    }


def health_summary(model: SelfModel) -> dict:
    """Summary of health signals."""
    counts: dict[str, int] = {}
    for h in model.health.values():
        key = h.status.value
        counts[key] = counts.get(key, 0) + 1
    return {
        "total": len(model.health),
        "by_status": counts,
    }


# ── Per-capability queries ────────────────────────────────────────────────────

def get_capability_confidence(model: SelfModel, capability_id: str) -> float:
    """Get confidence for a specific capability. Returns 0.0 if not found."""
    cap = model.capabilities.get(capability_id)
    return cap.confidence if cap else 0.0


def get_tools_for_capability(model: SelfModel, capability_id: str) -> list[str]:
    """Get tool/component dependencies for a capability."""
    cap = model.capabilities.get(capability_id)
    return cap.dependencies if cap else []


def get_blocked_capabilities(model: SelfModel) -> list[dict]:
    """Capabilities blocked by approval, config, or unavailability."""
    blocked = (
        CapabilityStatus.UNAVAILABLE,
        CapabilityStatus.NOT_CONFIGURED,
        CapabilityStatus.APPROVAL_REQUIRED,
    )
    return [
        {"id": c.id, "status": c.status.value, "reason": c.error or ", ".join(c.constraints)}
        for c in model.capabilities.values()
        if c.status in blocked
    ]


def get_missing_dependencies(model: SelfModel) -> list[dict]:
    """Components that are dependencies of capabilities but not ready."""
    not_ready = {
        comp.id for comp in model.components.values()
        if comp.status != ComponentStatus.READY
    }
    result = []
    for cap in model.capabilities.values():
        for dep in cap.dependencies:
            if dep in not_ready:
                result.append({
                    "capability": cap.id,
                    "dependency": dep,
                    "dependency_status": model.components[dep].status.value
                    if dep in model.components else "unknown",
                })
    return result


def get_runtime_health(model: SelfModel) -> dict:
    """All health signals as a flat dict."""
    return {h.name: h.status.value for h in model.health.values()}


def get_economic_status() -> dict:
    """
    Economic intelligence layer availability summary.

    Returns operational status of each economic subsystem.
    Fail-open: returns partial status on errors.
    """
    status: dict = {
        "strategic_memory_active": False,
        "strategic_memory_records": 0,
        "recommendations_available": False,
        "recommendations_count": 0,
        "kpi_tracking_active": False,
        "playbook_chains_available": False,
        "chains_count": 0,
        "economic_capabilities_registered": 0,
    }

    try:
        from core.economic.strategic_memory import get_strategic_memory
        mem = get_strategic_memory()
        status["strategic_memory_active"] = True
        status["strategic_memory_records"] = mem.count
    except Exception as _exc:
        log.warning("swallowed_exception", action="strategic_memory_status", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        evals = evaluator.evaluate_all()
        total_recs = sum(len(e.recommendations) for e in evals)
        status["recommendations_available"] = total_recs > 0
        status["recommendations_count"] = total_recs
    except Exception as _exc:
        log.warning("swallowed_exception", action="recommendations_status", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.objectives.objective_horizon import get_horizon_manager
        mgr = get_horizon_manager()
        data = mgr.to_dict()
        status["kpi_tracking_active"] = len(data.get("metrics", {})) > 0
    except Exception as _exc:
        log.warning("swallowed_exception", action="kpi_tracking_status", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.economic.playbook_composition import BUILT_IN_CHAINS
        status["playbook_chains_available"] = len(BUILT_IN_CHAINS) > 0
        status["chains_count"] = len(BUILT_IN_CHAINS)
    except Exception as _exc:
        log.warning("swallowed_exception", action="playbook_chains_status", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from kernel.capabilities.registry import get_capability_registry
        reg = get_capability_registry()
        economic = reg.list_by_category("economic")
        status["economic_capabilities_registered"] = len(economic)
    except Exception as _exc:
        log.warning("swallowed_exception", action="economic_capabilities_status", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return status


def get_autonomy_limits(model: SelfModel) -> dict:
    """Current autonomy limits as a flat dict."""
    a = model.autonomy
    return {
        "mode": a.mode.value,
        "tools_need_approval": a.requires_approval_for_tools,
        "code_patches_need_approval": a.requires_approval_for_code_patch,
        "external_calls_need_approval": a.requires_approval_for_external_calls,
        "deployment_needs_approval": a.requires_approval_for_deployment,
        "max_risk_auto": a.max_risk_auto_approve,
        "max_files": a.max_files_per_patch,
        "max_steps": a.max_steps_per_mission,
    }


def get_known_limitations(model: SelfModel) -> list[dict]:
    """
    Derive known operational limitations from real runtime state.

    Each limitation is factual, with source and severity.
    Priority: critical > high > medium > low.
    """
    limitations: list[dict] = []

    # 1. Unavailable MCP servers
    for comp in model.components.values():
        if comp.type == "mcp" and comp.status in (
            ComponentStatus.UNAVAILABLE, ComponentStatus.ERROR
        ):
            limitations.append({
                "id": comp.id,
                "category": "mcp",
                "severity": "medium",
                "description": f"{comp.id} not available: {comp.reason or comp.error or comp.status.value}",
                "source": "mcp_registry",
            })

    # 2. Missing secrets
    for comp in model.components.values():
        if comp.missing_secrets:
            limitations.append({
                "id": f"{comp.id}:missing_secrets",
                "category": "configuration",
                "severity": "medium",
                "description": f"{comp.id} missing secrets: {', '.join(comp.missing_secrets)}",
                "source": "mcp_registry",
            })

    # 3. Unconfigured connectors
    for comp in model.components.values():
        if comp.type == "connector" and comp.status == ComponentStatus.NOT_CONFIGURED:
            limitations.append({
                "id": comp.id,
                "category": "connector",
                "severity": "low",
                "description": f"Connector {comp.id} not configured",
                "source": "module_manager",
            })

    # 4. Degraded health signals
    for h in model.health.values():
        if h.status == HealthStatus.DEGRADED:
            limitations.append({
                "id": f"health:{h.name}",
                "category": "health",
                "severity": "high",
                "description": f"{h.name} degraded: {h.detail}",
                "source": "health_probe",
            })

    # 5. Unknown health signals
    for h in model.health.values():
        if h.status == HealthStatus.UNKNOWN:
            limitations.append({
                "id": f"health:{h.name}",
                "category": "health",
                "severity": "medium",
                "description": f"{h.name} status unknown",
                "source": "health_probe",
            })

    # 6. Approval-gated capabilities (blocks autonomous execution)
    approval_count = sum(
        1 for c in model.capabilities.values()
        if c.status == CapabilityStatus.APPROVAL_REQUIRED
    )
    if approval_count > 0:
        limitations.append({
            "id": "approval_gating",
            "category": "autonomy",
            "severity": "low",
            "description": f"{approval_count} capabilities require human approval before use",
            "source": "capability_graph",
        })

    # 7. Experimental or unstable capabilities
    for cap in model.capabilities.values():
        if cap.status == CapabilityStatus.EXPERIMENTAL:
            limitations.append({
                "id": f"experimental:{cap.id}",
                "category": "stability",
                "severity": "low",
                "description": f"{cap.id} is experimental — may be unreliable",
                "source": "capability_graph",
            })
        elif cap.reliability > 0 and cap.reliability < 0.5:
            limitations.append({
                "id": f"unstable:{cap.id}",
                "category": "stability",
                "severity": "medium",
                "description": f"{cap.id} reliability is {cap.reliability:.0%}",
                "source": "capability_graph",
            })

    # 8. Kernel performance-derived limitations (fail-open)
    try:
        from kernel.capabilities.performance import get_performance_store
        store = get_performance_store()
        degraded = store.get_degraded(threshold=0.5)
        for d in degraded[:5]:
            _label = _performance_label(d)
            limitations.append({
                "id": f"kernel_perf:{d['entity_type']}:{d['entity_id']}",
                "category": "performance",
                "severity": "medium" if d["success_rate"] < 0.3 else "low",
                "description": _label,
                "source": "kernel_performance",
            })

        # Low confidence entities (enough samples but unstable)
        for record in store.get_all():
            if record["total"] >= 5 and record["confidence"] < 0.3:
                limitations.append({
                    "id": f"kernel_confidence:{record['entity_type']}:{record['entity_id']}",
                    "category": "performance",
                    "severity": "low",
                    "description": (
                        f"{record['entity_type']} '{record['entity_id']}' has low confidence "
                        f"({record['confidence']:.2f}) — insufficient or inconsistent data"
                    ),
                    "source": "kernel_performance",
                })
    except Exception:
        log.debug("swallowed_exception", exc_info=True)

    # 9. Skill execution mode — preparation-only if no LLM configured
    try:
        from core.planning.skill_llm import _is_llm_available
        if not _is_llm_available():
            limitations.append({
                "id": "skill_execution_mode",
                "category": "capability",
                "severity": "medium",
                "description": (
                    "Skill execution is preparation-only (no LLM API key configured). "
                    "Skills build prompt contexts but cannot produce analysis output. "
                    "Configure OPENROUTER_API_KEY or OPENAI_API_KEY to enable productive execution."
                ),
                "source": "skill_llm",
            })
    except Exception as _exc:
        log.warning("swallowed_exception", action="skill_llm_capability_suggestion", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # 10. Economic intelligence — strategic memory and capability health
    try:
        from core.economic.strategic_memory import get_strategic_memory
        mem = get_strategic_memory()
        if mem.count == 0:
            limitations.append({
                "id": "economic_memory_empty",
                "category": "economic",
                "severity": "low",
                "description": (
                    "Strategic memory is empty — no execution outcomes recorded yet. "
                    "Execute playbooks to enable strategy learning."
                ),
                "source": "strategic_memory",
            })
    except Exception as _exc:
        log.warning("swallowed_exception", action="strategic_memory_capability_suggestion", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    try:
        from core.economic.strategy_evaluation import get_strategy_evaluator
        evaluator = get_strategy_evaluator()
        for ev in evaluator.evaluate_all():
            if ev.score <= 0.3 and ev.sample_count >= 3:
                limitations.append({
                    "id": f"weak_strategy:{ev.strategy_type}",
                    "category": "economic",
                    "severity": "medium",
                    "description": (
                        f"Strategy '{ev.strategy_type}' performing poorly "
                        f"({ev.score:.0%} across {ev.sample_count} executions)"
                    ),
                    "source": "strategy_evaluation",
                })
    except Exception as _exc:
        log.warning("swallowed_exception", action="strategy_evaluation_capability_suggestion", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Sort by severity (critical > high > medium > low)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    limitations.sort(key=lambda x: severity_order.get(x["severity"], 99))

    return limitations
