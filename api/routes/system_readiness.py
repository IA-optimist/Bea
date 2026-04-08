"""
api/routes/system_readiness.py — System readiness endpoint.

Reports which API components actually loaded vs which are missing.
Uses runtime route introspection (not the unused router_registry).
"""
from __future__ import annotations

import time
import structlog
from fastapi import APIRouter

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v3/system", tags=["system"])

# Expected routers and their signature routes.
# If a route prefix is found in the mounted routes, the component is "loaded".
EXPECTED_COMPONENTS = {
    "missions":           "/api/v3/missions",
    "auth":               "/auth/token",
    "websocket":          "/ws/",
    "sse_stream":         "/api/v2/stream",
    "learning":           "/api/v2/learning",
    "multimodal":         "/api/multimodal",
    "rag":                "/api/v2/rag",
    "agent_builder":      "/api/v2/agent-builder",
    "mission_control":    "/api/v3/mission-control",
    "browser":            "/api/v2/browser",
    "monitoring":         "/api/v3/monitoring",
    "voice":              "/api/v2/voice",
    "objectives":         "/api/v3/objectives",
    "self_improvement":   "/api/v2/self-improvement",
    "dashboard":          "/api/v3/dashboard",
    "approval":           "/api/v3/approval",
    "convergence":        "/api/v3/convergence",
    "performance":        "/api/v3/performance",
    "observability":      "/api/v3/observability",
    "finance":            "/api/v3/finance",
    "vault":              "/api/v3/vault",
    "identity":           "/api/v3/identity",
    "connectors":         "/api/v3/connectors",
    "cognitive":          "/api/v3/cognitive",
    "mcp_management":     "/api/v3/mcp",
    "skills":             "/api/v3/skills",
    "models":             "/api/v3/models",
    "execution":          "/api/v3/execution",
    "strategy":           "/api/v3/strategy",
    "kernel":             "/api/v3/kernel",
    "security_audit":     "/api/v3/security",
    "system":             "/api/v3/system",
    "health":             "/health",
}


@router.get("/readiness", tags=["system"])
async def system_readiness():
    """Report which API components are loaded vs missing.

    Introspects the running FastAPI app's mounted routes to determine
    which expected components actually loaded. This replaces the need
    for the unused router_registry.
    """
    from api.main import app

    # Collect all mounted route paths
    mounted_paths: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            mounted_paths.add(route.path)
        # Include sub-routes from mounted routers
        if hasattr(route, "routes"):
            for sub in route.routes:
                if hasattr(sub, "path"):
                    mounted_paths.add(sub.path)

    loaded = []
    failed = []
    for name, signature_path in EXPECTED_COMPONENTS.items():
        found = any(signature_path in p for p in mounted_paths)
        if found:
            loaded.append(name)
        else:
            failed.append(name)

    total_routes = len(mounted_paths)
    ready = len(failed) <= 5  # allow up to 5 optional missing components

    return {
        "ready": ready,
        "total_routes_mounted": total_routes,
        "components": {
            "loaded": len(loaded),
            "failed": len(failed),
            "loaded_list": sorted(loaded),
            "failed_list": sorted(failed),
        },
        "summary": f"{len(loaded)}/{len(EXPECTED_COMPONENTS)} components loaded, {total_routes} routes mounted",
    }
