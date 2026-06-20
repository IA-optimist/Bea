"""
BEA MAX — Auth helpers (JWT + Access Token system).

Two auth paths:
1. Admin login: username=admin, password=BEA_ADMIN_PASSWORD → JWT
   (legacy fallback to BEA_SECRET_KEY in dev only)
2. Access token: jv-xxx bearer token → validated against TokenManager

Both produce authorized access. Access tokens have role-based permissions.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Any, Dict, Optional, cast

import structlog

logger = structlog.get_logger(__name__)
log = logger  # alias for M3 emitter

try:
    import jwt as _jwt
except ImportError:
    _jwt = None


def _secret() -> str:
    from config.settings import get_settings
    return cast(str, get_settings().bea_secret_key)


def _require_jwt() -> Any:
    if _jwt is None:
        logger.critical("PyJWT is required for token authentication")
        raise RuntimeError("PyJWT is required for token authentication")
    return _jwt


# ── Constant-time comparison ──

def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing side-channels."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ── Admin password resolution ──

_ADMIN_PW_MISSING_LOGGED = False


def _get_admin_password() -> str:
    """Return the configured admin password, or raise if unset.

    The legacy fallback to BEA_SECRET_KEY was removed so a missing
    BEA_ADMIN_PASSWORD no longer silently elevates the JWT signing
    key into an admin credential.
    """
    admin_pw = os.environ.get("BEA_ADMIN_PASSWORD", "")
    if not admin_pw:
        raise RuntimeError("BEA_ADMIN_PASSWORD is not set — admin login is disabled.")
    return admin_pw


def authenticate_user(username: str, password: str) -> Optional[Dict[str, str]]:
    """
    Admin auth with constant-time comparison.
    Both valid-user/wrong-password and invalid-user paths do equivalent work.
    Returns user dict or None.
    """
    global _ADMIN_PW_MISSING_LOGGED
    if not password:
        return None

    try:
        admin_pw = _get_admin_password()
    except RuntimeError:
        if not _ADMIN_PW_MISSING_LOGGED:
            logger.warning(
                "Admin login attempted but BEA_ADMIN_PASSWORD is not set — refusing."
            )
            _ADMIN_PW_MISSING_LOGGED = True
        # Still burn time on a dummy compare to avoid leaking the config state via timing
        _constant_time_compare(password, "x" * 32)
        return None

    if username == "admin":
        # Valid username path: compare against real password
        if _constant_time_compare(password, admin_pw):
            return {"username": "admin", "role": "admin"}
        return None

    # Invalid username path: still perform a comparison to prevent
    # timing leak that reveals whether the username exists
    _constant_time_compare(password, admin_pw)
    return None


def _check_auth_password(username: str, password: str) -> Optional[str]:
    """
    Check credentials and return a JWT token if valid, None otherwise.
    Used by /auth/token endpoint.
    """
    user = authenticate_user(username, password)
    if not user:
        return None
    return create_access_token({"sub": user["username"], "role": user.get("role", "user")})


def create_access_token(data: dict[str, Any], expires_in: int = 2592000) -> str:
    """Create a JWT access token."""
    jwt_module = _require_jwt()
    payload = {**data, "exp": int(time.time()) + expires_in, "iat": int(time.time())}
    return cast(str, jwt_module.encode(payload, _secret(), algorithm="HS256"))


def verify_token(token_str: str) -> Optional[dict[str, Any]]:
    """
    Verify a token string. Supports both:
    1. JWT tokens (from admin login)
    2. Access tokens (jv-xxx from TokenManager)

    Returns: {"username": ..., "role": ...} or None.
    """
    from api.token_utils import strip_bearer
    token_str = strip_bearer(token_str)
    if not token_str:
        return None

    # Fast path: static BEA_API_TOKEN match (any format — read dynamically for testability)
    import os as _os
    import hmac as _hmac
    _static = _os.environ.get('BEA_API_TOKEN', '')
    if _static and _hmac.compare_digest(token_str.encode(), _static.encode()):
        return {'username': 'api', 'role': 'admin', 'auth_type': 'static'}

    # Path 1: Access token (starts with jv-)
    if token_str.startswith("jv-"):
        try:
            from api.access_tokens import get_token_manager
            manager = get_token_manager()
            access_token = manager.validate_token(token_str)
            if access_token:
                return {
                    "username": access_token.name,
                    "role": access_token.role,
                    "token_id": access_token.id,
                    "auth_type": "access_token",
                }
        except Exception as _exc:
            log.warning("swallowed_exception", action="auth_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        # Fallback: static BEA_API_TOKEN (also starts with jv-)
        import os as _os
        import hmac as _hmac
        _static = _os.environ.get('BEA_API_TOKEN', '')
        if _static and _hmac.compare_digest(token_str.encode(), _static.encode()):
            return {'username': 'api', 'role': 'admin', 'auth_type': 'static'}
        return None

    # Path 2: JWT token
    jwt_module = _require_jwt()
    try:
        payload = jwt_module.decode(token_str, _secret(), algorithms=["HS256"])
        # Mo2 wire-up (closes the gap in docs/security/jwt-hardening-v2.md):
        # if v2 is enabled and the token carries a `jti` claim, consult the
        # revocation list. Tokens minted by the legacy path do not have a
        # `jti`, so they pass through unchanged — flipping the feature flag
        # does not invalidate any existing session.
        if payload.get("jti"):
            from api import jwt_v2
            if jwt_v2.is_v2_enabled():
                # verify_access_token re-decodes + checks Redis revocation.
                # Returns None on revoked, the claims dict otherwise.
                v2_claims = jwt_v2.verify_access_token(token_str, _secret())
                if v2_claims is None:
                    return None
        return {
            "username": payload.get("sub", "unknown"),
            "role": payload.get("role", "user"),
            "auth_type": "jwt",
        }
    except Exception as _exc:
        log.warning("swallowed_exception", action="auth_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # Path 3: Static API token fallback
    from config.settings import get_settings
    settings = get_settings()
    configured_static = getattr(settings, 'bea_api_token', '') or ''
    if configured_static and hmac.compare_digest(token_str.encode(), configured_static.encode()):
        return {"username": "api", "role": "admin", "auth_type": "static"}

    return None


# ── Permission checks ──

ROLE_PERMISSIONS = {
    "admin": {"read", "write", "approve", "manage_tokens", "admin", "diagnostics"},
    "user": {"read", "write", "approve"},
    "viewer": {"read"},
}


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(user: dict[str, Any], permission: str) -> bool:
    """Check if a user dict has a specific permission. Raises ValueError if not."""
    role = user.get("role", "viewer")
    if not has_permission(role, permission):
        return False
    return True


# ========================================
# FASTAPI DEPENDENCY FOR TOKEN AUTH
# ========================================

from fastapi import Header, HTTPException, status

async def get_current_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    FastAPI dependency to verify Authorization header.
    
    Usage:
        @router.get("/protected")
        async def protected_endpoint(user: dict = Depends(get_current_user)):
            return {"user": user["username"]}
    
    Returns:
        dict: User info {username, role, token_id, auth_type}
    
    Raises:
        HTTPException: 401 if token invalid or missing
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    # verify_token handles "Bearer xxx" or "xxx" format
    user_data = verify_token(authorization)

    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your access token is invalid. Please check and try again.",
        )

    return user_data
