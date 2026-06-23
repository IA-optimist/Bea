"""
tests/test_policy_engine_session_limits.py

Tests for PolicyEngine session tracker: idempotency, isolation, limit enforcement,
get_report(), select_llm_provider(), _cloud_allowed(), and reset via clear_sessions().
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types

if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")

    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self

    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules["structlog"] = _sl

import pytest
from core.policy_engine import PolicyEngine, get_policy_engine, reset_policy_engine


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: même mission_id => même session tracker (idempotence)
# ──────────────────────────────────────────────────────────────────────────────

def test_same_mission_id_returns_same_tracker():
    """ensure_session() is idempotent: calling twice with the same id returns the same tracker."""
    engine = PolicyEngine(None)
    t1 = engine.ensure_session("mission-abc")
    t2 = engine.ensure_session("mission-abc")
    assert t1 is t2


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: deux mission_id différents => compteurs séparés
# ──────────────────────────────────────────────────────────────────────────────

def test_different_mission_ids_have_separate_counters():
    """Two distinct sessions must not share action counters."""
    engine = PolicyEngine(None)
    t1 = engine.ensure_session("mission-1")
    t2 = engine.ensure_session("mission-2")
    t1.record_action()
    # t2's counter must remain untouched
    assert t2.actions_done == 0


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: limite actions atteinte => evaluate_tool bloque
# ──────────────────────────────────────────────────────────────────────────────

def test_session_limit_blocks_when_exceeded():
    """Once action limit is exhausted, evaluate_tool() must return not-allowed."""
    engine = PolicyEngine(None)
    # Créer la session et épuiser les actions
    tracker = engine.ensure_session("mission-limit", mode="auto")
    max_actions = tracker.limits["max_actions_per_session"]
    for _ in range(max_actions):
        tracker.record_action()

    # evaluate_tool doit désormais bloquer (il appelle tracker.record_action() +
    # tracker.check_limits() en interne via ensure_session())
    # On utilise un tool low-risk pour ne pas être bloqué par le gate HIGH-risk
    decision = engine.evaluate_tool(
        tool_name="read_file",
        action_type="read",
        risk_level="low",
        mission_id="mission-limit",
    )
    assert not decision.allowed, (
        f"Decision should be blocked after limit exhausted, got: {decision.reason}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: get_report() ne crashe pas (_cloud_allowed non-régression)
# ──────────────────────────────────────────────────────────────────────────────

def test_get_report_no_attribute_error():
    """get_report() must not raise AttributeError (cloud_allowed field)."""
    engine = PolicyEngine(None)
    report = engine.get_report()
    assert "cloud_allowed" in report


def test_get_report_returns_session_counts():
    """get_report() reflects the current number of active sessions."""
    engine = PolicyEngine(None)
    engine.ensure_session("rep-s1")
    engine.ensure_session("rep-s2")
    report = engine.get_report()
    assert report["active_sessions"] >= 2
    assert "rep-s1" in report["sessions"]
    assert "rep-s2" in report["sessions"]


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: select_llm_provider() ne crashe pas
# ──────────────────────────────────────────────────────────────────────────────

def test_select_llm_provider_no_attribute_error():
    """select_llm_provider() must not raise, and must return an LLMRoute."""
    from core.policy_engine import LLMRoute
    engine = PolicyEngine(None)
    provider = engine.select_llm_provider()
    # Any return is fine — just must not crash and must be an LLMRoute
    assert isinstance(provider, LLMRoute)


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: _cloud_allowed est bien une méthode liée à l'instance
# ──────────────────────────────────────────────────────────────────────────────

def test_cloud_allowed_is_bound_method():
    """_cloud_allowed must be callable on the instance."""
    engine = PolicyEngine(None)
    assert callable(engine._cloud_allowed)
    # Must not raise and must return a bool
    result = engine._cloud_allowed()
    assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: clear_sessions remet le compteur à zéro (reset_session via clear_sessions)
# ──────────────────────────────────────────────────────────────────────────────

def test_clear_sessions_removes_tracker():
    """After clear_sessions(), ensure_session creates a fresh tracker with 0 actions."""
    engine = PolicyEngine(None)
    t = engine.ensure_session("mission-reset")
    t.record_action()
    t.record_action()
    assert t.actions_done == 2

    engine.clear_sessions()

    # Après purge, ensure_session doit retourner un tracker neuf ou inexistant
    t2 = engine.ensure_session("mission-reset")
    # Soit c'est un objet différent, soit le compteur est remis à 0
    assert t2.actions_done == 0, (
        "Expected a fresh tracker with actions_done=0 after clear_sessions()"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: get_session() retourne None pour session inconnue
# ──────────────────────────────────────────────────────────────────────────────

def test_get_session_returns_none_for_unknown():
    """get_session() must return None if no tracker exists for that id."""
    engine = PolicyEngine(None)
    assert engine.get_session("nonexistent-mission-xyz") is None


# ──────────────────────────────────────────────────────────────────────────────
# Test 9: new_session(mode="night") lève la limite d'actions
# ──────────────────────────────────────────────────────────────────────────────

def test_night_mode_has_higher_action_limit():
    """night mode should allow more actions per session than auto."""
    engine = PolicyEngine(None)
    t_auto = engine.new_session("s-auto", mode="auto")
    t_night = engine.new_session("s-night", mode="night")
    assert t_night.limits["max_actions_per_session"] > t_auto.limits["max_actions_per_session"]


# ──────────────────────────────────────────────────────────────────────────────
# Test 10: evaluate_tool bloque les tools HIGH-risk
# ──────────────────────────────────────────────────────────────────────────────

def test_evaluate_tool_blocks_high_risk():
    """HIGH risk tools must always be blocked by evaluate_tool()."""
    engine = PolicyEngine(None)
    decision = engine.evaluate_tool(
        tool_name="git_push",
        action_type="write",
        risk_level="high",
        mission_id="m-high",
    )
    assert not decision.allowed


# ──────────────────────────────────────────────────────────────────────────────
# Test 11: evaluate_tool permet les tools LOW-risk sans mission_id
# ──────────────────────────────────────────────────────────────────────────────

def test_evaluate_tool_allows_low_risk_no_mission():
    """Low-risk tools without mission_id must be allowed."""
    engine = PolicyEngine(None)
    decision = engine.evaluate_tool(
        tool_name="read_file",
        action_type="read",
        risk_level="low",
        mission_id="",
    )
    assert decision.allowed


# ──────────────────────────────────────────────────────────────────────────────
# Test 12: singleton get_policy_engine / reset_policy_engine
# ──────────────────────────────────────────────────────────────────────────────

def test_singleton_returns_same_instance():
    """get_policy_engine() must return the same singleton across calls."""
    reset_policy_engine()
    a = get_policy_engine(None)
    b = get_policy_engine(None)
    assert a is b


def test_reset_policy_engine_creates_fresh_instance():
    """reset_policy_engine() must drop the old singleton."""
    reset_policy_engine()
    a = get_policy_engine(None)
    reset_policy_engine()
    b = get_policy_engine(None)
    assert a is not b
