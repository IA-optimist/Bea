"""
BEA MAX — Canonical API (FastAPI)
This is the ONE backend API. Loaded by main.py (the canonical entrypoint).

Structure (refactor M1 — api/main.py is now a pure orchestration file):
  - App instantiation, CORS, middlewares, rate limiting
  - Router mounting (~35 routers from api/routes/)
  - Startup/shutdown logic lives in api/lifespan.py
  - Miscellaneous inline endpoints in api/routes/misc_endpoints.py

Legacy v1 routes (/api/mission, /api/health, etc.) are included as aliases.
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

# ── Feature flags ─────────────────────────────────────────────
# ENABLE_STUB_ROUTES=true to mount stub/unimplemented route handlers
# (finance, venture, playbooks, browser, voice). Default: false.
# When false, these endpoints return 404 instead of fake 200 with empty data.
_ENABLE_STUB_ROUTES = os.getenv("ENABLE_STUB_ROUTES", "false").lower() == "true"
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Request, WebSocket
from api._deps import require_auth, get_start_time
from api.rate_limit_middleware import limiter, custom_rate_limit_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from api.security_headers import SecurityHeadersMiddleware
# Mo3: strip_bearer + OAuth2PasswordRequestForm moved to api/routes/auth.py.
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── Lifespan (startup / shutdown) — extracted to api/lifespan.py ──────────────
from api.lifespan import lifespan

log = structlog.get_logger()


# ── App ───────────────────────────────────────────────────────

# Disable public /docs and /redoc in production (expose only when ENABLE_API_DOCS=1)
ENABLE_API_DOCS = os.environ.get("ENABLE_API_DOCS", os.environ.get("BEA_DOCS", "0"))
_enable_docs = ENABLE_API_DOCS == "1"

app = FastAPI(
    title="BeaMax API",
    description="Plateforme multi-agents autonome BeaMax — API v2",
    version="2.0.0",
    docs_url="/docs" if _enable_docs else None,
    redoc_url="/redoc" if _enable_docs else None,
    # Disable default /openapi.json — we override with auth-protected version below
    openapi_url=None,
    lifespan=lifespan,
)

# Auth-protected OpenAPI schema endpoint (when docs enabled)
if _enable_docs:
    @app.get("/openapi.json", include_in_schema=False)
    async def get_openapi_schema(user: dict = Depends(require_auth)):
        """OpenAPI schema endpoint — requires authentication.

        Protects API documentation from unauthorized access.
        /docs and /redoc will fetch this endpoint automatically.
        """
        from fastapi.openapi.utils import get_openapi
        return get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

# Rate limiting (Phase 4 Security)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

# CORS: restrict to known origins (override via CORS_ORIGINS env var).
# Mounted after auth/security middlewares so it executes first and can answer
# preflight requests before auth/rate checks.
#
# Audit Sprint 2 §4.1 P2 : in production, CORS_ORIGINS MUST be set explicitly.
# Falling through to the localhost defaults in prod is a config smell that
# would silently allow misconfigured browser clients to be reachable.
_cors_origins = os.environ.get("CORS_ORIGINS", "").strip()
_is_production = os.environ.get("BEA_PRODUCTION", "").lower() in ("1", "true", "yes")
if _is_production and not _cors_origins:
    raise RuntimeError(
        "PRODUCTION STARTUP BLOCKED — CORS_ORIGINS is not set. "
        "Set CORS_ORIGINS to a comma-separated allowlist of trusted origins "
        "(e.g. CORS_ORIGINS=https://app.example.com,https://admin.example.com) "
        "or unset BEA_PRODUCTION to run in dev mode."
    )
_allowed_origins = (
    [o.strip() for o in _cors_origins.split(",") if o.strip()]
    if _cors_origins
    else [
        "http://localhost:8000",       # local dev
        "http://localhost:3000",       # local frontend
        "http://localhost:3001",       # beamax-frontend docker
        "http://10.0.2.2:8000",       # Android emulator
        "http://127.0.0.1:8000",      # loopback
    ]
)

# ── Global access enforcement middleware (fail-closed) ────────
# CRITICAL: This middleware enforces auth on every request.
# It MUST NOT be commented out — without it, per-route auth is the only
# line of defense and any route without Depends(require_auth) becomes public.
try:
    from api.middleware import AccessEnforcementMiddleware, V1DeprecationMiddleware
    app.add_middleware(AccessEnforcementMiddleware)
    # Tags every /api/v1/* response with RFC 8594 Deprecation + Sunset headers
    # and emits a structlog warning. Sunset target : 2026-10-01.
    app.add_middleware(V1DeprecationMiddleware)
    # DeprecationMiddleware (api/deprecation_middleware.py) handles fine-grained
    # route-level deprecation notices (X-Deprecated / Warning headers) for specific
    # deprecated paths. Different from V1DeprecationMiddleware (which covers all
    # /api/v1/* wholesale). Both coexist without overlap.
    try:
        from api.deprecation_middleware import DeprecationMiddleware
        app.add_middleware(DeprecationMiddleware)
    except ImportError as _dm_err:
        log.warning("deprecation_middleware_unavailable", err=str(_dm_err))
except ImportError as _enf_err:
    log.error("access_enforcement_MISSING", err=str(_enf_err),
              note="Security middleware unavailable — API will rely on per-route auth only")
    # Fail-hard in production: a missing security middleware is a block-startup
    # condition. In dev we fall through to per-route auth only (logged error).
    if os.environ.get("BEA_PRODUCTION", "").lower() in ("1", "true", "yes"):
        raise RuntimeError(
            "PRODUCTION STARTUP BLOCKED — AccessEnforcementMiddleware failed "
            f"to import: {_enf_err}. Fix the import or unset BEA_PRODUCTION "
            "to run in dev mode with per-route auth only."
        ) from _enf_err

# SlowAPI is the single mounted rate limiter. Keep it inside CORS so browser
# preflights are answered before rate checks.
app.add_middleware(SlowAPIMiddleware)

# Security headers must wrap auth/rate-limit responses.
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Bea-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# ── Training-data collector hook (opt-in via BEA_TRAINING_COLLECT=1) ──
# Wraps LLMFactory.safe_invoke so every successful LLM call is captured
# in data/training/raw/*.jsonl. No-op if the env var is unset.
try:
    from core.llm_wrapper import patch_llm_factory
    patch_llm_factory()
except Exception as _tc_err:
    log.debug("training_collector_hook_skipped", err=str(_tc_err)[:120])

# ── Router mounting — see api/router_mount.py ─────────────────
from api.router_mount import mount_all_routers

mount_all_routers(app, _ENABLE_STUB_ROUTES)


# ── Session info endpoint (used by mobile app for role detection) ──
@app.get("/api/v2/session", include_in_schema=False)
async def session_info(request: Request, user: dict = Depends(require_auth)):
    """Returns current user session info: role, username.

    Auth enforced via Depends(require_auth) — no silent admin fallback.
    Returns 401 if the token cannot be verified.
    """
    if isinstance(user, dict):
        return {
            "ok": True,
            "role": user.get("role", "user"),
            "username": user.get("username") or user.get("sub", ""),
            "auth_type": user.get("auth_type", "unknown"),
        }
    return {
        "ok": True,
        "role": getattr(user, "role", "user"),
        "username": getattr(user, "username", "") or getattr(user, "sub", ""),
    }


# ── Root: serve the login page ─────────────────────────────────
@app.get("/", include_in_schema=False)
async def root_redirect():
    # Entry point → login page (redirects to /app.html after auth)
    return RedirectResponse(url="/app.html")


# ── Auth cookie compatibility aliases ─────────────────────────
# Auth router is mounted inside mount_all_routers. These aliases let
# internal code that imported from api.main continue to work.
from api.routes import auth as _auth_routes

_COOKIE_NAME = _auth_routes.COOKIE_NAME
_COOKIE_MAX_AGE = _auth_routes.COOKIE_MAX_AGE
_COOKIE_SECURE = _auth_routes.COOKIE_SECURE
_set_auth_cookie = _auth_routes.set_auth_cookie


# ── WebSocket stream alias ────────────────────────────────────

@app.websocket("/ws/stream")
async def ws_stream_alias(websocket: WebSocket):
    try:
        from api.ws import ws_handler
        await ws_handler(websocket)
    except Exception:
        try:
            await websocket.close()
        except Exception as _exc:
            log.warning("swallowed_exception", action="main_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


# ── Auth optionnel ────────────────────────────────────────────

_API_TOKEN = os.getenv("BEA_API_TOKEN", "")
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
    It delegates to BeaOrchestrator/OrchestratorV2 internally.
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
        from core.observability.metrics import MetricsCollector
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


# _ORPHAN_REMOVED — dead code cleaned up in refactor cycle
# si_v2_router — self-improvement v2 endpoints mounted via si_v2_router
# cockpit_router — cockpit monitoring endpoints (integrated into main)

# NOTE: POST /api/v2/task is handled by missions_v3_router (missions.py).
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
