"""
tests/test_policy_engine_session_hardening.py

Edge-case hardening tests for PolicyEngine session tracker after PR #114.

Covers:
  - explicit limits always override mode presets
  - atomic check_limits + record_action under concurrency
  - expired session eviction
  - empty/None mission_id fail-closed
  - high-risk without mission_id blocked
  - principal/owner separation for same mission_id
  - get_report / select_llm_provider non-regression
"""
from __future__ import annotations

import threading
import time

import pytest

from core.policy_engine import (
    PolicyEngine,
    LLMRoute,
    get_policy_engine,
    reset_policy_engine,
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Explicit limits override mode presets
# ──────────────────────────────────────────────────────────────────────────────

def test_explicit_limits_override_night_mode_preset():
    """An explicit max_actions limit must win over the night-mode preset (30)."""
    engine = PolicyEngine(None)
    tracker = engine.new_session(
        "s-night-limit",
        mode="night",
        limits={"max_actions_per_session": 5},
    )
    assert tracker.limits["max_actions_per_session"] == 5


def test_explicit_limits_override_improve_mode_preset():
    engine = PolicyEngine(None)
    tracker = engine.new_session(
        "s-improve-limit",
        mode="improve",
        limits={"max_actions_per_session": 3, "session_timeout_s": 120},
    )
    assert tracker.limits["max_actions_per_session"] == 3
    assert tracker.limits["session_timeout_s"] == 120


def test_mode_preset_applies_when_no_explicit_limit():
    engine = PolicyEngine(None)
    night = engine.new_session("s-night-default", mode="night")
    assert night.limits["max_actions_per_session"] == 30
    assert night.limits["session_timeout_s"] == 1800

    improve = engine.new_session("s-improve-default", mode="improve")
    assert improve.limits["max_actions_per_session"] == 15


# ──────────────────────────────────────────────────────────────────────────────
# 2. Atomic check + record under concurrency
# ──────────────────────────────────────────────────────────────────────────────

def test_check_and_record_is_atomic_with_limit_one():
    """With limit 1, two concurrent calls cannot both be allowed."""
    engine = PolicyEngine(None)
    engine.new_session("race", "auto", limits={"max_actions_per_session": 1})

    results = {"allowed": 0, "denied": 0, "errors": []}
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=2)
            d = engine.evaluate_tool("x", "read", "low", mission_id="race")
            if d.allowed:
                results["allowed"] += 1
            else:
                results["denied"] += 1
        except Exception as e:
            results["errors"].append(str(e))

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not results["errors"]
    assert results["allowed"] == 1, f"expected exactly 1 allowed, got {results}"
    assert results["denied"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# 3. Expired session eviction
# ──────────────────────────────────────────────────────────────────────────────

def test_expired_session_is_evicted_on_ensure_session():
    engine = PolicyEngine(None)
    engine.new_session(
        "expiring",
        "auto",
        limits={"max_actions_per_session": 10, "session_timeout_s": 0.01},
    )
    # Session should exist immediately
    assert engine.get_session("expiring") is not None

    time.sleep(0.02)
    # Eviction runs on ensure_session / get_report
    engine.ensure_session("later")

    assert engine.get_session("expiring") is None
    report = engine.get_report()
    assert "expiring" not in report["sessions"]


def test_expired_session_replaced_cleanly():
    engine = PolicyEngine(None)
    t1 = engine.new_session(
        "reused",
        "auto",
        limits={"max_actions_per_session": 10, "session_timeout_s": 0.01},
    )
    t1.record_action()
    time.sleep(0.02)
    t2 = engine.ensure_session("reused")
    assert t2.actions_done == 0
    assert engine.get_session("reused") is t2


def test_max_sessions_cap_evicts_oldest():
    """When cap is exceeded, oldest sessions are evicted."""
    class _Settings:
        max_policy_sessions = 3

    engine = PolicyEngine(_Settings())
    for i in range(4):
        engine.new_session(f"sess-{i}")
        time.sleep(0.001)

    engine.ensure_session("trigger-cleanup")
    report = engine.get_report()
    assert "sess-0" not in report["sessions"]
    assert "sess-3" in report["sessions"]


# ──────────────────────────────────────────────────────────────────────────────
# 4. Empty / None mission_id fail-closed
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing_id", ["", None])
def test_evaluate_tool_blocks_empty_or_none_mission_id(missing_id):
    engine = PolicyEngine(None)
    d = engine.evaluate_tool(
        tool_name="read_file",
        action_type="read",
        risk_level="low",
        mission_id=missing_id,
    )
    assert not d.allowed
    assert "mission_id" in d.reason.lower()


def test_empty_mission_id_does_not_create_session():
    engine = PolicyEngine(None)
    engine.evaluate_tool("x", "read", "low", mission_id="")
    assert not engine._sessions


# ──────────────────────────────────────────────────────────────────────────────
# 5. High-risk without mission_id is blocked
# ──────────────────────────────────────────────────────────────────────────────

def test_high_risk_without_mission_id_blocked():
    engine = PolicyEngine(None)
    d = engine.evaluate_tool(
        tool_name="shell_command",
        action_type="execute",
        risk_level="high",
        mission_id="",
    )
    assert not d.allowed
    assert "HIGH risk" in d.reason


# ──────────────────────────────────────────────────────────────────────────────
# 6. Principal / owner separation
# ──────────────────────────────────────────────────────────────────────────────

def test_same_mission_id_different_principal_are_separate_sessions():
    engine = PolicyEngine(None)
    t_a = engine.ensure_session(
        "shared-mission",
        principal_id="principal-a",
    )
    t_b = engine.ensure_session(
        "shared-mission",
        principal_id="principal-b",
    )

    assert t_a is not t_b
    t_a.record_action()
    assert t_b.actions_done == 0


def test_raw_mission_id_without_principal_remains_supported():
    engine = PolicyEngine(None)
    t1 = engine.ensure_session("raw-mission")
    t2 = engine.ensure_session("raw-mission")
    assert t1 is t2


def test_session_key_normalization_private():
    engine = PolicyEngine(None)
    assert engine._session_key("m") == "m"
    assert engine._session_key("m", principal_id="p") == "p:m"


# ──────────────────────────────────────────────────────────────────────────────
# 7. get_report still works
# ──────────────────────────────────────────────────────────────────────────────

def test_get_report_still_works_after_hardening():
    engine = PolicyEngine(None)
    engine.ensure_session("r1")
    report = engine.get_report()
    assert "active_sessions" in report
    assert "cloud_allowed" in report
    assert "r1" in report["sessions"]


# ──────────────────────────────────────────────────────────────────────────────
# 8. select_llm_provider still works
# ──────────────────────────────────────────────────────────────────────────────

def test_select_llm_provider_still_works():
    engine = PolicyEngine(None)
    route = engine.select_llm_provider()
    assert isinstance(route, LLMRoute)


# ──────────────────────────────────────────────────────────────────────────────
# 9. Singleton reset still works
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_policy_engine_singleton_works():
    reset_policy_engine()
    a = get_policy_engine(None)
    reset_policy_engine()
    b = get_policy_engine(None)
    assert a is not b


# ──────────────────────────────────────────────────────────────────────────────
# 10. Principal auth binding — evaluate_tool uses explicit principal, not params
# ──────────────────────────────────────────────────────────────────────────────

def test_evaluate_tool_uses_explicit_principal_not_params():
    """evaluate_tool must use the principal_id explicit arg, not params dict."""
    engine = PolicyEngine(None)
    # Pre-create sessions for two principals
    engine.ensure_session("m1", principal_id="alice")
    engine.ensure_session("m1", principal_id="bob")

    # Call with explicit principal_id="alice"
    d = engine.evaluate_tool("read_file", "read", "low", mission_id="m1", principal_id="alice")
    assert d.allowed

    # Session for alice has 1 action; bob session still at 0
    assert engine.get_session("m1", principal_id="alice").actions_done == 1
    assert engine.get_session("m1", principal_id="bob").actions_done == 0


def test_client_cannot_override_principal_via_params():
    """Passing principal_id inside params dict must not affect session key.

    Before this fix, _extract_principal_id(params) could be spoofed by a client
    sending {'principal_id': 'victim', ...} in the request body.
    After this fix, params['principal_id'] is ignored; only the explicit arg counts.
    """
    engine = PolicyEngine(None)
    # Pre-seed victim's session with limit=1 (already at 0 actions)
    engine.ensure_session("shared-mission", principal_id="victim")

    # Attacker sends params claiming to be "victim" — must NOT pollute victim session.
    # No explicit principal_id passed → falls back to raw mission_id key.
    attacker_params = {"principal_id": "victim", "mission_id": "shared-mission"}
    engine.evaluate_tool(
        "read_file", "read", "low",
        mission_id="shared-mission",
        params=attacker_params,
        # principal_id intentionally NOT passed (simulates unauthenticated path)
    )

    # Victim's session must be untouched
    victim_session = engine.get_session("shared-mission", principal_id="victim")
    assert victim_session is not None
    assert victim_session.actions_done == 0, (
        "Victim session was polluted by attacker params — principal override bug"
    )


def test_missing_authenticated_principal_falls_back_to_raw_mission_key():
    """When no authenticated principal is provided, session key = raw mission_id.

    This is the safe fallback for internal/test callers.  It must NOT share state
    with a session that has a principal bound.
    """
    engine = PolicyEngine(None)
    engine.ensure_session("m-raw")
    engine.ensure_session("m-raw", principal_id="alice")

    d_raw = engine.evaluate_tool("read_file", "read", "low", mission_id="m-raw")
    assert d_raw.allowed

    # Alice's session still untouched
    assert engine.get_session("m-raw", principal_id="alice").actions_done == 0
    # Raw key session was incremented
    assert engine.get_session("m-raw").actions_done == 1


def test_check_action_session_lookup_uses_session_key():
    """check_action() must use _session_key so principal-bound sessions are found."""
    engine = PolicyEngine(None)
    tracker = engine.ensure_session("ca-mission", principal_id="user-x")
    # Exhaust the session
    for _ in range(tracker.limits["max_actions_per_session"]):
        tracker.record_action()

    d = engine.check_action(
        "write_file", "low", "auto",
        session_id="ca-mission",
        principal_id="user-x",
    )
    assert not d.allowed

    # Without principal, a separate session exists (raw key) → should be OK
    d_raw = engine.check_action(
        "write_file", "low", "auto",
        session_id="ca-mission",
    )
    assert d_raw.allowed
