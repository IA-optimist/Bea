"""
core/capability_routing/router.py — Top-level routing orchestration.

Wires together: resolver → registry → scorer → decision.
This is the single function MetaOrchestrator calls to get a routing decision.

Fail-open: if capability routing fails entirely, returns a fallback
RoutingDecision that lets the legacy agent path proceed.
"""
from __future__ import annotations

import time
import structlog

from core.capability_routing.spec import (
    RoutingDecision, CapabilityRequirement, ProviderSpec,
    ProviderType,
)
from core.capability_routing.registry import get_provider_registry
from core.capability_routing.scorer import rank_providers
from core.capability_routing.resolver import resolve_capabilities

log = structlog.get_logger("capability_routing.router")


def route_mission(
    goal: str,
    classification: dict | None = None,
    mode: str = "auto",
) -> list[RoutingDecision]:
    """
    Primary entry point: resolve capabilities and route to best providers.

    Returns one RoutingDecision per required capability.
    Each decision contains the selected provider (or None if no provider found).

    This is ADDITIVE to the existing MetaOrchestrator flow:
    - The decisions are recorded in mission metadata
    - The best provider is used as a routing hint
    - Legacy agent execution remains the fallback

    Args:
        goal: Mission goal text.
        classification: Optional classification dict from MetaOrchestrator.
        mode: Execution mode hint.

    Returns:
        List of RoutingDecision (one per capability).
    """
    start = time.time()
    decisions: list[RoutingDecision] = []

    try:
        # 1. Resolve what capabilities are needed
        requirements = resolve_capabilities(goal, classification)
        log.info("capability_routing.resolved",
                 count=len(requirements),
                 capabilities=[r.capability_id for r in requirements])

        # 2. Get the provider registry (populates on first call)
        registry = get_provider_registry()

        # 3. For each capability, find and score providers
        for req in requirements:
            decision = _route_single(req, registry)
            decisions.append(decision)

    except Exception as e:
        log.warning("capability_routing.failed", err=str(e)[:120])
        # Fallback: return a single "unknown" decision so MetaOrchestrator
        # can proceed with legacy agent routing
        decisions = [RoutingDecision(
            capability_id="general.execution",
            selected_provider=None,
            reason=f"Capability routing failed: {str(e)[:80]}",
            fallback_used=True,
        )]

    # Enrich decisions with canonical agent context (fail-open)
    try:
        from core.agents.canonical_agents import get_canonical_runtime
        runtime = get_canonical_runtime()
        for d in decisions:
            d.__dict__ if hasattr(d, '__dict__') else {}
            agent_id = runtime.get_agent_for_capability(d.capability_id)
            if agent_id:
                if not hasattr(d, 'metadata') or d.metadata is None:
                    d.metadata = {}
                d.metadata["canonical_agent"] = agent_id.value
                d.metadata["canonical_llm_role"] = runtime.get_llm_role_for_capability(d.capability_id)
    except Exception:
        log.debug("swallowed_exception", exc_info=True)

    # Enrich decisions with domain skill context (fail-open)
    try:
        from core.skills.domain_skill_router import resolve_via_domain_routers
        # Ensure domain routers are registered (import triggers registration)
        import core.skills.security_skill_router  # noqa: F401
        for d in decisions:
            ctx = resolve_via_domain_routers(d.capability_id, goal)
            if ctx and ctx.get("matched"):
                d.metadata["domain_routing"] = ctx
                log.info("domain_routing.resolved",
                         capability=d.capability_id,
                         router=ctx.get("router", "unknown"),
                         domain=ctx.get("domain", "unknown"),
                         skills_count=ctx.get("skills_count", 0),
                         top_skill=ctx["top_skills"][0]["name"] if ctx.get("top_skills") else None,
                         blocked=ctx.get("blocked", False))
                if ctx.get("blocked"):
                    d.reason = f"BLOCKED: {ctx['block_reason']}"
                    d.metadata["blocked"] = True
                    d.metadata["block_reason"] = ctx["block_reason"]
    except Exception as _dr_err:
        log.debug("domain_routing.enrichment_failed", err=str(_dr_err)[:80])

    elapsed_ms = (time.time() - start) * 1000
    log.info("capability_routing.complete",
             decisions=len(decisions),
             selected=[d.capability_id for d in decisions if d.success],
             fallbacks=[d.capability_id for d in decisions if d.fallback_used],
             elapsed_ms=round(elapsed_ms, 1))

    return decisions


