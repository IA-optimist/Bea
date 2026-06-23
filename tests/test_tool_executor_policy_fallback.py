from __future__ import annotations

from unittest.mock import patch

from core.tool_executor import get_tool_executor


def test_policy_unavailable_blocks_shell_command():
    """Regression: policy engine failure must block high-risk execute tools."""
    executor = get_tool_executor()
    with patch("core.policy_engine.PolicyEngine") as MockPE:
        instance = MockPE.return_value
        instance.evaluate_tool.side_effect = RuntimeError("policy engine unavailable")
        result = executor.execute(
            "shell_command",
            {"cmd": "ls -la", "mission_id": "test-policy-down"},
        )
    assert result.get("blocked_by_policy") is True
    assert "policy_unavailable_high_risk" in result.get("error", "")
