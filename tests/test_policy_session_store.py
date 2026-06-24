"""
Tests for core/session_store.py and PolicyEngine store integration.

Covers:
  - InMemorySessionStore isolation by principal_id:mission_id
  - Idempotency: same principal+mission reuses session
  - session_key always requires principal (mission_id alone is insufficient)
  - approved_by has no influence on session key
  - RedisSessionStore fail-closed when Redis unreachable
  - memory store allowed when POLICY_SESSION_STORE=memory
  - cleanup does not evict active sessions
"""
from __future__ import annotations

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from core.policy_engine import PolicyEngine, reset_policy_engine, get_policy_engine
from core.session_store import InMemorySessionStore, RedisSessionStore, build_session_store


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

class _Settings:
    dry_run = False
    escalation_enabled = False
    max_policy_sessions = None


def _engine(store=None) -> PolicyEngine:
    return PolicyEngine(_Settings(), store=store or InMemorySessionStore())


# ──────────────────────────────────────────────────────────────
# 1. InMemorySessionStore — isolation by principal
# ──────────────────────────────────────────────────────────────

def test_memory_store_isolates_by_principal():
    """Same mission_id but different principal_id → two independent sessions."""
    engine = _engine()
    engine.ensure_session("mission-1", principal_id="alice")
    engine.ensure_session("mission-1", principal_id="bob")

    # Increment alice's session only
    engine.evaluate_tool("read_file", "read", "low",
                         mission_id="mission-1", principal_id="alice")

    alice = engine.get_session("mission-1", principal_id="alice")
    bob   = engine.get_session("mission-1", principal_id="bob")

    assert alice is not None
    assert bob is not None
    assert alice.actions_done == 1
    assert bob.actions_done == 0, "bob's session must be untouched"


# ──────────────────────────────────────────────────────────────
# 2. Same principal + mission → same session (idempotent)
# ──────────────────────────────────────────────────────────────

def test_memory_store_same_principal_same_mission_reuses():
    engine = _engine()
    s1 = engine.ensure_session("mission-2", principal_id="carol")
    s1.actions_done = 5

    s2 = engine.ensure_session("mission-2", principal_id="carol")
    assert s2.actions_done == 5, "ensure_session must return the existing session"
    assert s1 is s2


# ──────────────────────────────────────────────────────────────
# 3. mission_id alone is insufficient — principal_id changes the key
# ──────────────────────────────────────────────────────────────

def test_session_key_requires_principal():
    """Accessing a session without principal_id must not collide with a
    principal-bound session for the same mission_id."""
    engine = _engine()
    engine.ensure_session("mission-3", principal_id="dave")

    # Lookup without principal — different key → None
    no_principal_session = engine.get_session("mission-3", principal_id=None)
    dave_session         = engine.get_session("mission-3", principal_id="dave")

    assert dave_session is not None
    # The no-principal lookup is a raw mission_id key — does NOT collide with
    # dave's principal-bound key.
    assert no_principal_session is None or no_principal_session is not dave_session


# ──────────────────────────────────────────────────────────────
# 4. approved_by must NOT influence session key
# ──────────────────────────────────────────────────────────────

def test_approved_by_not_used_in_session_key():
    """approved_by is audit-only; the session key is (principal_id, mission_id)."""
    engine = _engine()
    session = engine.ensure_session("mission-4", principal_id="eve")
    session.actions_done = 3

    # Simulate an approval event: approved_by = "frank"
    # The session must NOT be affected or re-created.
    approved_by = "frank"

    # approved_by is never passed to PolicyEngine — it stays audit-only.
    # Verify the session under "eve" is unchanged.
    retrieved = engine.get_session("mission-4", principal_id="eve")
    assert retrieved is not None
    assert retrieved.actions_done == 3

    # Verify no session exists under approved_by
    approved_by_session = engine.get_session("mission-4", principal_id=approved_by)
    assert approved_by_session is None, (
        "approved_by must never create or reference a policy session"
    )


# ──────────────────────────────────────────────────────────────
# 5. RedisSessionStore — fail-closed when Redis unreachable
# ──────────────────────────────────────────────────────────────

