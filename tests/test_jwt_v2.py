"""Tests for api.jwt_v2 — short access + rotating refresh + revocation.

These tests use an in-memory fake Redis (no real redis instance needed) so
they run identically locally and in CI.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import pytest

from api import jwt_v2


# ── In-memory fake Redis ────────────────────────────────────────

class FakeRedis:
    """A minimal in-memory stand-in for ``redis.Redis`` matching the
    :class:`api.jwt_v2.RedisStore` protocol."""

    def __init__(self) -> None:
        self.kv: dict[str, tuple[bytes, Optional[float]]] = {}
        self.sets: dict[str, set[bytes]] = {}

    # tuple value = (raw_bytes, expires_at_or_None)
    def _alive(self, key: str) -> bool:
        item = self.kv.get(key)
        if item is None:
            return False
        _value, exp = item
        if exp is not None and time.time() >= exp:
            del self.kv[key]
            return False
        return True

    def get(self, key: str) -> Optional[bytes]:
        if not self._alive(key):
            return None
        return self.kv[key][0]

    def set(self, key: str, value: bytes, ex: Optional[int] = None) -> bool:
        exp = (time.time() + ex) if ex is not None else None
        self.kv[key] = (value, exp)
        return True

    def delete(self, key: str) -> int:
        existed = key in self.kv
        self.kv.pop(key, None)
        existed_set = key in self.sets
        self.sets.pop(key, None)
        return int(existed or existed_set)

    def exists(self, key: str) -> int:
        return 1 if self._alive(key) else 0

    def sadd(self, key: str, *values: bytes) -> int:
        s = self.sets.setdefault(key, set())
        before = len(s)
        s.update(values)
        return len(s) - before

    def smembers(self, key: str) -> set[bytes]:
        return set(self.sets.get(key, set()))

    def expire(self, key: str, seconds: int) -> bool:
        # FakeRedis intentionally ignores set TTLs for simplicity; the
        # rotation/replay logic doesn't depend on TTL on set keys, only on
        # string keys (which we honor via _alive).
        return True


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture
def secret() -> str:
    return "test-secret-for-jwt-v2-do-not-use-in-prod"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    jwt_v2.set_store_for_testing(fake)
    monkeypatch.setenv("JWT_ACCESS_TTL_SECONDS", "900")
    monkeypatch.setenv("JWT_REFRESH_TTL_SECONDS", "86400")
    monkeypatch.setenv("JWT_REDIS_PREFIX", "test:jwt:")
    yield fake
    jwt_v2.set_store_for_testing(None)


# ── is_v2_enabled ───────────────────────────────────────────────

def test_feature_flag_default_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JARVIS_JWT_HARDENING_V2", raising=False)
    assert jwt_v2.is_v2_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_feature_flag_enabled_values(value: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JARVIS_JWT_HARDENING_V2", value)
    assert jwt_v2.is_v2_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_feature_flag_disabled_values(value: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JARVIS_JWT_HARDENING_V2", value)
    assert jwt_v2.is_v2_enabled() is False


# ── create_token_pair ───────────────────────────────────────────

def test_create_token_pair_returns_complete_struct(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    assert pair.access_token
    assert pair.refresh_token
    assert pair.access_jti
    assert pair.family_id
    assert pair.access_expires_in == 900
    assert pair.refresh_expires_in == 86400


def test_create_token_pair_requires_sub(secret: str, store: FakeRedis):
    with pytest.raises(ValueError, match="sub"):
        jwt_v2.create_token_pair(sub="", role="user", secret=secret)


def test_access_token_carries_expected_claims(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="admin", secret=secret)
    claims = jwt_v2.verify_access_token(pair.access_token, secret)
    assert claims is not None
    assert claims["sub"] == "alice"
    assert claims["role"] == "admin"
    assert claims["typ"] == "access"
    assert claims["jti"] == pair.access_jti
    assert claims["exp"] > claims["iat"]


def test_two_pairs_have_distinct_jti_and_family(secret: str, store: FakeRedis):
    p1 = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    p2 = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    assert p1.access_jti != p2.access_jti
    assert p1.family_id != p2.family_id
    assert p1.refresh_token != p2.refresh_token


# ── verify_access_token ─────────────────────────────────────────

def test_verify_rejects_tampered_signature(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    tampered = pair.access_token[:-2] + ("AA" if pair.access_token[-2:] != "AA" else "BB")
    assert jwt_v2.verify_access_token(tampered, secret) is None


def test_verify_rejects_wrong_secret(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    assert jwt_v2.verify_access_token(pair.access_token, "wrong-secret") is None


def test_verify_rejects_expired_token(monkeypatch: pytest.MonkeyPatch,
                                       secret: str, store: FakeRedis):
    monkeypatch.setenv("JWT_ACCESS_TTL_SECONDS", "1")
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    time.sleep(1.2)
    assert jwt_v2.verify_access_token(pair.access_token, secret) is None


def test_verify_accepts_legacy_tokens_without_jti(secret: str, store: FakeRedis):
    """A legacy 30-day JWT (no jti) must still validate so deploying v2
    does not invalidate existing sessions."""
    import jwt as _jwt
    legacy = _jwt.encode(
        {"sub": "carol", "role": "user", "exp": int(time.time()) + 3600,
         "iat": int(time.time())},
        secret, algorithm="HS256",
    )
    claims = jwt_v2.verify_access_token(legacy, secret)
    assert claims is not None
    assert claims["sub"] == "carol"
    assert "jti" not in claims


# ── revoke_access_jti ───────────────────────────────────────────

def test_revoked_jti_invalidates_token(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    assert jwt_v2.verify_access_token(pair.access_token, secret) is not None
    jwt_v2.revoke_access_jti(pair.access_jti, remaining_ttl_seconds=900)
    assert jwt_v2.verify_access_token(pair.access_token, secret) is None


def test_revoke_access_jti_no_op_for_empty_jti(store: FakeRedis):
    jwt_v2.revoke_access_jti("", remaining_ttl_seconds=60)
    # No exception, no Redis write.
    assert len(store.kv) == 0


# ── rotate_refresh_token ────────────────────────────────────────

def test_rotate_issues_new_pair(secret: str, store: FakeRedis):
    p1 = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    p2 = jwt_v2.rotate_refresh_token(p1.refresh_token, secret)
    assert p2.refresh_token != p1.refresh_token
    assert p2.access_jti != p1.access_jti
    assert p2.family_id == p1.family_id, "rotation must stay in the same family"


def test_rotate_invalidates_old_refresh_token(secret: str, store: FakeRedis):
    p1 = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    jwt_v2.rotate_refresh_token(p1.refresh_token, secret)
    # Replaying the original refresh should now be detected as a replay
    with pytest.raises(ValueError, match="replay"):
        jwt_v2.rotate_refresh_token(p1.refresh_token, secret)


def test_rotate_rejects_unknown_token(secret: str, store: FakeRedis):
    with pytest.raises(ValueError, match="unknown_or_expired"):
        jwt_v2.rotate_refresh_token("nonexistent-token-abc", secret)


def test_replay_revokes_entire_family(secret: str, store: FakeRedis):
    """If we rotate p1 -> p2 -> p3 and then replay p1, the whole family
    (including p3, the only live token) must be invalidated."""
    p1 = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    p2 = jwt_v2.rotate_refresh_token(p1.refresh_token, secret)
    p3 = jwt_v2.rotate_refresh_token(p2.refresh_token, secret)

    # p3 is currently the only live refresh token in the family
    with pytest.raises(ValueError, match="replay"):
        jwt_v2.rotate_refresh_token(p1.refresh_token, secret)

    # p3 must now also be rejected
    with pytest.raises(ValueError, match="unknown_or_expired"):
        jwt_v2.rotate_refresh_token(p3.refresh_token, secret)


def test_rotated_pair_has_working_access_token(secret: str, store: FakeRedis):
    p1 = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    p2 = jwt_v2.rotate_refresh_token(p1.refresh_token, secret)
    claims = jwt_v2.verify_access_token(p2.access_token, secret)
    assert claims is not None
    assert claims["sub"] == "alice"
    assert claims["jti"] == p2.access_jti


# ── revoke_refresh_token ────────────────────────────────────────

def test_revoke_refresh_token_invalidates_it(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    jwt_v2.revoke_refresh_token(pair.refresh_token)
    with pytest.raises(ValueError, match="unknown_or_expired"):
        jwt_v2.rotate_refresh_token(pair.refresh_token, secret)


def test_revoke_refresh_token_idempotent(secret: str, store: FakeRedis):
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)
    jwt_v2.revoke_refresh_token(pair.refresh_token)
    jwt_v2.revoke_refresh_token(pair.refresh_token)  # no exception


def test_revoke_refresh_token_no_op_for_empty(store: FakeRedis):
    jwt_v2.revoke_refresh_token("")  # no exception, no writes


# ── Resilience: Redis down ──────────────────────────────────────

def test_verify_falls_back_when_revocation_store_unavailable(
    secret: str, monkeypatch: pytest.MonkeyPatch,
):
    """If Redis is unreachable, verify_access_token must still accept a
    structurally valid token (signature + expiry OK). Failing closed would
    make every API call return 401 during a Redis outage."""
    monkeypatch.setenv("JWT_REDIS_PREFIX", "test:jwt:")
    # First create a token with a real store
    fake = FakeRedis()
    jwt_v2.set_store_for_testing(fake)
    pair = jwt_v2.create_token_pair(sub="alice", role="user", secret=secret)

    # Now make exists() raise to simulate Redis being down
    class BrokenStore(FakeRedis):
        def exists(self, key: str) -> int:  # type: ignore[override]
            raise ConnectionError("redis is on fire")

    jwt_v2.set_store_for_testing(BrokenStore())

    claims = jwt_v2.verify_access_token(pair.access_token, secret)
    assert claims is not None
    assert claims["sub"] == "alice"

    jwt_v2.set_store_for_testing(None)
