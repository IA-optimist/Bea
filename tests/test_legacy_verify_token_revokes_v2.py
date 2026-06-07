"""Mo2 wire-up: the legacy api.auth.verify_token must consult the v2
revocation list when given a v2 access JWT and v2 is enabled.

This closes the deliberately-deferred gap noted in
``docs/security/jwt-hardening-v2.md``: previously a v2-minted token
revoked via /api/v2/auth/logout would still pass through the legacy
verify_token path (used by the FastAPI Depends layer), because the
legacy path didn't know about the revocation set.
"""
from __future__ import annotations

import pytest

from api import auth, jwt_v2
from tests.test_jwt_v2 import FakeRedis


@pytest.fixture
def bea_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Patch api.auth._secret directly to avoid the @lru_cache on
    get_settings() that would otherwise return the old cached secret
    in CI (where the singleton is built at import time before our env
    monkeypatch takes effect)."""
    s = "test-secret-32-bytes-or-more-please"
    monkeypatch.setenv("BEA_SECRET_KEY", s)
    monkeypatch.setattr("api.auth._secret", lambda: s)
    return s


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    jwt_v2.set_store_for_testing(fake)
    monkeypatch.setenv("JWT_REDIS_PREFIX", "test:jwt:")
    monkeypatch.setenv("JWT_ACCESS_TTL_SECONDS", "900")
    monkeypatch.setenv("JWT_REFRESH_TTL_SECONDS", "86400")
    yield fake
    jwt_v2.set_store_for_testing(None)


def test_legacy_verify_accepts_v2_token_when_not_revoked(
    monkeypatch: pytest.MonkeyPatch, bea_secret: str, fake_redis: FakeRedis,
):
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=bea_secret)

    result = auth.verify_token(pair.access_token)
    assert result is not None
    assert result["username"] == "alice"
    assert result["auth_type"] == "jwt"


def test_legacy_verify_rejects_v2_token_after_revocation(
    monkeypatch: pytest.MonkeyPatch, bea_secret: str, fake_redis: FakeRedis,
):
    """The key test: v2 tokens reaching the legacy verify_token path must
    honor the revocation list. Before this wire-up, a revoked v2 token
    still passed the legacy check, defeating /api/v2/auth/logout."""
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=bea_secret)

    # Pre-revoke: legacy path accepts.
    assert auth.verify_token(pair.access_token) is not None

    # Revoke the jti and verify the legacy path now rejects.
    jwt_v2.revoke_access_jti(pair.access_jti, remaining_ttl_seconds=900)
    assert auth.verify_token(pair.access_token) is None


def test_legacy_verify_ignores_revocation_when_flag_off(
    monkeypatch: pytest.MonkeyPatch, bea_secret: str, fake_redis: FakeRedis,
):
    """When v2 is disabled, the legacy path does NOT consult Redis even if
    the token has a jti. This preserves the rollback path: turn the flag
    off, the legacy behavior is exactly what it was before v2 landed."""
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=bea_secret)
    jwt_v2.revoke_access_jti(pair.access_jti, remaining_ttl_seconds=900)

    monkeypatch.delenv("BEA_JWT_HARDENING_V2", raising=False)

    # With the flag off, the legacy path bypasses the revocation check.
    # The token's signature + expiry are still valid, so it's accepted.
    result = auth.verify_token(pair.access_token)
    assert result is not None
    assert result["username"] == "alice"


def test_legacy_verify_legacy_token_without_jti_unchanged(
    monkeypatch: pytest.MonkeyPatch, bea_secret: str, fake_redis: FakeRedis,
):
    """A legacy long-lived JWT (no jti) must keep working under both flag
    states. Deploying the v2 module + this wire-up must not invalidate any
    active legacy session."""
    monkeypatch.setenv("BEA_JWT_HARDENING_V2", "1")
    legacy_token = auth.create_access_token(
        {"sub": "carol", "role": "user"}, expires_in=3600,
    )
    result = auth.verify_token(legacy_token)
    assert result is not None
    assert result["username"] == "carol"
    assert result["auth_type"] == "jwt"
