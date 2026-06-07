"""
Unified Router Namespace — BeaMax
════════════════════════════════════

Centralized import entry point for all routing systems.

PRODUCTION ROUTERS:
- adaptive_routing: Health tracking, circuit breaker integration
- llm_routing_policy: Budget/latency/quality policy enforcement
- capability_routing: Capability-based provider selection
- domain_router: Domain classification (code/research/creative/general)
- task_router: Agent selection logic

IMPORT PATTERNS:

Option A — Individual imports (recommended for clarity):
    from core.routing import get_enhanced_tracker, RoutingPolicy, route_mission

Option B — Namespace imports (for bulk imports):
    from core import routing
    tracker = routing.get_enhanced_tracker()
    policy = routing.RoutingPolicy(...)
    result = routing.route_mission(...)

Option C — Legacy direct imports (still supported):
    from core.adaptive_routing import get_enhanced_tracker
    from core.llm_routing_policy import RoutingPolicy
    from core.capability_routing.router import route_mission

ARCHITECTURE:
- This module is a thin facade (no business logic)
- All routers remain in their original locations
- No forced migration (opt-in convenience layer)
"""

# ── Adaptive Routing (health tracking, circuit breaker) ──────────────────────
from core.adaptive_routing import (
    get_enhanced_tracker,
    AdaptiveRoutingManager,
)

# ── LLM Routing Policy (budget, latency, quality) ────────────────────────────
from core.llm_routing_policy import (
    RoutingPolicy,
    get_routing_policy,
)

# ── Capability Routing (capability-based provider selection) ─────────────────
from core.capability_routing.router import (
    route_mission,
    CapabilityRouter,
)

# ── Domain Router (domain classification) ────────────────────────────────────
from core.domain_router import (
    get_domain_router,
    classify_domain,
    detect_domain,
    DomainRouter,
)

# ── Task Router (agent selection) ────────────────────────────────────────────
from core.task_router import (
    route_to_agent,
    TaskRouter,
)

# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    # Adaptive routing
    "get_enhanced_tracker",
    "AdaptiveRoutingManager",
    # LLM policy
    "RoutingPolicy",
    "get_routing_policy",
    # Capability routing
    "route_mission",
    "CapabilityRouter",
    # Domain classification
    "get_domain_router",
    "classify_domain",
    "detect_domain",
    "DomainRouter",
    # Agent selection
    "route_to_agent",
    "TaskRouter",
]
