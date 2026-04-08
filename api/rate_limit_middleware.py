"""
JARVIS MAX — Rate Limiting Middleware (Phase 4 Security)
==========================================================
Protects API endpoints from DDoS and brute force attacks.

Limits:
- General API: 100 requests/minute per IP
- Business endpoints: 20 requests/minute per IP
- Auth endpoints: 5 requests/minute per IP
"""
from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
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


# Initialize limiter
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["100/minute"],  # Global default
    storage_uri="memory://",  # Use Redis in production: redis://redis:6379
)


def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    User-friendly rate limit error response.
    """
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down and try again in a minute.",
            "retry_after": exc.detail.split("Retry after ")[1] if "Retry after" in exc.detail else "60 seconds",
            "support": "If you need higher limits, please contact support or upgrade your plan.",
        },
    )


def get_limiter():
    """Get limiter instance for FastAPI dependency injection."""
    return limiter


def get_rate_limit_handler():
    """Get custom rate limit error handler."""
    return custom_rate_limit_handler
