"""Authentication routes.

Audit follow-up (Mo3): the 6 auth endpoints used to live inline in
`api/main.py`, which was over 1090 lines and mixed app factory + middleware
wiring + auth + chat + metrics. Extracted here so:

  - `main.py` shrinks (audit M1 large-file ratchet),
  - the auth surface is reviewable in one focused module,
  - OpenAPI tags + dependencies become explicit,
  - tests can import and exercise the router directly.

Public router : :data:`router`. Mount with ``app.include_router(router)``.

Cookie helpers (:func:`set_auth_cookie`, :data:`COOKIE_NAME`) are also
exported because the rest of the API uses them when issuing tokens
(`api/main.py` still calls them from other paths).
"""
from __future__ import annotations

import logging
import os
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from api._deps import require_auth
from api.token_utils import strip_bearer

logger = logging.getLogger(__name__)


# â”€â”€ HttpOnly cookie config (XSS-safe token storage, CVSS 9.1 mitigation) â”€â”€
# Secure flag activÃ© uniquement hors dev pour permettre le test en HTTP local.
COOKIE_NAME = "bea_token"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days
COOKIE_SECURE = os.environ.get("BEA_COOKIE_SECURE", "1") != "0"


def set_auth_cookie(response: Response, token: str) -> None:
    """Set HttpOnly token cookie (XSS-safe). Additive â€” token reste aussi en body."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


router = APIRouter(tags=["auth"])


# â”€â”€ JSON login / logout (frontend React dashboard) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/api/v2/auth/login")  # type: ignore[untyped-decorator]
async def json_login(request: Request, response: Response) -> dict[str, Any]:
    """
    JSON-compatible login endpoint for the React dashboard.

    Accepts: ``{"email": "...", "password": "..."}`` or
             ``{"username": "...", "password": "..."}``.
    Returns: ``{"ok": true, "data": {"token": "...", "user": {...}}}``.

    Sets the HttpOnly cookie ``bea_token`` â€” prioritized over headers
    server-side. Legacy frontends using the body token still work.
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    username = body.get("username") or body.get("email") or ""
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username/email and password required")
    from api.auth import _check_auth_password
    token = _check_auth_password(username, password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    set_auth_cookie(response, token)
    return {
        "ok": True,
        "data": {
            "token": token,
            "user": {"username": username, "role": "user"},
        },
    }


@router.post("/api/v2/auth/logout")  # type: ignore[untyped-decorator]
async def json_logout(request: Request, response: Response) -> dict[str, Any]:
    """Clear the HttpOnly cookie. Header-borne Bearer/X-Bea-Token tokens
    are the client's responsibility to drop.

    When ``BEA_JWT_HARDENING_V2`` is on, this also actively revokes the
    access token's ``jti`` and the refresh token (if provided) server-side,
    so the tokens are immediately unusable even before they expire.
    """
    from api import jwt_v2

    if jwt_v2.is_v2_enabled():
        # Best-effort revoke: read JWT from cookie / Authorization and
        # extract the jti without throwing if it's malformed or expired.
        from api.auth import _secret
        from api.token_utils import strip_bearer as _strip
        token_str = (
            request.cookies.get(COOKIE_NAME)
            or _strip(request.headers.get("Authorization", ""))
            or request.headers.get("X-Bea-Token", "")
        )
        if token_str:
            try:
                import jwt as _jwt
                claims = _jwt.decode(
                    token_str, _secret(), algorithms=["HS256"],
                    options={"verify_exp": False},
                )
                jti = claims.get("jti")
                exp = int(claims.get("exp", 0))
                if jti:
                    remaining = max(exp - int(__import__("time").time()), 1)
                    jwt_v2.revoke_access_jti(jti, remaining_ttl_seconds=remaining)
            except Exception as exc:
                logger.debug("jwt_v2_logout_decode_skipped: %s", exc)

        # Read body for refresh_token (best effort).
        try:
            body = await request.json()
            refresh = body.get("refresh_token", "") if isinstance(body, dict) else ""
        except Exception:
            refresh = ""
        if not refresh:
            refresh = request.headers.get("X-Refresh-Token", "") or ""
        if refresh:
            try:
                jwt_v2.revoke_refresh_token(refresh)
            except Exception as exc:
                logger.debug("jwt_v2_logout_refresh_revoke_skipped: %s", exc)

    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "data": {"message": "logged_out"}}


