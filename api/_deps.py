"""
api/_deps.py — Shared auth, getters, and utilities for all route modules.
"""
from __future__ import annotations

import hmac
import json as _json
import os
import time
from typing import Any, Optional

import structlog
from fastapi import Depends, Header, HTTPException, Request

log = structlog.get_logger()

_API_TOKEN = os.getenv("JARVIS_API_TOKEN", "")
_start_time = time.time()


def require_auth(
    request: Request,
    x_jarvis_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> dict:
    """Canonical auth dependency for FastAPI handlers.

    Reads token from X-Jarvis-Token or Authorization: Bearer.
    Returns user dict on success, raises 401 on failure.
    Used as: Depends(require_auth)

    The AccessEnforcementMiddleware already validates auth, so this
    is defense-in-depth. If middleware already set request.state.user,
    trust it.
    """
    # Fast path: middleware already authenticated
    if hasattr(request.state, "user") and request.state.user:
        return request.state.user

    # Fallback: verify ourselves
    from api.token_utils import strip_bearer
    from api.auth import verify_token

    token = x_jarvis_token or (strip_bearer(authorization) if authorization else None)

    if not token:
        raise HTTPException(status_code=401, detail="Token invalide ou manquant.")

    # Static token match
    if _API_TOKEN and token == _API_TOKEN:
        return {"username": "api", "role": "admin", "auth_type": "static"}

    # JWT or access token
    user = verify_token(token)
    if user:
        return user

    raise HTTPException(status_code=401, detail="Token invalide ou manquant.")


def get_start_time() -> float:
    return _start_time


_REQUIRE_AUTH: bool = os.getenv("JARVIS_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")


def _check_auth(token: str | None, authorization: str | None = None) -> None:
    """Validate API token or JWT. Accepts X-Jarvis-Token or Authorization: Bearer.

    Auth enforcement matrix:
      JARVIS_API_TOKEN set   → token validation enforced (normal path)
      JARVIS_API_TOKEN unset + JARVIS_REQUIRE_AUTH=true  → 503 "Auth not configured"
      JARVIS_API_TOKEN unset + JARVIS_REQUIRE_AUTH unset → auth disabled (dev only)
    """
    if not _API_TOKEN:
        if _REQUIRE_AUTH:
            # JARVIS_REQUIRE_AUTH=true but no token configured — operator error,
            # refuse all requests rather than silently allowing unauthenticated access.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Authentication is required (JARVIS_REQUIRE_AUTH=true) "
                    "but JARVIS_API_TOKEN is not configured. "
                    "Set JARVIS_API_TOKEN in your environment."
                ),
            )
        return  # No token configured and require_auth not set — auth disabled (dev mode)

    # Extract bearer token from Authorization header (centralized)
    from api.token_utils import strip_bearer
    bearer = strip_bearer(authorization) if authorization else None

    # 1. Check static API token (X-Jarvis-Token or Bearer)
    # Use hmac.compare_digest for constant-time comparison (prevents timing attacks)
    _api_bytes = _API_TOKEN.encode()
    if token and hmac.compare_digest(token.encode(), _api_bytes):
        return
    if bearer and hmac.compare_digest(bearer.encode(), _api_bytes):
        return

    # 1.5. Check access token (jv-* tokens from TokenManager)
    if candidate and candidate.startswith('jv-'):
        try:
            from api.auth import verify_token
            token_data = verify_token(candidate)
            if token_data:
                return
        except Exception as e:
            log.warning(f"access_token_verification_failed token={candidate[:10]}... error={e}")

    # 2. Check JWT token (issued by /auth/token)
    candidate = bearer or token
    if candidate:
        if _verify_jwt(candidate):
            return

    raise HTTPException(status_code=401, detail="Unauthorized")


def _verify_jwt(token_str: str) -> bool:
    """Verify a HS256 JWT issued by /auth/token. Requires PyJWT."""
    try:
        import jwt as _jwt
        from config.settings import get_settings
        secret = get_settings().jarvis_secret_key
        _jwt.decode(token_str, secret, algorithms=["HS256"])
        return True
    except ImportError:
        log.error("_deps.pyjwt_missing — install PyJWT to enable JWT auth")
        return False
    except Exception:
        return False


def _get_orchestrator():
    """Return the canonical MetaOrchestrator singleton."""
    from core.meta_orchestrator import get_meta_orchestrator
    return get_meta_orchestrator()


def _get_kernel():
    """
    Return the JarvisKernel singleton (Pass 14).
    Use for kernel.execute() — the authoritative execution entry point.
    Fail-open: returns None if kernel is not booted.

    NOTE (Pass 26 — R8): prefer _get_kernel_adapter() for all API→kernel calls.
    Direct kernel access is kept here only for internal tooling and backward compat.
    """
    try:
        from kernel.runtime.kernel import get_kernel
        return get_kernel()
    except Exception:
        return None


def _get_kernel_adapter():
    """
    Return the KernelAdapter singleton (Pass 26 — R8).

    R8: The API is an adapter, never a decision-maker.
    KernelAdapter is the ONLY sanctioned bridge between API routes and the kernel.
    Decouples external callers from kernel.execution.contracts internals.
    Fail-open: returns None if interfaces layer unavailable.
    """
    try:
        from interfaces.kernel_adapter import get_kernel_adapter
        return get_kernel_adapter()
    except Exception:
        return None


def _get_mission_system():
    from core.mission_system import get_mission_system
    return get_mission_system()


def _get_task_queue():
    from core.task_queue import get_core_task_queue
    return get_core_task_queue()


def _get_metrics():
    try:
        from core.metrics import get_metrics
        return get_metrics()
    except Exception:
        return None


def _get_monitoring_agent():
    from config.settings import get_settings
    from agents.monitoring_agent import MonitoringAgent
    return MonitoringAgent(get_settings())


def _extract_final_output(text: str) -> str:
    """Post-process final_output: convert raw JSON to readable text if needed."""
    if not text:
        return text
    stripped = text.strip()
    if "{" in stripped and "}" in stripped:
        try:
            data = _json.loads(stripped)
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
            return str(readable)  # no truncation — full response preserved for the user
        except (_json.JSONDecodeError, Exception):
            pass
    return text


# ═════════════════════════════════════════════════════════════════════
# DATABASE SESSION DEPENDENCY
# ═════════════════════════════════════════════════════════════════════

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession

# Lazy init database engine
_db_engine = None
_SessionLocal = None


def _init_db():
    """Initialize database engine and session maker (lazy)"""
    global _db_engine, _SessionLocal
    if _db_engine is None:
        database_url = os.getenv("DATABASE_URL", "postgresql://jarvis:jarvismax2025@jarvis_postgres:5432/jarvis")
        _db_engine = create_engine(database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_db_engine, autocommit=False, autoflush=False)
    return _SessionLocal


def get_db() -> SQLAlchemySession:
    """
    FastAPI dependency for database sessions
    
    Usage:
        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            items = db.query(Item).all()
            return items
    
    Automatically closes session after request completes.
    """
    SessionLocal = _init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