def _route_single(
    requirement: CapabilityRequirement,
    registry,
) -> RoutingDecision:
    """Route a single capability requirement to the best provider."""
    cap_id = requirement.capability_id

    # Get candidates from registry
    candidates = registry.get_providers(cap_id)

    # If no direct match, try fuzzy: check if any capability starts with our prefix
    if not candidates:
        candidates = _fuzzy_match(cap_id, registry)

    if not candidates:
        return RoutingDecision(
            capability_id=cap_id,
            selected_provider=None,
            reason=f"No providers registered for {cap_id}",
            fallback_used=True,
            candidates_evaluated=0,
        )

    # Enrich providers with kernel performance data (fail-open)
    try:
        from kernel.convergence.performance_routing import enrich_providers
        enrich_providers(candidates)
    except Exception:
        log.debug("swallowed_exception", exc_info=True)

    # Score all candidates
    scored = rank_providers(candidates, requirement)

    # Separate available from blocked
    available = [s for s in scored if not s.blocked]
    blocked = [s for s in scored if s.blocked]

    if not available:
        return RoutingDecision(
            capability_id=cap_id,
            selected_provider=None,
            reason=f"All {len(candidates)} providers blocked",
            fallback_used=True,
            candidates_evaluated=len(candidates),
            blocked_candidates=[s.to_dict() for s in blocked],
        )

    best = available[0]

    # Build explainable reason including performance influence
    reason = f"Selected {best.provider.provider_id} (score={best.total_score:.3f})"
    try:
        kp = best.provider.metadata.get("kernel_performance", {})
        if kp and kp.get("adjustment", 0) != 0:
            reason += f" | {kp['explanation']}"
    except Exception as _exc:
        log.warning("swallowed_exception", action="router_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    return RoutingDecision(
        capability_id=cap_id,
        selected_provider=best.provider,
        score=best.total_score,
        reason=reason,
        fallback_used=False,
        candidates_evaluated=len(candidates),
        all_candidates=[s.to_dict() for s in available],
        blocked_candidates=[s.to_dict() for s in blocked],
    )


def _fuzzy_match(cap_id: str, registry) -> list[ProviderSpec]:
    """
    Fuzzy capability matching: if exact ID not found, try prefix match.

    E.g., "code.patch" might match providers registered under "cap-bea-coder"
    if their category is "coding" and keywords overlap.
    """
    candidates = []
    prefix = cap_id.split(".")[0] if "." in cap_id else cap_id

    # Map common prefixes to capability graph categories
    _PREFIX_TO_CATEGORIES = {
        "code": ("coding", "review", "testing"),
        "research": ("analysis", "research"),
        "infra": ("deployment", "monitoring"),
        "security": ("security",),
        "content": ("writing",),
        "github": ("mcp",),
        "browser": ("mcp",),
        "finance": ("modules",),
        "memory": ("memory",),
        "workflow": ("connectors",),
        "filesystem": ("mcp",),
        "tool": ("restricted-tool",),
        "mcp": ("mcp",),
    }

    target_categories = _PREFIX_TO_CATEGORIES.get(prefix, ())
    if not target_categories:
        return []

    # Scan all capabilities for category match
    for known_cap_id in registry.get_all_capabilities():
        for provider in registry.get_providers(known_cap_id):
            cat = provider.metadata.get("category", "")
            if cat in target_categories:
                candidates.append(provider)
            # Also match on provider_type
            elif provider.provider_type.value in target_categories:
                candidates.append(provider)

    return candidates


def route_single_capability(
    capability_id: str,
    min_reliability: float = 0.0,
    max_risk: str = "high",
    prefer_type: ProviderType | None = None,
) -> RoutingDecision:
    """
    Direct capability routing for programmatic use.

    Skips goal parsing — route a known capability ID directly.
    Useful for internal subsystems that know exactly what they need.
    """
    requirement = CapabilityRequirement(
        capability_id=capability_id,
        min_reliability=min_reliability,
        max_risk=max_risk,
        prefer_type=prefer_type,
    )
    registry = get_provider_registry()
    return _route_single(requirement, registry)
