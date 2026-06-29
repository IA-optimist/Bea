"""
tests/agent_runtime/test_aci.py — ACI deny-by-default behaviour tests.
"""
from __future__ import annotations

import pytest

from agent_runtime.actions import ActionRequest, ActionResult, ActionType
from agent_runtime.policy import CommandPolicy, RiskLevel
from agent_runtime.registry import ACIActionRegistry
from agent_runtime.executor import ACIExecutor


# ── Helpers ───────────────────────────────────────────────────────────────────

def _req(action_type: ActionType, payload: dict | None = None) -> ActionRequest:
    return ActionRequest(
        mission_id="test-mission",
        agent_id="test-agent",
        action_type=action_type,
        payload=payload or {},
        realm="code",
    )


def _policy_allow_all() -> CommandPolicy:
    return CommandPolicy(
        allowed_actions=set(ActionType),
        allowed_paths=["/workspace", "workspace"],
        require_approval_above_risk=RiskLevel.CRITICAL,  # never block in tests
    )


def _full_caps() -> set[str]:
    return {"read", "write", "execute", "sandbox", "git", "github"}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestACIBlocking:
    def test_unknown_action_blocked(self):
        """An action not in the registry must be blocked (deny-by-default)."""
        empty_registry = ACIActionRegistry()  # nothing registered
        executor = ACIExecutor(registry=empty_registry, agent_capabilities=_full_caps())
        req = _req(ActionType.READ_FILE)
        result = executor.execute(req, _policy_allow_all())
        assert result.status == "blocked"
        assert "not registered" in (result.error or "")

    def test_missing_capability_blocked(self):
        """Agent without required capability must be blocked."""
        from agent_runtime.registry import get_default_registry
        executor = ACIExecutor(
            registry=get_default_registry(),
            agent_capabilities=set(),  # no capabilities at all
        )
        req = _req(ActionType.READ_FILE)
        result = executor.execute(req, _policy_allow_all())
        assert result.status == "blocked"
        assert "capability" in (result.error or "").lower()

    def test_policy_denied_action_blocked(self):
        """Action explicitly denied by policy must be blocked."""
        from agent_runtime.registry import get_default_registry
        policy = CommandPolicy(
            denied_actions={ActionType.READ_FILE},
            allowed_paths=["/workspace"],
            require_approval_above_risk=RiskLevel.CRITICAL,
        )
        executor = ACIExecutor(registry=get_default_registry(), agent_capabilities=_full_caps())
        req = _req(ActionType.READ_FILE)
        result = executor.execute(req, policy)
        assert result.status == "blocked"

    def test_dangerous_path_blocked(self):
        """Sensitive paths must be blocked without explicit allow."""
        from agent_runtime.registry import get_default_registry
        policy = CommandPolicy(
            allowed_actions={ActionType.READ_FILE},
            allowed_paths=["workspace"],  # does NOT include core/security
            require_approval_above_risk=RiskLevel.CRITICAL,
        )
        executor = ACIExecutor(registry=get_default_registry(), agent_capabilities=_full_caps())
        req = _req(ActionType.READ_FILE, payload={"path": "core/security/rbac.py"})
        result = executor.execute(req, policy)
        assert result.status == "blocked"
        assert "sensitive" in (result.error or "").lower()

    def test_risky_action_requires_approval(self):
        """HIGH risk action must require approval when threshold is MEDIUM."""
        from agent_runtime.registry import get_default_registry
        policy = CommandPolicy(
            allowed_actions=set(ActionType),
            allowed_paths=["/workspace"],
            require_approval_above_risk=RiskLevel.MEDIUM,  # block HIGH+
        )
        executor = ACIExecutor(registry=get_default_registry(), agent_capabilities=_full_caps())
        req = _req(ActionType.APPLY_PATCH, payload={"path": "/workspace/foo.py"})
        result = executor.execute(req, policy)
        assert result.status == "approval_required"

    def test_read_file_allowed_in_scope(self):
        """READ_FILE in an allowed path with proper capabilities must succeed (or at least not block)."""
        from agent_runtime.registry import get_default_registry
        policy = CommandPolicy(
            allowed_actions={ActionType.READ_FILE},
            allowed_paths=["workspace"],
            require_approval_above_risk=RiskLevel.HIGH,
        )
        executor = ACIExecutor(registry=get_default_registry(), agent_capabilities={"read"})
        req = _req(ActionType.READ_FILE, payload={"path": "workspace/notes.txt"})
        result = executor.execute(req, policy)
        # Stub handler returns error (not implemented), but must NOT be blocked
        assert result.status in ("success", "error"), f"Expected not blocked, got: {result.status} — {result.error}"

    def test_apply_patch_outside_scope_fails(self):
        """APPLY_PATCH targeting a path outside allowed_paths must be blocked."""
        from agent_runtime.registry import get_default_registry
        policy = CommandPolicy(
            allowed_actions={ActionType.APPLY_PATCH},
            allowed_paths=["workspace/patches"],
            require_approval_above_risk=RiskLevel.CRITICAL,
        )
        executor = ACIExecutor(registry=get_default_registry(), agent_capabilities=_full_caps())
        req = _req(ActionType.APPLY_PATCH, payload={"target": "/etc/passwd"})
        result = executor.execute(req, policy)
        assert result.status == "blocked"

    def test_run_tests_respects_policy(self):
        """RUN_TESTS with risk threshold LOW must require approval (MEDIUM > LOW)."""
        from agent_runtime.registry import get_default_registry
        policy = CommandPolicy(
            allowed_actions={ActionType.RUN_TESTS},
            allowed_paths=["/workspace"],
            require_approval_above_risk=RiskLevel.LOW,  # MEDIUM > LOW → approval
        )
        executor = ACIExecutor(registry=get_default_registry(), agent_capabilities=_full_caps())
        req = _req(ActionType.RUN_TESTS)
        result = executor.execute(req, policy)
        assert result.status == "approval_required"
