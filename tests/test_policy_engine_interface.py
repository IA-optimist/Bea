from __future__ import annotations

import pytest

from core.policy_engine import PolicyEngine, PolicyDecision, get_policy_engine, reset_policy_engine


class TestEvaluateToolInterface:
    """Stable-interface tests for the ToolExecutor policy gate."""

    def test_evaluate_tool_allows_low_risk_read(self):
        pe = PolicyEngine(None)
        d = pe.evaluate_tool(
            tool_name="list_project_structure",
            action_type="read",
            risk_level="low",
            mission_id="m-1",
        )
        assert isinstance(d, PolicyDecision)
        assert d.allowed is True

    def test_evaluate_tool_blocks_high_risk(self):
        pe = PolicyEngine(None)
        d = pe.evaluate_tool(
            tool_name="shell_command",
            action_type="execute",
            risk_level="high",
            mission_id="m-1",
        )
        assert d.allowed is False
        assert "HIGH risk" in d.reason

    def test_evaluate_tool_blocks_unknown_execute(self):
        pe = PolicyEngine(None)
        d = pe.evaluate_tool(
            tool_name="mystery_tool",
            action_type="execute",
            risk_level="unknown",
            mission_id="m-1",
        )
        assert d.allowed is False
        assert "unknown" in d.reason.lower()

    def test_get_policy_engine_singleton_returns_same_instance(self):
        reset_policy_engine()
        a = get_policy_engine(None)
        b = get_policy_engine(None)
        assert a is b
        reset_policy_engine()

    def test_evaluate_tool_signature_compatible_with_tool_executor(self):
        """ToolExecutor calls evaluate_tool(tool_name, action_type, risk_level, mission_id, params)."""
        pe = PolicyEngine(None)
        d = pe.evaluate_tool(
            tool_name="x",
            action_type="execute",
            risk_level="low",
            mission_id="m-1",
            params={"cmd": "ls"},
        )
        assert isinstance(d, PolicyDecision)


class TestSharedSessionTracker:
    """PolicyEngine session/economic limits must be shared across ToolExecutor calls."""

    def test_same_mission_id_increments_shared_counter(self):
        pe = PolicyEngine(None)
        pe.new_session("shared-mission", "auto", limits={"max_actions_per_session": 5})
        for _ in range(3):
            d = pe.evaluate_tool("list_project_structure", "read", "low", mission_id="shared-mission")
            assert d.allowed is True
        tracker = pe.get_session("shared-mission")
        assert tracker.actions_done == 3

    def test_different_mission_ids_have_separate_counters(self):
        pe = PolicyEngine(None)
        pe.new_session("mission-a", "auto", limits={"max_actions_per_session": 5})
        pe.new_session("mission-b", "auto", limits={"max_actions_per_session": 5})
        pe.evaluate_tool("x", "read", "low", mission_id="mission-a")
        pe.evaluate_tool("x", "read", "low", mission_id="mission-a")
        pe.evaluate_tool("x", "read", "low", mission_id="mission-b")
        assert pe.get_session("mission-a").actions_done == 2
        assert pe.get_session("mission-b").actions_done == 1

    def test_action_limit_blocks_further_calls(self):
        pe = PolicyEngine(None)
        pe.new_session("limited", "auto", limits={"max_actions_per_session": 2})
        assert pe.evaluate_tool("x", "read", "low", mission_id="limited").allowed is True
        assert pe.evaluate_tool("x", "read", "low", mission_id="limited").allowed is True
        blocked = pe.evaluate_tool("x", "read", "low", mission_id="limited")
        assert blocked.allowed is False
        assert "Limite actions" in blocked.reason

    def test_low_risk_allowed_before_limit(self):
        pe = PolicyEngine(None)
        pe.new_session("low-risk", "auto", limits={"max_actions_per_session": 10})
        d = pe.evaluate_tool("list_project_structure", "read", "low", mission_id="low-risk")
        assert d.allowed is True

    def test_reset_session_clears_counter(self):
        pe = PolicyEngine(None)
        pe.new_session("reset-me", "auto", limits={"max_actions_per_session": 2})
        pe.evaluate_tool("x", "read", "low", mission_id="reset-me")
        pe.clear_sessions()
        d = pe.evaluate_tool("x", "read", "low", mission_id="reset-me")
        assert d.allowed is True
        assert pe.get_session("reset-me").actions_done == 1

    def test_no_mission_id_is_blocked_and_does_not_create_session(self):
        pe = PolicyEngine(None)
        d = pe.evaluate_tool("x", "read", "low", mission_id="")
        assert d.allowed is False
        assert "mission_id" in d.reason.lower()
        assert not pe._sessions
