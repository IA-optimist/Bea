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

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from api._deps import require_auth
from api.token_utils import strip_bearer


# ── HttpOnly cookie config (XSS-safe token storage, CVSS 9.1 mitigation) ──
# Secure flag activé uniquement hors dev pour permettre le test en HTTP local.
COOKIE_NAME = "jarvis_token"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days
COOKIE_SECURE = os.environ.get("JARVIS_COOKIE_SECURE", "1") != "0"


def set_auth_cookie(response: Response, token: str) -> None:
    """Set HttpOnly token cookie (XSS-safe). Additive — token reste aussi en body."""
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


# ── JSON login / logout (frontend React dashboard) ────────────────

@router.post("/api/v2/auth/login")
async def json_login(request: Request, response: Response):
    """
    JSON-compatible login endpoint for the React dashboard.

    Accepts: ``{"email": "...", "password": "..."}`` or
             ``{"username": "...", "password": "..."}``.
    Returns: ``{"ok": true, "data": {"token": "...", "user": {...}}}``.

    Sets the HttpOnly cookie ``jarvis_token`` — prioritized over headers
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


@router.post("/api/v2/auth/logout")
async def json_logout(response: Response):
    """Clear the HttpOnly cookie. Header-borne Bearer/X-Jarvis-Token tokens
    are the client's responsibility to drop."""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "data": {"message": "logged_out"}}


# ── OAuth2 form login + legacy aliases ────────────────────────────

@router.post("/auth/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    response: Response = None,
):
    from api.auth import _check_auth_password
    token = _check_auth_password(form_data.username, form_data.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if response is not None:
        set_auth_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/login")
async def login_alias(
    form_data: OAuth2PasswordRequestForm = Depends(),
    response: Response = None,
):
    """Returns: token, role, expires_in, authenticated, permissions."""
    return await login_for_access_token(form_data, response)


@router.get("/auth/me")
async def auth_me(user: dict = Depends(require_auth)):
    """Return the authenticated user's identity (from cookie or header).

    The HttpOnly cookie ``jarvis_token`` is read first by ``require_auth``,
    with Bearer / X-Jarvis-Token fallback for legacy clients.

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


@router.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    """Refresh a JWT token.

    Accepts (in descending priority): HttpOnly ``jarvis_token`` cookie,
    ``Authorization: Bearer <token>`` header, or ``X-Jarvis-Token`` header.
    Returns a new token and refreshes the HttpOnly cookie.
    Returns 401 if the current token is invalid or expired.
    """
    from api.auth import create_access_token, verify_token

    token_str = (
        request.cookies.get(COOKIE_NAME)
        or strip_bearer(request.headers.get("Authorization", ""))
        or request.headers.get("X-Jarvis-Token", "")
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
    return {"access_token": new_token, "token_type": "bearer"}