# â”€â”€ OAuth2 form login + legacy aliases â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _maybe_issue_v2_pair(username: str, role: str) -> dict[str, Any] | None:
    """If BEA_JWT_HARDENING_V2 is on, return a v2 (access, refresh) pair
    payload. Returns ``None`` when the flag is off so the legacy code path
    runs unchanged.

    Audit Mo2 prep: this is the only place we branch on the flag at the
    HTTP layer; the v2 module owns the cryptographic logic.
    """
    from api import jwt_v2
    if not jwt_v2.is_v2_enabled():
        return None
    from api.auth import _secret
    pair = jwt_v2.create_token_pair(sub=username, role=role, secret=_secret())
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": "bearer",  # nosec B105 â€” OAuth2 standard string
        "expires_in": pair.access_expires_in,
        "refresh_expires_in": pair.refresh_expires_in,
    }


@router.post("/auth/token")  # type: ignore[untyped-decorator]
async def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> dict[str, Any]:
    from api.auth import authenticate_user, create_access_token
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    v2 = _maybe_issue_v2_pair(user["username"], user.get("role", "user"))
    if v2 is not None:
        # v2 cookie stores the access JWT (short-lived).
        set_auth_cookie(response, v2["access_token"])
        return v2

    # Legacy path: 30-day JWT, no refresh.
    token = create_access_token({"sub": user["username"], "role": user.get("role", "user")})
    set_auth_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}  # nosec B105 — OAuth2 standard string


@router.post("/auth/login")  # type: ignore[untyped-decorator]
async def login_alias(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> dict[str, Any]:
    """Returns: token, role, expires_in, authenticated, permissions."""
    return cast(dict[str, Any], await login_for_access_token(response=response, form_data=form_data))


@router.get("/auth/me")  # type: ignore[untyped-decorator]
async def auth_me(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    """Return the authenticated user's identity (from cookie or header).

    The HttpOnly cookie ``bea_token`` is read first by ``require_auth``,
    with Bearer / X-Bea-Token fallback for legacy clients.

    Lets the frontend restore the session on page load without persisting
    sensitive info in ``localStorage``. Returns 401 if not authenticated.
    """
    return {
        "ok": True,
        "data": {
            "authenticated": True,
            "user": user,
            "role": user.get("role", "user"),
            "username": user.get("username", ""),
        },
    }


@router.post("/auth/refresh")  # type: ignore[untyped-decorator]
async def refresh_token(request: Request, response: Response) -> dict[str, Any]:
    """Refresh a JWT token.

    Two paths depending on ``BEA_JWT_HARDENING_V2``:

    * **v2 on** (audit Mo2 prep): expects a ``refresh_token`` field in the
      JSON body or as ``X-Refresh-Token`` header. Performs single-use
      rotation, detects replay, and revokes the entire family on attack.
      Returns ``{access_token, refresh_token, token_type, expires_in,
      refresh_expires_in}``.

    * **v2 off** (legacy): accepts the old long-lived access token from
      cookie / Authorization / X-Bea-Token, verifies it, issues a new
      one. Behavior unchanged from before Mo2.
    """
    from api import jwt_v2

    if jwt_v2.is_v2_enabled():
        # Prefer body field; fall back to header for non-JSON clients.
        body_refresh = ""
        try:
            body = await request.json()
            if isinstance(body, dict):
                body_refresh = body.get("refresh_token") or ""
        except Exception:
            body_refresh = ""
        refresh = body_refresh or request.headers.get("X-Refresh-Token", "") or ""
        if not refresh:
            raise HTTPException(status_code=401, detail="refresh_token missing")
        from api.auth import _secret
        try:
            pair = jwt_v2.rotate_refresh_token(refresh, _secret())
        except ValueError as exc:
            # Includes replay detection â€” the family is already revoked
            # inside rotate_refresh_token. Surface as 401 so the client
            # must re-login.
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        set_auth_cookie(response, pair.access_token)
        return {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "token_type": "bearer",  # nosec B105 â€” OAuth2 standard string
            "expires_in": pair.access_expires_in,
            "refresh_expires_in": pair.refresh_expires_in,
        }

    # Legacy path (unchanged).
    from api.auth import create_access_token, verify_token
    token_str = (
        request.cookies.get(COOKIE_NAME)
        or strip_bearer(request.headers.get("Authorization", ""))
        or request.headers.get("X-Bea-Token", "")
    )
    if not token_str:
        raise HTTPException(status_code=401, detail="No token provided")
    user = verify_token(token_str)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    new_token = create_access_token({
        "sub": user.get("username", ""),
        "role": user.get("role", "user"),
    })
    set_auth_cookie(response, new_token)
    return {"access_token": new_token, "token_type": "bearer"}  # nosec B105 â€” OAuth2 standard string
