"""End-to-end auth routes tests under both flag states.

Verifies the wiring in ``api/routes/auth.py``:

  * Flag OFF: ``/auth/token`` returns the legacy single token, no refresh.
  * Flag ON: ``/auth/token`` returns access + refresh + expires_in.
  * Flag ON: ``/auth/refresh`` rotates the refresh token; replay → 401.
  * Flag ON: ``/auth/logout`` revokes the access JTI server-side.
"""
from __future__ import annotations

import os
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import jwt_v2
from api.routes import auth as auth_routes
from tests.test_jwt_v2 import FakeRedis


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def bea_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Patch api.auth._secret to bypass the @lru_cache on get_settings()."""
    s = "test-secret-32-bytes-or-more-please"
    monkeypatch.setenv("BEA_SECRET_KEY", s)
    monkeypatch.setenv("BEA_ADMIN_PASSWORD", "admin-password-for-test")
    monkeypatch.setattr("api.auth._secret", lambda: s)
    return s


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    jwt_v2.set_store_for_testing(fake)
    monkeypatch.setenv("JWT_ACCESS_TTL_SECONDS", "900")
    monkeypatch.setenv("JWT_REFRESH_TTL_SECONDS", "86400")
    monkeypatch.setenv("JWT_REDIS_PREFIX", "test:jwt:")
    yield fake
    jwt_v2.set_store_for_testing(None)


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(auth_routes.router)
    return a


# ── Flag OFF: legacy behavior unchanged ──────────────────────────

def test_login_flag_off_returns_single_token(monkeypatch: pytest.MonkeyPatch,
                                              app: FastAPI, bea_secret: str):
    monkeypatch.delenv("BEA_JWT_HARDENING_V2", raising=False)
    client = TestClient(app)
    r = client.post("/auth/token", data={
        "username": "admin", "password": "admin-password-for-test",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "refresh_token" not in body
    assert "expires_in" not in body


# ── Flag ON: v2 contract ─────────────────────────────────────────

def test_login_flag_on_returns_pair(monkeypatch: pytest.MonkeyPatch,
                                     app: FastAPI, bea_secret: str,
                                     fake_redis: FakeRedis):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    client = TestClient(app)
    r = client.post("/auth/token", data={
        "username": "admin", "password": "admin-password-for-test",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 900
    assert body["refresh_expires_in"] == 86400


def test_login_flag_on_rejects_bad_password(monkeypatch: pytest.MonkeyPatch,
                                              app: FastAPI, bea_secret: str,
                                              fake_redis: FakeRedis):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    client = TestClient(app)
    r = client.post("/auth/token", data={
        "username": "admin", "password": "wrong-password",
    })
    assert r.status_code == 401


def test_refresh_flag_on_rotates(monkeypatch: pytest.MonkeyPatch,
                                  app: FastAPI, bea_secret: str,
                                  fake_redis: FakeRedis):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    client = TestClient(app)
    login = client.post("/auth/token", data={
        "username": "admin", "password": "admin-password-for-test",
    }).json()

    refreshed = client.post("/auth/refresh", json={
        "refresh_token": login["refresh_token"],
    })
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["access_token"] != login["access_token"]
    assert body["refresh_token"] != login["refresh_token"]


def test_refresh_flag_on_detects_replay(monkeypatch: pytest.MonkeyPatch,
                                         app: FastAPI, bea_secret: str,
                                         fake_redis: FakeRedis):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    client = TestClient(app)
    login = client.post("/auth/token", data={
        "username": "admin", "password": "admin-password-for-test",
    }).json()

    # First rotation succeeds.
    first = client.post("/auth/refresh", json={
        "refresh_token": login["refresh_token"],
    })
    assert first.status_code == 200

    # Replay the original refresh — must be rejected.
    replay = client.post("/auth/refresh", json={
        "refresh_token": login["refresh_token"],
    })
    assert replay.status_code == 401
    assert "replay" in replay.json()["detail"]


def test_refresh_flag_on_missing_token(monkeypatch: pytest.MonkeyPatch,
                                        app: FastAPI, bea_secret: str,
                                        fake_redis: FakeRedis):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    client = TestClient(app)
    r = client.post("/auth/refresh", json={})
    assert r.status_code == 401
    assert "missing" in r.json()["detail"]


def test_logout_flag_on_revokes_jti(monkeypatch: pytest.MonkeyPatch,
                                     app: FastAPI, bea_secret: str,
                                     fake_redis: FakeRedis):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    client = TestClient(app)
    login = client.post("/auth/token", data={
        "username": "admin", "password": "admin-password-for-test",
    }).json()

    # Verify token works before logout
    pre = jwt_v2.verify_access_token(login["access_token"], bea_secret)
    assert pre is not None

    # Logout: must mark JTI revoked.
    client.cookies.set("bea_token", login["access_token"])
    r = client.post(
        "/api/v2/auth/logout",
        json={"refresh_token": login["refresh_token"]},
    )
    assert r.status_code == 200

    # Token must now fail verification (jti is revoked).
    post = jwt_v2.verify_access_token(login["access_token"], bea_secret)
    assert post is None

    # And the refresh must be unusable.
    replay = client.post("/auth/refresh", json={
        "refresh_token": login["refresh_token"],
    })
    assert replay.status_code == 401


def test_legacy_refresh_path_still_works_when_flag_off(
    monkeypatch: pytest.MonkeyPatch, app: FastAPI, bea_secret: str,
):
    """Deploying the v2 module must not break the legacy refresh path."""
    monkeypatch.delenv("BEA_JWT_HARDENING_V2", raising=False)
    client = TestClient(app)

    login = client.post("/auth/token", data={
        "username": "admin", "password": "admin-password-for-test",
    }).json()
    legacy_token = login["access_token"]

    # Legacy refresh expects the old token from cookie / Authorization.
    client.cookies.set("bea_token", legacy_token)
    r = client.post(
        "/auth/refresh",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    # Same claims + same secret + same iat (same second) → same JWT bytes; only
    # the contract matters here: legacy path issues a single bearer token, no
    # refresh field. The token's freshness is implicit in iat/exp updating on
    # subsequent calls.
    assert "refresh_token" not in body
    assert body["token_type"] == "bearer"
