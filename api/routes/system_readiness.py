"""
api/routes/system_readiness.py — System readiness endpoint.

Reports which API components actually loaded vs which are missing.
Uses runtime route introspection (not the unused router_registry).
"""
from __future__ import annotations

import os
import socket
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api._deps import require_auth

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v3/system", tags=["system"], dependencies=[Depends(require_auth)])

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


def _runtime_probes() -> tuple[bool, dict]:
    ready = True
    probes = {}

    try:
        from config.settings import get_settings
        settings = get_settings()
        active_providers = []
        if getattr(settings, "openrouter_api_key", ""):
            active_providers.append("openrouter")
        if getattr(settings, "anthropic_api_key", ""):
            active_providers.append("anthropic")
        if getattr(settings, "openai_api_key", ""):
            active_providers.append("openai")
        strategy = os.environ.get("MODEL_STRATEGY", "") or (active_providers[0] if active_providers else "none")
        has_llm = bool(active_providers)
        probes["llm_key"] = {
            "ok": has_llm,
            "providers": active_providers,
            "strategy": strategy,
            "detail": (
                f"providers={active_providers} strategy={strategy}"
                if has_llm
                else "no LLM key configured"
            ),
        }
        if not has_llm:
            ready = False
    except Exception as exc:
        probes["llm_key"] = {"ok": False, "detail": str(exc)[:120]}
        ready = False

    try:
        from config.settings import get_settings
        settings = get_settings()
        host = getattr(settings, "qdrant_host", "") or "qdrant"
        port = int(getattr(settings, "qdrant_port", 6333) or 6333)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        qdrant_ok = result == 0
        probes["qdrant"] = {
            "ok": qdrant_ok,
            "host": f"{host}:{port}",
            "detail": "reachable" if qdrant_ok else "unreachable",
        }
        if not qdrant_ok:
            ready = False
    except Exception as exc:
        probes["qdrant"] = {"ok": False, "detail": str(exc)[:120]}
        ready = False

    try:
        from core.meta_orchestrator import get_meta_orchestrator
        orchestrator = get_meta_orchestrator()
        breaker = getattr(orchestrator, "_circuit_breaker", None)
        breaker_open = None
        if breaker is not None and hasattr(breaker, "status"):
            breaker_open = bool(breaker.status().get("open", False))
        probes["orchestrator"] = {
            "ok": True,
            "detail": f"circuit_breaker={breaker_open}",
        }
    except Exception as exc:
        probes["orchestrator"] = {"ok": False, "detail": str(exc)[:120]}
        ready = False

    return ready, probes


def build_readiness_payload(
    mounted_paths: set[str],
    expected_components: dict[str, str] | None = None,
) -> dict:
    expected = expected_components or EXPECTED_COMPONENTS

    loaded = []
    failed = []
    for name, signature_path in expected.items():
        found = any(signature_path in p for p in mounted_paths)
        if found:
            loaded.append(name)
        else:
            failed.append(name)

    total_routes = len(mounted_paths)
    production = os.environ.get("BEA_PRODUCTION", "").lower() in ("1", "true", "yes")
    allowed_failures = 0 if production else len(expected)
    components_ready = len(failed) <= allowed_failures
    probes_ready, probes = _runtime_probes()
    ready = components_ready and probes_ready

    return {
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "probes": probes,
        "total_routes_mounted": total_routes,
        "components": {
            "loaded": len(loaded),
            "failed": len(failed),
            "loaded_list": sorted(loaded),
            "failed_list": sorted(failed),
        },
        "allowed_failures": allowed_failures,
        "summary": f"{len(loaded)}/{len(expected)} components loaded, {total_routes} routes mounted",
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

    payload = build_readiness_payload(mounted_paths)
    status_code = 200 if payload["ready"] else 503
    return JSONResponse(
        {"ok": payload["ready"], "data": payload},
        status_code=status_code,
    )
