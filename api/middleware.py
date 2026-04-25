"""
JARVIS MAX — Global Access Enforcement Middleware
===================================================
Wires access_enforcement into every HTTP request.

Extracts token from:
  1. Authorization: Bearer <token>
  2. X-Jarvis-Token header
  3. ?token= query parameter (for websocket upgrades)

Blocks unauthorized requests with user-friendly JSON errors.
Public paths bypass enforcement.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.access_enforcement import check_access, is_public_path


def _extract_token(request: Request) -> str | None:
    """Extract auth token from request (priorité descendante).

    1. cookie ``jarvis_token`` — HttpOnly, XSS-safe (nouveau frontend)
    2. ``Authorization: Bearer <token>`` — OAuth2-style
    3. ``X-Jarvis-Token`` header — legacy frontend (localStorage)
    4. ``?token=`` query param — WebSocket upgrades uniquement
    """
    # 1. HttpOnly cookie (nouveau frontend, XSS-safe)
    cookie_token = request.cookies.get("jarvis_token")
    if cookie_token:
        return cookie_token

    # 2. Authorization: Bearer <token>
    from api.token_utils import strip_bearer
    auth_header = request.headers.get("authorization", "")
    bearer_token = strip_bearer(auth_header)
    if bearer_token:
        return bearer_token

    # 3. X-Jarvis-Token header (legacy)
    jarvis_token = request.headers.get("x-jarvis-token", "")
    if jarvis_token:
        return jarvis_token

    # 4. Query parameter (for websocket upgrades)
    token_param = request.query_params.get("token", "")
    if token_param:
        return token_param

    return None


def _permission_for_method(method: str) -> str:
    """Map HTTP method to required permission."""
    if method in ("GET", "HEAD", "OPTIONS"):
        return "read"
    return "write"


class AccessEnforcementMiddleware(BaseHTTPMiddleware):
    """
    Global middleware that enforces token-gated access on all routes.

    - Public paths (/health, /index.html, static, /auth/login) → pass through
    - All other routes → require valid token
    - Returns user-friendly JSON error messages
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Public paths bypass auth
        if is_public_path(path):
            return await call_next(request)

        # OPTIONS requests for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # Extract token
        raw_token = _extract_token(request)

        # Check access
        permission = _permission_for_method(request.method)
        result = check_access(raw_token, path=path, permission=permission)

        if not result.allowed:
            return JSONResponse(
                status_code=result.error_code,
                content={
                    "detail": result.error_message,
                    "support": "Please contact support or renew your access.",
                },
            )

        # Attach user info to request state for downstream use
        request.state.user = result.user
        request.state.token = result.token

        return await call_next(request)


# ── v1 deprecation tagger ─────────────────────────────────────────────
# RFC 8594 (Deprecation + Sunset headers) compliance for all /api/v1/*
# responses. Lets clients (mobile, frontend) detect the deprecation and
# log the call site for telemetry-driven removal.

_V1_SUNSET_DATE = "2026-10-01T00:00:00Z"
_V1_DOC_LINK = '<https://github.com/UniTy01/Jarvismax-master/blob/main/docs/API_VERSIONING.md>; rel="deprecation"'


class V1DeprecationMiddleware(BaseHTTPMiddleware):
    """
    Tags every response from a /api/v1/* path with Deprecation + Sunset
    headers per RFC 8594, plus a structlog warning so prod telemetry can
    track residual v1 traffic before final removal.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_v1 = path.startswith("/api/v1/") or path == "/api/v1"

        response = await call_next(request)

        if is_v1:
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = _V1_SUNSET_DATE
            response.headers["Link"] = _V1_DOC_LINK
            # IETF RFC 7234 Warning code 299 = "Miscellaneous warning"
            response.headers["Warning"] = '299 - "Deprecated API ; migrate to v2/v3 ; sunset 2026-10-01"'
            try:
                import structlog
                structlog.get_logger(__name__).warning(
                    "api.v1.deprecated_call",
                    path=path,
                    method=request.method,
                    status=response.status_code,
                    sunset=_V1_SUNSET_DATE,
                )
            except Exception:
                pass

        return response
