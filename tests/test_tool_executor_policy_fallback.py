from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.execution_policy import Decision
from core.tool_executor import get_tool_executor


def _allowing_permission_check():
    """Return mocks that let the request reach the policy/execution gates."""
    cap_reg = MagicMock()
    cap_reg.check_permission.return_value = {"allowed": True, "requires_approval": False}
    tool_perm = MagicMock()
    tool_perm.check.return_value = {"allowed": True, "request": None}
    cb = MagicMock()
    cb.can_execute.return_value = True
    return {
        "core.capabilities.registry.get_capability_registry": cap_reg,
        "core.tool_permissions.get_tool_permissions": tool_perm,
        "core.resilience.get_circuit_breaker": cb,
    }


def _mk_policy_mock(allowed: bool = True, reason: str = "tool_allowed"):
    """Return a PolicyEngine mock whose evaluate_tool returns the desired decision."""
    m = MagicMock()
    d = MagicMock()
    d.allowed = allowed
    d.reason = reason
    m.evaluate_tool.return_value = d
    return m


@pytest.mark.parametrize("tool", ["shell_command", "execute_code"])
def test_policy_unavailable_blocks_execute_tools(tool):
    """Regression: policy engine failure must block high-risk execute tools."""
    executor = get_tool_executor()
    mocks = _allowing_permission_check()
    with (
        patch("core.policy_engine.get_policy_engine") as mock_get_policy,
        patch("core.capabilities.registry.get_capability_registry", return_value=mocks["core.capabilities.registry.get_capability_registry"]),
        patch("core.tool_permissions.get_tool_permissions", return_value=mocks["core.tool_permissions.get_tool_permissions"]),
        patch("core.resilience.get_circuit_breaker", return_value=mocks["core.resilience.get_circuit_breaker"]),
    ):
        mock_get_policy.return_value.evaluate_tool.side_effect = RuntimeError("policy engine unavailable")
        params = {"cmd": "ls -la", "code": "print(1)", "mission_id": "test-policy-down"}
        result = executor.execute(tool, params)
    assert result.get("blocked_by_policy") is True
    assert "policy_unavailable_high_risk" in result.get("error", "")


def test_low_risk_read_tool_allowed_when_policy_ok():
    """Read-only low-risk tools should remain available when both gates are healthy."""
    executor = get_tool_executor()
    mocks = _allowing_permission_check()
    with (
        patch("core.policy_engine.get_policy_engine", return_value=_mk_policy_mock(allowed=True)),
        patch("core.capabilities.registry.get_capability_registry", return_value=mocks["core.capabilities.registry.get_capability_registry"]),
        patch("core.tool_permissions.get_tool_permissions", return_value=mocks["core.tool_permissions.get_tool_permissions"]),
        patch("core.resilience.get_circuit_breaker", return_value=mocks["core.resilience.get_circuit_breaker"]),
        patch.object(executor, "_tools", {"list_project_structure": lambda **_: {"ok": True, "result": "ok"}}),
    ):
        result = executor.execute("list_project_structure", {"path": ".", "mission_id": "test-low-risk"})
    assert result.get("blocked_by_policy") is not True
    assert result.get("ok") is True


def test_execution_policy_requires_approval_blocks_tool():
    """ExecutionPolicy returning REQUIRES_APPROVAL must block the tool call."""
    executor = get_tool_executor()
    mocks = _allowing_permission_check()
    fake_decision = MagicMock()
    fake_decision.decision = Decision.REQUIRES_APPROVAL
    fake_decision.reason = "supervised_requires_approval"
    with (
        patch("core.execution_policy.get_execution_policy") as mock_exec_policy,
        patch("core.policy_engine.get_policy_engine", return_value=_mk_policy_mock(allowed=True)),
        patch("core.capabilities.registry.get_capability_registry", return_value=mocks["core.capabilities.registry.get_capability_registry"]),
        patch("core.tool_permissions.get_tool_permissions", return_value=mocks["core.tool_permissions.get_tool_permissions"]),
        patch("core.resilience.get_circuit_breaker", return_value=mocks["core.resilience.get_circuit_breaker"]),
    ):
        mock_exec_policy.return_value.evaluate.return_value = fake_decision
        result = executor.execute("shell_command", {"cmd": "ls", "mission_id": "test-approval"})
    assert result.get("blocked_by_policy") is True
    assert "blocked_by_policy" in result.get("error", "")


def test_execution_policy_blocked_blocks_tool():
    """ExecutionPolicy returning BLOCKED must block the tool call."""
    executor = get_tool_executor()
    mocks = _allowing_permission_check()
    fake_decision = MagicMock()
    fake_decision.decision = Decision.BLOCKED
    fake_decision.reason = "auto_critical_action_blocked"
    with (
        patch("core.execution_policy.get_execution_policy") as mock_exec_policy,
        patch("core.policy_engine.get_policy_engine", return_value=_mk_policy_mock(allowed=True)),
        patch("core.capabilities.registry.get_capability_registry", return_value=mocks["core.capabilities.registry.get_capability_registry"]),
        patch("core.tool_permissions.get_tool_permissions", return_value=mocks["core.tool_permissions.get_tool_permissions"]),
        patch("core.resilience.get_circuit_breaker", return_value=mocks["core.resilience.get_circuit_breaker"]),
    ):
        mock_exec_policy.return_value.evaluate.return_value = fake_decision
        result = executor.execute("shell_command", {"cmd": "ls", "mission_id": "test-blocked"})
    assert result.get("blocked_by_policy") is True
    assert "blocked_by_policy" in result.get("error", "")