def test_redis_store_fail_closed_if_unavailable():
    """RedisSessionStore must raise RuntimeError when Redis is unreachable.
    No silent fallback to InMemorySessionStore."""
    import redis as _redis

    with patch.object(_redis, "from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_client.ping.side_effect = _redis.ConnectionError("connection refused")
        mock_from_url.return_value = mock_client

        with pytest.raises(RuntimeError, match="cannot reach Redis"):
            RedisSessionStore("redis://localhost:6379")


# ──────────────────────────────────────────────────────────────
# 6. memory backend is explicitly allowed in dev
# ──────────────────────────────────────────────────────────────

def test_memory_store_allowed_in_dev(monkeypatch):
    monkeypatch.setenv("POLICY_SESSION_STORE", "memory")
    monkeypatch.delenv("REDIS_URL", raising=False)

    store = build_session_store()
    assert isinstance(store, InMemorySessionStore)


def test_redis_store_required_config_raises(monkeypatch):
    """POLICY_SESSION_STORE=redis without REDIS_URL must raise."""
    monkeypatch.setenv("POLICY_SESSION_STORE", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        build_session_store()


# ──────────────────────────────────────────────────────────────
# 7. Cleanup does not evict active sessions
# ──────────────────────────────────────────────────────────────

def test_cleanup_does_not_remove_active_sessions():
    """_cleanup_expired_sessions must not touch sessions that have not timed out."""
    engine = _engine()
    # Session with very long timeout — not expired
    engine.new_session("active-mission", limits={"max_actions_per_session": 10,
                                                  "max_tokens_per_session": 50_000,
                                                  "max_cloud_calls_per_session": 5,
                                                  "max_cost_usd_per_session": 0.5,
                                                  "session_timeout_s": 9999},
                       principal_id="grace")

    engine._cleanup_expired_sessions()

    still_there = engine.get_session("active-mission", principal_id="grace")
    assert still_there is not None, "active session must survive cleanup"


def test_cleanup_removes_expired_sessions():
    """_cleanup_expired_sessions must remove sessions past their timeout."""
    engine = _engine()
    engine.new_session("old-mission", limits={"max_actions_per_session": 10,
                                               "max_tokens_per_session": 50_000,
                                               "max_cloud_calls_per_session": 5,
                                               "max_cost_usd_per_session": 0.5,
                                               "session_timeout_s": 1},
                       principal_id="henry")

    # Back-date the session start so it appears expired
    key = engine._session_key("old-mission", "henry")
    session = engine._sessions.get(key)
    assert session is not None
    session.started_at -= 10  # 10s ago, timeout=1s → expired
    engine._sessions.set(key, session)

    engine._cleanup_expired_sessions()

    gone = engine.get_session("old-mission", principal_id="henry")
    assert gone is None, "expired session must be evicted"


# ──────────────────────────────────────────────────────────────
# 8. get_policy_engine() uses InMemory by default
# ──────────────────────────────────────────────────────────────

def test_get_policy_engine_uses_memory_by_default(monkeypatch):
    monkeypatch.setenv("POLICY_SESSION_STORE", "memory")
    reset_policy_engine()
    engine = get_policy_engine(_Settings())
    assert isinstance(engine._sessions, InMemorySessionStore)
    reset_policy_engine()


# ──────────────────────────────────────────────────────────────
# 9. Thread safety: 20 concurrent evaluate_tool calls on limit=2
# ──────────────────────────────────────────────────────────────

def test_concurrent_evaluate_tool_respects_limit():
    """check_and_record() with InMemorySessionStore: only 2 actions allowed."""
    engine = _engine()
    engine.ensure_session("m-concurrent", principal_id="iris",
                          # inject custom limits via new_session
                          )
    # Override limits to max 2
    engine.new_session("m-concurrent", limits={"max_actions_per_session": 2,
                                                "max_tokens_per_session": 50_000,
                                                "max_cloud_calls_per_session": 5,
                                                "max_cost_usd_per_session": 0.5,
                                                "session_timeout_s": 600},
                       principal_id="iris")

    results = []
    lock = threading.Lock()

    def call():
        d = engine.evaluate_tool("read_file", "read", "low",
                                 mission_id="m-concurrent", principal_id="iris")
        with lock:
            results.append(d.allowed)

    threads = [threading.Thread(target=call) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed = sum(1 for r in results if r)
    assert allowed == 2, f"Expected exactly 2 allowed, got {allowed}"
