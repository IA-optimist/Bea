"""
JARVIS MAX — Canonical API (FastAPI)
This is the ONE backend API. Loaded by main.py (the canonical entrypoint).

Structure (1800+ lines — refactor into routers planned):
  Lines ~70-220:   App init, CORS, router mounts
  Lines ~220-260:  Startup, auth helpers
  Lines ~260-330:  Pydantic models, lazy getters
  Lines ~330-810:  POST /api/v2/task (main mission handler)
  Lines ~810-1060: Task/mission CRUD endpoints
  Lines ~1060-1180: Health, status, metrics, diagnostics, logs, restart
  Lines ~1180-1310: Mode system, SSE stream, legacy aliases
  Lines ~1310-1550: Decision memory, multimodal, auth, websocket
  Lines ~1550-1800: Self-improvement, tools, knowledge, static mount

Legacy v1 routes (/api/mission, /api/health, etc.) are included as aliases.
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import time
from pathlib import Path
from typing import Any, Optional

import structlog
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from api._deps import require_auth, get_start_time, _check_auth
from api.token_utils import strip_bearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = structlog.get_logger()


def _extract_final_output(text: str) -> str:
    """
    Post-processing du final_output : si le texte ressemble à du JSON brut,
    le convertit en texte lisible. Sinon, retourne tel quel.
    """
    if not text:
        return text
    stripped = text.strip()
    if "{" in stripped and "}" in stripped:
        try:
            data = _json.loads(stripped)
            # Extraire les champs textuels les plus probables
            readable = (
                data.get("result")
                or data.get("output")
                or data.get("response")
                or data.get("content")
                or data.get("reasoning")
                or data.get("answer")
                or data.get("text")
                or data.get("message")
                or str(data)
            )
            return f"[Résultat de Jarvis]\n{str(readable)[:2000]}"
        except (_json.JSONDecodeError, Exception):
            pass
    return text


# ── App ───────────────────────────────────────────────────────

# Disable public /docs and /redoc in production (expose only when ENABLE_API_DOCS=1)
ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", os.environ.get("JARVIS_DOCS", "0"))
_enable_docs = ENABLE_API_DOCS == "1"

app = FastAPI(
    title="JarvisMax API",
    description="Plateforme multi-agents autonome JarvisMax — API v2",
    version="2.0.0",
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
)

# CORS: restrict to known origins (override via CORS_ORIGINS env var)
_cors_origins = os.environ.get("CORS_ORIGINS", "").strip()
_allowed_origins = (
    [o.strip() for o in _cors_origins.split(",") if o.strip()]
    if _cors_origins
    else [
        "http://localhost:8000",       # local dev
        "http://localhost:3000",       # local frontend
        "http://10.0.2.2:8000",       # Android emulator
        "http://127.0.0.1:8000",      # loopback
    ]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Jarvis-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# ── Global access enforcement middleware (fail-closed) ────────
try:
    from api.middleware import AccessEnforcementMiddleware
    app.add_middleware(AccessEnforcementMiddleware)
except ImportError as _enf_err:
    log.error("access_enforcement_MISSING", err=str(_enf_err),
              note="Security middleware unavailable — API will rely on per-route auth only")
    # NOT silenced: this is logged as error, not warning

# ── Security headers middleware ───────────────────────────────
try:
    from api.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Rate limiting middleware (sliding window per IP+path) ─────
try:
    from api.rate_limiter import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
except ImportError as _rl_err:
    log.error("rate_limiter_MISSING", err=str(_rl_err))

# ── Router Registry ───────────────────────────────────────────
try:
    from api.router_registry import register_router as _reg_fn, register_failure as _fail_fn
except Exception:
    def _reg_fn(*a, **kw): pass
    def _fail_fn(*a, **kw): pass

# ── Import du routeur WebSockets v3 ───────────────────────────
try:
    from api.ws import router as ws_router
    app.include_router(ws_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur SSE Streaming ───────────────────────────
try:
    from api.stream_router import router as stream_router
    app.include_router(stream_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Learning ─────────────────────────────────
try:
    from api.routes.learning import router as learning_router
    app.include_router(learning_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Multimodal ───────────────────────────────
try:
    from api.routes.multimodal import router as multimodal_router
    app.include_router(multimodal_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur RAG ──────────────────────────────────────
try:
    from api.routes.rag import router as rag_router
    app.include_router(rag_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Agent Builder ───────────────────────────
try:
    from api.routes.agent_builder import router as agent_builder_router
    app.include_router(agent_builder_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Phase 9 Mission Control ──────────────────
try:
    from api.routes.mission_control import router as mission_control_router
    app.include_router(mission_control_router)
except Exception as _e:
    log.warning("mission_control_router_unavailable", err=str(_e))

# ── Import du routeur Browser (Phase 8) ───────────────────────
try:
    from api.routes.browser import router as browser_router
    app.include_router(browser_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Routing Diagnostics ──────────────────────
try:
    from api.routes.routing_diagnostics import router as routing_diag_router
    if routing_diag_router:
        app.include_router(routing_diag_router)
except Exception as _e:
    log.warning("routing_diagnostics_router_unavailable", err=str(_e))

# ── Import du routeur Monitoring (Phase 3 + Phase 8) ──────────
try:
    from api.routes.monitoring import router as monitoring_router
    app.include_router(monitoring_router)
except Exception as _e:
    log.warning("monitoring_router_unavailable", err=str(_e))

# ── Import du routeur Voice & Call (Phase 10) ──────────────────
try:
    from api.routes.voice import router as voice_router
    app.include_router(voice_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Objective Engine ─────────────────────────
try:
    from api.routes.objectives import router as objectives_router
    app.include_router(objectives_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import du routeur Self-Improvement Loop ────────────────────
try:
    from api.routes.self_improvement import router as self_improvement_router
    app.include_router(self_improvement_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

try:
    from api.routes.dashboard import router as dashboard_router
    app.include_router(dashboard_router)
except ImportError as _e:
    log.warning("dashboard_router_unavailable", err=str(_e))

try:
    from api.routes.approval import router as approval_router
    app.include_router(approval_router)
except ImportError as _e:
    log.warning("approval_router_unavailable", err=str(_e))

# ── Import Convergence Router (v3 orchestration bridge) ────────
try:
    from api.routes.convergence import router as convergence_router
    app.include_router(convergence_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Import Performance Intelligence Router (v3) ───────────────
try:
    from api.routes.performance import router as performance_router
    if performance_router:
        app.include_router(performance_router)
except Exception as _e:
    log.warning("router_import_failed", err=str(_e)[:120])

# ── Cockpit Router REMOVED — cockpit.html deleted ────────────

# ── Import Observability Router (V3) ──────────────────────────
try:
    from api.routes.observability import router as observability_router
    if observability_router:
        app.include_router(observability_router)
except Exception as _e:
    log.warning("observability_router_unavailable", err=str(_e))

# ── Import Mobile Metrics Router ─────────────────────────────
try:
    from api.routes.metrics_mobile import router as metrics_mobile_router
    if metrics_mobile_router:
        app.include_router(metrics_mobile_router)
except Exception as _e:
    log.warning("metrics_mobile_router_unavailable", err=str(_e))

try:
    from api.routes.extensions import router as extensions_router
    app.include_router(extensions_router)
except Exception as _e:
    log.warning("extensions_router_unavailable", err=str(_e))

try:
    from api.routes.token_management import router as token_mgmt_router
    if token_mgmt_router:
        app.include_router(token_mgmt_router)
except Exception:
    pass

# ── Skills & trace routers ──
try:
    from api.routes.skills import router as skills_router
    app.include_router(skills_router)
except Exception as _e:
    log.warning("skills_router_unavailable", err=str(_e))

try:
    from api.routes.trace import router as trace_router
    app.include_router(trace_router)
except Exception as _e:
    log.warning("trace_router_unavailable", err=str(_e))

# ── V3 feature routes (finance, missions, vault, identity, modules_v3) ──
try:
    from api.routes.system import router as system_router
    app.include_router(system_router)
except Exception as _e:
    log.warning("system_router_unavailable", err=str(_e))

try:
    from api.routes.finance import router as finance_router
    app.include_router(finance_router)
except Exception as _e:
    log.warning("finance_router_unavailable", err=str(_e))

try:
    from api.routes.missions import router as missions_v3_router
    app.include_router(missions_v3_router)
except Exception as _e:
    log.warning("missions_v3_router_unavailable", err=str(_e))

try:
    from api.routes.vault import router as vault_router
    app.include_router(vault_router)
except Exception as _e:
    log.warning("vault_router_unavailable", err=str(_e))

try:
    from api.routes.identity import router as identity_router
    app.include_router(identity_router)
except Exception as _e:
    log.warning("identity_router_unavailable", err=str(_e))

# NOTE: connectors_router must be mounted BEFORE modules_v3_router.
# modules_v3 defines GET /api/v3/connectors (bare prefix="/api/v3"),
# which shadows connectors.py's prefix="/api/v3/connectors" if mounted first.
# Mounting connectors_router first ensures the real connector registry is served.
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

try:
    from api.routes.cognitive import router as cognitive_router
    app.include_router(cognitive_router)
except Exception as _e:
    log.warning("cognitive_router_unavailable", err=str(_e))

try:
    from api.routes.action_console import router as console_router
    app.include_router(console_router)
except Exception as _e:
    log.warning("console_router_unavailable", err=str(_e))

try:
    from api.routes.mcp_management import router as mcp_mgmt_router
    app.include_router(mcp_mgmt_router)
except Exception as _e:
    log.warning("mcp_mgmt_router_unavailable", err=str(_e))

try:
    from api.routes.self_model import router as self_model_router
    app.include_router(self_model_router)
except Exception as _e:
    log.warning("self_model_router_unavailable", err=str(_e))

try:
    from api.routes.capability_routing import router as capability_routing_router
    app.include_router(capability_routing_router)
except Exception as _e:
    log.warning("capability_routing_router_unavailable", err=str(_e))

try:
    from api.routes.cognitive_events import router as cognitive_events_router
    app.include_router(cognitive_events_router)
except Exception as _e:
    log.warning("cognitive_events_router_unavailable", err=str(_e))

try:
    from api.routes.mission_persistence import router as mission_persistence_router
    app.include_router(mission_persistence_router)
except Exception as _e:
    log.warning("mission_persistence_router_unavailable", err=str(_e))

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
    from api.routes.domain_skills import router as domain_skills_router
    app.include_router(domain_skills_router)
except Exception as _e:
    log.warning("domain_skills_router_unavailable", err=str(_e))

try:
    from api.routes.operational_tools import router as operational_tools_router
    app.include_router(operational_tools_router)
except Exception as _e:
    log.warning("operational_tools_router_unavailable", err=str(_e))

try:
    from api.routes.system_readiness import router as system_readiness_router
    app.include_router(system_readiness_router)
except Exception as _e:
    log.warning("system_readiness_router_unavailable", err=str(_e))

try:
    from api.routes.plan_runner import router as plan_runner_router
    app.include_router(plan_runner_router)
except Exception as _e:
    log.warning("plan_runner_router_unavailable", err=str(_e))

try:
    from api.routes.playbooks import router as playbooks_router
    app.include_router(playbooks_router)
except Exception as _e:
    log.warning("playbooks_router_unavailable", err=str(_e))

try:
    from api.routes.economic import router as economic_router
    app.include_router(economic_router)
except Exception as _e:
    log.warning("economic_router_unavailable", err=str(_e))

try:
    from api.routes.models import router as models_router
    app.include_router(models_router)
except Exception as _e:
    log.warning("models_router_unavailable", err=str(_e))

try:
    from api.routes.execution import router as execution_router
    app.include_router(execution_router)
except Exception as _e:
    log.warning("execution_router_unavailable", err=str(_e))

try:
    from api.routes.venture import router as venture_router
    app.include_router(venture_router)
except Exception as _e:
    log.warning("venture_router_unavailable", err=str(_e))

try:
    from api.routes.strategy import router as strategy_router
    app.include_router(strategy_router)
except Exception as _e:
    log.warning("strategy_router_unavailable", err=str(_e))

try:
    from api.routes.kernel import router as kernel_router
    app.include_router(kernel_router)
except Exception as _e:
    log.warning("kernel_router_unavailable", err=str(_e))

try:
    from api.routes.security_audit import router as security_audit_router
    app.include_router(security_audit_router)
except Exception as _e:
    log.warning("security_audit_router_unavailable", err=str(_e))

try:
    from api.routes.debug import router as debug_router
    app.include_router(debug_router)
except Exception as _e:
    log.warning("debug_router_unavailable", err=str(_e))

# ── Previously unregistered routes — now mounted (2026-03-30) ─────────────────
# system_v2: /api/system/mode/uncensored, /api/v2/decision-memory/*, /health, etc.
try:
    from api.routes.system_v2 import router as system_v2_router
    app.include_router(system_v2_router)
except Exception as _e:
    log.warning("system_v2_router_unavailable", err=str(_e))

# self_improvement_v2: /api/v2/self-improvement/failures, /proposals, /validate, etc.
try:
    from api.routes.self_improvement_v2 import router as self_improvement_v2_router
    app.include_router(self_improvement_v2_router)
except Exception as _e:
    log.warning("self_improvement_v2_router_unavailable", err=str(_e))

# modules: /modules/agents, /modules/skills, /modules/mcp, /modules/connectors
# (distinct from modules_v3 which uses /api/v3/* prefix)
try:
    from api.routes.modules import router as modules_router
    app.include_router(modules_router)
except Exception as _e:
    log.warning("modules_router_unavailable", err=str(_e))

# NOTE: GET /health is handled by system_v2_router (mounted at line ~475, include_in_schema=False).
# The Docker healthcheck uses that route. No duplicate needed here.

# ── Session info endpoint (used by mobile app for role detection) ──
@app.get("/api/v2/session", include_in_schema=False)
async def session_info(request: Request):
    """Returns current user session info: role, username.

    No admin fallback — returns the real role from the token.
    If the token cannot be verified, returns 401.
    """
    from api.auth import verify_token
    token_str = request.headers.get("authorization", "")
    user = verify_token(token_str)
    if user:
        return {
            "ok": True,
            "role": user.get("role", "user"),
            "username": user.get("username", "unknown"),
            "auth_type": user.get("auth_type", "unknown"),
        }
    return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)


# ── Root: serve the login page ─────────────────────────────────
@app.get("/", include_in_schema=False)
async def root_redirect():
    # Entry point → login page (redirects to /app.html after auth)
    return RedirectResponse(url="/app.html")


# ── Startup : workspace cleanup ────────────────────────────────
@app.on_event("startup")
async def _on_startup():
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
        _seen = set()
        for route in app.routes:
            if isinstance(route, APIRoute):
                prefix = route.path.rsplit("/", 1)[0] if "/" in route.path else ""
                tags = list(route.tags) if route.tags else []
                name = tags[0] if tags else prefix.strip("/").replace("/", "_") or "root"
                if name not in _seen:
                    r = APIRouter()
                    r.routes = [rt for rt in app.routes if isinstance(rt, APIRoute) and (list(rt.tags) or [""])[0] == (tags[0] if tags else "")]
                    _auto_reg(name, r, prefix=prefix, tags=tags)
                    _seen.add(name)
        log.info("router_registry_auto_populated", count=len(_seen))
    except Exception as exc:
        log.warning("router_registry_auto_failed", err=str(exc)[:80])


@app.on_event("shutdown")
async def _on_shutdown():
    # Save kernel performance data to survive restarts
    try:
        from kernel.runtime.boot import save_performance
        saved = save_performance()
        log.info("kernel_performance_saved_on_shutdown", success=saved)
    except Exception as exc:
        log.warning("kernel_performance_save_failed", err=str(exc)[:80])


_start_time = time.time()


# ── Auth optionnel ────────────────────────────────────────────

_API_TOKEN = os.getenv("JARVIS_API_TOKEN", "")
_start_time = get_start_time()
# NOTE: _check_auth is imported from api._deps (supports JWT + static token)
# Do NOT redefine it here — the import above is canonical.


# ── Modèles Pydantic ──────────────────────────────────────────

class TaskRequest(BaseModel):
    input:    str               = Field(..., min_length=1, max_length=10000)
    mode:     str               = "auto"
    priority: int               = Field(default=2, ge=1, le=4)

class ModeRequest(BaseModel):
    mode:       str
    changed_by: str = "api"

class TriggerRequest(BaseModel):
    mission: str
    context: dict[str, Any] = Field(default_factory=dict)

class AbortRequest(BaseModel):
    reason: str = "Annulé par l'utilisateur"

class MissionSubmitRequest(BaseModel):
    goal:  str = Field(..., min_length=1, max_length=10000)
    mode:  str = "AUTO"


# ── Anti-duplicate mission guard ─────────────────────────────
# Set of currently-executing mission IDs. Prevents duplicate background tasks
# when the same mission_id is submitted concurrently.
_running_missions: set = set()


async def _run_mission(mission_id: str, goal: str, mode: str = "auto") -> None:
    """Execute a single mission via MetaOrchestrator. Anti-duplicate guard enforced."""
    _running_missions.add(mission_id)
    try:
        orch = _get_orchestrator()
        await orch.run(mission_id=mission_id, goal=goal, mode=mode)
    except Exception as _rm_err:
        log.warning("run_mission_failed", mission_id=mission_id, err=str(_rm_err)[:80])
    finally:
        _running_missions.discard(mission_id)


# ── Lazy component getters ────────────────────────────────────

def _get_orchestrator():
    """Get the mission orchestrator.

    MetaOrchestrator is the CANONICAL entry point.
    It delegates to JarvisOrchestrator/OrchestratorV2 internally.
    Direct instantiation of legacy orchestrators is prohibited.
    See: core/architecture_ownership.py — DEPRECATED_MODULES
    """
    from core.meta_orchestrator import get_meta_orchestrator
    return get_meta_orchestrator()

def _get_mission_system():
    from core.mission_system import get_mission_system
    return get_mission_system()

def _get_task_queue():
    from executor.task_queue import get_task_queue
    return get_task_queue()

def _get_metrics():
    try:
        from config.settings import get_settings
        from monitoring.metrics import MetricsCollector
        return MetricsCollector(get_settings())
    except Exception:
        return None

def _get_monitoring_agent():
    try:
        from config.settings import get_settings
        from agents.monitoring_agent import MonitoringAgent
        return MonitoringAgent(get_settings())
    except Exception:
        from agents.monitoring_agent import MonitoringAgent
        return MonitoringAgent()






# ── Multimodal endpoints ──────────────────────────────────────
# Removed: 3 inline stubs that returned "not implemented".
# Real multimodal is served by api/routes/multimodal.py (v2):
#   POST /api/v2/multimodal/image/generate
#   POST /api/v2/multimodal/image/describe
#   POST /api/v2/multimodal/voice/stt
#   POST /api/v2/multimodal/voice/tts
#   GET  /api/v2/multimodal/capabilities
# Provider implementations in modules/multimodal/ (image, voice, video).


# ── Auth endpoints ────────────────────────────────────────────

@app.post("/auth/token", tags=["auth"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    from api.auth import _check_auth_password
    token = _check_auth_password(form_data.username, form_data.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": token, "token_type": "bearer"}

@app.post("/auth/login", tags=["auth"])
# Returns: token, role, expires_in, authenticated, permissions
async def login_alias(form_data: OAuth2PasswordRequestForm = Depends()):
    return await login_for_access_token(form_data)

@app.get("/auth/me", tags=["auth"])
# Returns: authenticated, role, permissions, expires_in
# ROLE_PERMISSIONS mapping: admin=all, user=read/write, viewer=read
async def auth_me(request: Request):
    try:
        from api._deps import require_auth as _ra
        user = await _ra(request)
        return {"ok": True, "user": user}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/auth/refresh", tags=["auth"])
async def refresh_token(request: Request):
    """Refresh a JWT token. Accepts Authorization: Bearer <token> header.
    Returns a new token if the current one is valid; 401 otherwise.
    Used by the Flutter mobile app for silent session renewal.
    """
    from api._deps import _check_auth
    from api.token_utils import strip_bearer
    from api.auth import create_access_token, verify_token
    auth_header = request.headers.get("Authorization", "")
    token_str = strip_bearer(auth_header) or request.headers.get("X-Jarvis-Token", "")
    if not token_str:
        raise HTTPException(status_code=401, detail="No token provided")
    user = verify_token(token_str)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    new_token = create_access_token({"sub": user.get("username", ""), "role": user.get("role", "user")})
    return {"access_token": new_token, "token_type": "bearer"}


# ── WebSocket stream alias ────────────────────────────────────

@app.websocket("/ws/stream")
async def ws_stream_alias(websocket: WebSocket):
    try:
        from api.ws import ws_handler
        await ws_handler(websocket)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Router Registry Status ────────────────────────────────────

@app.get("/api/v3/system/registry", tags=["system"])
async def router_registry_status():
    """Show status of all registered API routers."""
    try:
        from api.router_registry import get_registry_status
        return get_registry_status()
    except Exception as e:
        return {"error": str(e)}


# _ORPHAN_REMOVED — dead code cleaned up in refactor cycle
# si_v2_router — self-improvement v2 endpoints mounted via si_v2_router
# cockpit_router — cockpit monitoring endpoints (integrated into main)

# NOTE: POST /api/v2/task is handled by missions_v3_router (missions.py, mounted at line ~311).
# POST /api/v2/tasks/{id}/approve and /reject are also in missions.py.
# Stubs removed — they returned fake data (pass + static dict) and were never reached.


# ── Static files (dashboard) — DOIT ÊTRE EN DERNIER ───────────
# NOTE: starlette≥1.0 StaticFiles has `assert scope["type"] == "http"` which
# crashes (AssertionError) when a WebSocket request hits an unmatched path.
# _WsSafeStaticFiles silently closes unknown WebSocket connections instead.
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    class _WsSafeStaticFiles(StaticFiles):
        async def __call__(self, scope, receive, send):
            if scope.get("type") != "http":
                # WebSocket to an unknown path — close gracefully, no crash
                await send({"type": "websocket.close", "code": 4004})
                return
            await super().__call__(scope, receive, send)

    app.mount("/", _WsSafeStaticFiles(directory=str(_static_dir)), name="static")
