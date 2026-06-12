"""
BEA MAX — Rate Limiting Middleware (Phase 4 Security)
==========================================================
Protects API endpoints from DDoS and brute force attacks.

Limits:
- General API: 100 requests/minute per IP
- Business endpoints: 20 requests/minute per IP
- Auth endpoints: 5 requests/minute per IP
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from starlette.responses import JSONResponse


def get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key based on IP + user if authenticated.
    
    Prevents authenticated users from being grouped with other IPs.
    """
    # Get IP address
    ip = get_remote_address(request)
    
    # If authenticated, use user ID instead
    if hasattr(request.state, "user") and request.state.user:
        user_id = request.state.user.get("username", "")
        if user_id:
            return f"user:{user_id}"
    
    return f"ip:{ip}"


# Initialize limiter with Redis backend (distributed across API replicas).
# Falls back to in-memory storage in dev when the `redis` Python package is
# not installed or REDIS_URL is unset. Production MUST set REDIS_URL and
# install redis>=3.0 for distributed rate limiting across workers.
import os
import logging as _logging

_rl_log = _logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "").strip()
_STORAGE_URI = "memory://"

if REDIS_URL:
    try:
        import redis as _redis_pkg  # noqa: F401 — probe availability
        _STORAGE_URI = REDIS_URL
    except ImportError:
        _rl_log.warning(
            "rate_limit.redis_package_missing — falling back to memory:// "
            "(non-distributed). Install redis>=3.0 and set REDIS_URL to use "
            "distributed rate limiting."
        )
else:
    _rl_log.info(
        "rate_limit.memory_storage — REDIS_URL not set, using in-memory "
        "rate limiting (single-worker only)."
    )

# Production safety: if BEA_PRODUCTION is set, refuse to start with
# memory:// storage (silently allows bypassing rate limits by adding workers).
if os.environ.get("BEA_PRODUCTION", "").lower() in ("1", "true", "yes") \
        and _STORAGE_URI == "memory://":
    raise RuntimeError(
        "PRODUCTION STARTUP BLOCKED — rate limiter falling back to memory:// "
        "storage. Set REDIS_URL and install redis>=3.0, or unset "
        "BEA_PRODUCTION to run in dev mode."
    )

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["100/minute"],  # Global default
    storage_uri=_STORAGE_URI,
    # Bea loads configuration explicitly. Disable slowapi's implicit .env
    # read, which uses the Windows locale encoding and breaks on UTF-8.
    config_filename="",
)


def custom_rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    User-friendly rate limit error response.
    Handles both RateLimitExceeded and unexpected exception types gracefully.
    """
    detail_str = getattr(exc, "detail", "") or str(exc)
    retry_after = (
        detail_str.split("Retry after ")[1]
        if isinstance(detail_str, str) and "Retry after" in detail_str
        else "60 seconds"
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down and try again in a minute.",
            "retry_after": retry_after,
            "support": "If you need higher limits, please contact support or upgrade your plan.",
        },
    )


def get_limiter():
    """Get limiter instance for FastAPI dependency injection."""
    return limiter


def get_rate_limit_handler():
    """Get custom rate limit error handler."""
    return custom_rate_limit_handler
