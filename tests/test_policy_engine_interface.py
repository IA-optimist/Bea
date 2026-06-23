from __future__ import annotations

from unittest.mock import patch

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
