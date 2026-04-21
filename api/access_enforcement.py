"""
JARVIS MAX — Access Enforcement Middleware
============================================
Server-side token gating enforced on ALL protected endpoints.

Behavior:
  - No token → 401 "Authentication required"
  - Invalid token → 401 "Invalid access token"
  - Expired token → 403 "Your access has expired"
  - Revoked/disabled → 403 "Your access has been revoked"
  - Daily limit reached → 429 "Daily mission limit reached"
  - Admin token → full access, bypasses all limits

Messages are user-friendly (no raw error codes).
"""
from __future__ import annotations

from api.auth import verify_token, has_permission
from api.access_tokens import get_token_manager, AccessToken


class AccessResult:
    """Result of an access check."""
    __slots__ = ("allowed", "user", "token", "error_code", "error_message")

    def __init__(self, allowed: bool = False, user: dict | None = None,
                 token: AccessToken | None = None,
                 error_code: int = 401, error_message: str = ""):
        self.allowed = allowed
        self.user = user
        self.token = token
        self.error_code = error_code
        self.error_message = error_message

    def to_error_response(self) -> dict:
        return {
            "error": self.error_message,
            "code": self.error_code,
            "support": "Please contact support or renew your access.",
        }


# ── Public / unprotected paths ──
_PUBLIC_PATHS = {
    "/health",
    "/api/health",  # TEMPORARY: Allow dev access
    "/api/v2/health",
    "/api/v3/system/readiness",   # Required: Docker healthcheck + verify_boot.sh call this without auth
    "/",
    "/app.html",
    "/auth/login",
    "/auth/token",
    "/docs",
    "/openapi.json",
    "/redoc",
}

_silent_log = __import__("structlog").get_logger(__name__)

# Paths that match by prefix (static files)
_PUBLIC_PREFIXES = (
    "/static/",
    "/docs/",
    "/.well-known/",  # ACME TLS challenges (Caddy/certbot)
)


def is_public_path(path: str) -> bool:
    """Check if a path is publicly accessible without auth."""
    if path in _PUBLIC_PATHS:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    # Allow static asset extensions (CSS/JS/images/fonts only — NOT .html)
    # HTML pages must be explicitly listed in _PUBLIC_PATHS to prevent exposure
    if path.endswith((".css", ".js", ".png", ".ico", ".svg", ".woff2")):
        return True
    return False


def check_access(raw_token: str | None, path: str = "",
                 permission: str = "read") -> AccessResult:
    """
    Server-side access check.

    Args:
        raw_token: the Bearer token or X-Jarvis-Token header value
        path: the request path (for public path bypass)
        permission: required permission level

    Returns:
        AccessResult with allowed=True/False and user-friendly error.
    """
    # Public paths are always accessible
    if path and is_public_path(path):
        return AccessResult(allowed=True, user={"username": "public", "role": "public"})

    # No token → blocked
    if not raw_token:
        return AccessResult(
            allowed=False,
            error_code=401,
            error_message="Authentication required. Please enter your access token.",
        )

    # Strip "Bearer " prefix (centralized)
    from api.token_utils import strip_bearer
    token_str = strip_bearer(raw_token) or ""

    # Try verify
    user = verify_token(token_str)

    if not user:
        # Determine specific error
        if token_str.startswith("jv-"):
            # It's an access token format — check specific reason
            manager = get_token_manager()
            from api.access_tokens import _hash_token
            token_hash = _hash_token(token_str)
            token_id = manager._hash_index.get(token_hash)
            if token_id:
                token_obj = manager._tokens.get(token_id)
                if token_obj:
                    if not token_obj.enabled:
                        return AccessResult(
                            allowed=False,
                            error_code=403,
                            error_message="Your access has been revoked. Please contact support.",
                        )
                    if token_obj.expired:
                        if token_obj.expires_at > 0:
                            return AccessResult(
                                allowed=False,
                                error_code=403,
                                error_message="Your access has expired. Please renew your subscription.",
                            )
                        return AccessResult(
                            allowed=False,
                            error_code=403,
                            error_message="Your access limit has been reached. Please upgrade your plan.",
                        )
        return AccessResult(
            allowed=False,
            error_code=401,
            error_message="Your access token is invalid. Please check and try again.",
        )

    # Check permission
    role = user.get("role", "viewer")
    if not has_permission(role, permission):
        return AccessResult(
            allowed=False,
            user=user,
            error_code=403,
            error_message="You don't have permission for this action.",
        )

    # For access tokens: get the token object for plan limits
    token_obj = None
    if user.get("auth_type") == "access_token":
        token_id = user.get("token_id")
        if token_id:
            manager = get_token_manager()
            token_obj = manager.get_token_by_id(token_id)

    return AccessResult(allowed=True, user=user, token=token_obj)


def check_mission_access(raw_token: str | None) -> AccessResult:
    """
    Check if a user can submit a new mission.
    Enforces daily limits and plan restrictions.
    Admin bypasses all limits.
    """
    result = check_access(raw_token, permission="write")
    if not result.allowed:
        return result

    # Admin bypasses all limits
    if result.user and result.user.get("role") == "admin":
        return result

    # Check daily mission limit for access tokens
    if result.token:
        if not result.token.check_daily_limit():
            limits = result.token.plan_limits
            return AccessResult(
                allowed=False,
                user=result.user,
                token=result.token,
                error_code=429,
                error_message=f"Daily mission limit reached ({limits.missions_per_day}/day). "
                              "Please try again tomorrow or upgrade your plan.",
            )

    return result


def record_mission_usage(token: AccessToken | None) -> None:
    """Record a mission usage against a token's daily limit."""
    if token:
        token.record_mission()
        # Persist
        try:
            manager = get_token_manager()
            manager._save()
        except Exception:
            _silent_log.debug("suppressed_exception", src='access_enforcement.py')


def get_user_friendly_error(status_code: int, detail: str = "") -> str:
    """Convert HTTP error codes to user-friendly messages."""
    messages = {
        401: "Authentication required. Please enter your access token.",
        403: "You don't have permission for this action.",
        429: "Usage limit reached. Please try again later or upgrade your plan.",
    }
    return detail or messages.get(status_code, "Something went wrong. Please try again.")
