"""
JARVIS MAX — Auth helpers (JWT + Access Token system).

Two auth paths:
1. Admin login: username=admin, password=JARVIS_ADMIN_PASSWORD → JWT
   (legacy fallback to JARVIS_SECRET_KEY in dev only)
2. Access token: jv-xxx bearer token → validated against TokenManager

Both produce authorized access. Access tokens have role-based permissions.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import jwt as _jwt
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False


def _secret() -> str:
    from config.settings import get_settings
    return get_settings().jarvis_secret_key


# ── Constant-time comparison ──

def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing side-channels."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ── Admin password resolution ──

_ADMIN_PW_WARNING_EMITTED = False


def _get_admin_password() -> str:
    """
    Get admin password. Priority:
    1. JARVIS_ADMIN_PASSWORD (preferred, always used in production)
    2. JARVIS_SECRET_KEY (legacy fallback, warns once)
    """
    global _ADMIN_PW_WARNING_EMITTED
    admin_pw = os.environ.get("JARVIS_ADMIN_PASSWORD", "")
    if admin_pw:
        return admin_pw
    # Legacy fallback
    secret = _secret()
    if not _ADMIN_PW_WARNING_EMITTED:
        logger.warning(
            "JARVIS_ADMIN_PASSWORD not set — falling back to JARVIS_SECRET_KEY. "
            "Set JARVIS_ADMIN_PASSWORD explicitly for production."
        )
        _ADMIN_PW_WARNING_EMITTED = True
    return secret


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Admin auth with constant-time comparison.
    Both valid-user/wrong-password and invalid-user paths do equivalent work.
    Returns user dict or None.
    """
    if not password:
        return None

    admin_pw = _get_admin_password()

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


def create_access_token(data: dict, expires_in: int = 3600) -> str:
    """Create a JWT access token."""
    if _JWT_AVAILABLE:
        payload = {**data, "exp": int(time.time()) + expires_in, "iat": int(time.time())}
        return _jwt.encode(payload, _secret(), algorithm="HS256")
    import hashlib, json
    payload_str = json.dumps(data, sort_keys=True)
    sig = hashlib.sha256((payload_str + _secret()).encode()).hexdigest()[:16]
    return f"token.{sig}"


def verify_token(token_str: str) -> Optional[dict]:
    """
    Verify a token string. Supports both:
    1. JWT tokens (from admin login)
    2. Access tokens (jv-xxx from TokenManager)

    Returns: {"username": ..., "role": ...} or None.
    """
    # SECURITY: Fail-closed by default — only bypass if JARVIS_DEV_MODE explicitly set
    import os
    _DEV_MODE = os.environ.get("JARVIS_DEV_MODE", "").lower() in ("1", "true", "yes")
    if _DEV_MODE:
        import structlog
        log = structlog.get_logger()
        log.warning("auth.dev_bypass_active", reason="JARVIS_DEV_MODE=true")
        return {"username": "dev", "role": "admin", "auth_type": "dev_bypass"}
    
    from api.token_utils import strip_bearer
    token_str = strip_bearer(token_str)
    if not token_str:
        return None

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
        except Exception:
            pass
        return None

    # Path 2: JWT token
    if _JWT_AVAILABLE:
        try:
            payload = _jwt.decode(token_str, _secret(), algorithms=["HS256"])
            return {
                "username": payload.get("sub", "unknown"),
                "role": payload.get("role", "user"),
                "auth_type": "jwt",
            }
        except Exception:
            pass

    # Path 3: Static API token fallback
    from config.settings import get_settings
    settings = get_settings()
    if hasattr(settings, 'jarvis_api_token') and token_str == settings.jarvis_api_token:
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


def require_permission(user: dict, permission: str) -> bool:
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
    authorization: str = Header(None)
) -> dict:
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
    # SECURITY: Fail-closed by default — only bypass if JARVIS_DEV_MODE explicitly set
    import os
    _DEV_MODE = os.environ.get("JARVIS_DEV_MODE", "").lower() in ("1", "true", "yes")
    if _DEV_MODE:
        import structlog
        log = structlog.get_logger()
        log.warning("auth.get_current_user.dev_bypass_active", reason="JARVIS_DEV_MODE=true")
        return {"username": "dev", "role": "admin", "auth_type": "dev_bypass"}
    
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
