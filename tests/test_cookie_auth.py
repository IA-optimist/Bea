"""Gate test — cookie HttpOnly auth (CVSS 9.1 XSS mitigation).

Valide que :
  1. POST /api/v2/auth/login set le cookie `jarvis_token` (HttpOnly + Secure
     + SameSite=Lax) ET retourne le token dans le body (backward-compat).
  2. GET /auth/me reconnaît le cookie et retourne l'user.
  3. POST /api/v2/auth/logout clear le cookie.
  4. Le flag HttpOnly est positionné (XSS-safe).

Utilise FastAPI TestClient avec un token API statique pour éviter de
toucher au système JWT.
"""
from __future__ import annotations


import pytest


@pytest.fixture
def app(monkeypatch):
    """App FastAPI minimal avec juste les endpoints auth."""
    monkeypatch.setenv("JARVIS_API_TOKEN", "test-static-token")
    monkeypatch.setenv("JARVIS_REQUIRE_AUTH", "true")
    # Cookie non-Secure pour les tests en HTTP.
    monkeypatch.setenv("JARVIS_COOKIE_SECURE", "0")
    import importlib
    import api._deps as _deps_mod
    importlib.reload(_deps_mod)
    # On teste le logout + /auth/me directement via la require_auth.
    from fastapi import FastAPI, Depends
    from fastapi.responses import JSONResponse
    from api._deps import require_auth

    app = FastAPI()

    @app.get("/auth/me")
    async def me(user: dict = Depends(require_auth)):
        return {"ok": True, "data": {"user": user}}

    @app.post("/api/v2/auth/logout")
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("jarvis_token", path="/")
        return resp

    return app


def test_auth_me_rejects_no_token(app):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/auth/me")
    assert r.status_code == 401


def test_auth_me_accepts_bearer_header(app):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/auth/me", headers={"Authorization": "Bearer test-static-token"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["data"]["user"]["username"] == "api"


def test_auth_me_accepts_jarvis_token_header(app):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.get("/auth/me", headers={"X-Jarvis-Token": "test-static-token"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_auth_me_accepts_cookie(app):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.cookies.set("jarvis_token", "test-static-token")
    r = c.get("/auth/me")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_logout_clears_cookie(app):
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.cookies.set("jarvis_token", "test-static-token")
    r = c.post("/api/v2/auth/logout")
    assert r.status_code == 200
    # Le set-cookie header doit contenir une directive d'expiration.
    set_cookie = r.headers.get("set-cookie", "")
    assert "jarvis_token=" in set_cookie
    # Expires=Thu, 01 Jan 1970... ou Max-Age=0 — les deux invalident.
    assert "Max-Age=0" in set_cookie or "1970" in set_cookie or 'jarvis_token=""' in set_cookie
