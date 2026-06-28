"""
agent_runtime/registry.py — ACI Action Registry.

Deny-by-default: only registered actions with declared capabilities may run.
Registration maps ActionType → (handler_fn, required_capabilities, risk_level).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Any

import structlog

from agent_runtime.actions import ActionType, ActionRequest, ActionResult
from agent_runtime.policy import RiskLevel

log = structlog.get_logger("bea.aci.registry")


@dataclass
class ActionRegistration:
    action_type: ActionType
    handler: Callable[[ActionRequest], ActionResult]
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    risk_level: RiskLevel = RiskLevel.SAFE
    description: str = ""


class ACIActionRegistry:
    """
    Central registry for ACI actions.

    Default behaviour: DENY. An action must be explicitly registered
    and the calling agent must have the required capabilities.
    """

    def __init__(self) -> None:
        self._registry: dict[ActionType, ActionRegistration] = {}

    def register(
        self,
        action_type: ActionType,
        handler: Callable[[ActionRequest], ActionResult],
        *,
        required_capabilities: frozenset[str] | set[str] = frozenset(),
        risk_level: RiskLevel = RiskLevel.SAFE,
        description: str = "",
    ) -> None:
        self._registry[action_type] = ActionRegistration(
            action_type=action_type,
            handler=handler,
            required_capabilities=frozenset(required_capabilities),
            risk_level=risk_level,
            description=description,
        )
        log.debug("aci_action_registered", action=action_type.value, risk=risk_level.value)

    def get(self, action_type: ActionType) -> ActionRegistration | None:
        return self._registry.get(action_type)

    def is_registered(self, action_type: ActionType) -> bool:
        return action_type in self._registry

    def check_capabilities(
        self,
        action_type: ActionType,
        agent_capabilities: set[str],
    ) -> tuple[bool, str | None]:
        """
        Returns (allowed, reason).
        reason is None when allowed.
        """
        reg = self.get(action_type)
        if reg is None:
            return False, f"action '{action_type.value}' is not registered (deny-by-default)"
        missing = reg.required_capabilities - agent_capabilities
        if missing:
            return False, f"agent missing capabilities: {sorted(missing)}"
        return True, None

    def list_actions(self) -> list[dict[str, Any]]:
        return [
            {
                "action": r.action_type.value,
                "risk": r.risk_level.value,
                "required_capabilities": sorted(r.required_capabilities),
                "description": r.description,
            }
            for r in self._registry.values()
        ]


# ── Module-level default registry (populated lazily) ──────────────────────────
_default_registry: ACIActionRegistry | None = None


def get_default_registry() -> ACIActionRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = _build_default_registry()
    return _default_registry


def _build_default_registry() -> ACIActionRegistry:
    """Build the default registry with stub handlers for all ActionTypes."""
    from agent_runtime.results import not_implemented_handler
    reg = ACIActionRegistry()
    # Safe read-only actions
    for at in (ActionType.READ_FILE, ActionType.LIST_FILES,
               ActionType.SEARCH_TEXT, ActionType.SEARCH_SYMBOL):
        reg.register(at, not_implemented_handler,
                     required_capabilities={"read"},
                     risk_level=RiskLevel.SAFE,
                     description=f"Read-only: {at.value}")
    # Write/exec actions
    reg.register(ActionType.APPLY_PATCH, not_implemented_handler,
                 required_capabilities={"write", "sandbox"},
                 risk_level=RiskLevel.HIGH,
                 description="Apply unified diff patch inside sandbox")
    reg.register(ActionType.RUN_TESTS, not_implemented_handler,
                 required_capabilities={"execute", "sandbox"},
                 risk_level=RiskLevel.MEDIUM,
                 description="Run pytest inside sandbox")
    reg.register(ActionType.RUN_LINTER, not_implemented_handler,
                 required_capabilities={"execute"},
                 risk_level=RiskLevel.LOW,
                 description="Run ruff linter")
    reg.register(ActionType.RUN_TYPECHECK, not_implemented_handler,
                 required_capabilities={"execute"},
                 risk_level=RiskLevel.LOW,
                 description="Run mypy type checker")
    reg.register(ActionType.RUN_SECURITY_SCAN, not_implemented_handler,
                 required_capabilities={"execute"},
                 risk_level=RiskLevel.LOW,
                 description="Run bandit security scan")
    reg.register(ActionType.CREATE_BRANCH, not_implemented_handler,
                 required_capabilities={"git"},
                 risk_level=RiskLevel.MEDIUM,
                 description="Create git branch or worktree")
    reg.register(ActionType.CREATE_PR_DRAFT, not_implemented_handler,
                 required_capabilities={"git", "github"},
                 risk_level=RiskLevel.HIGH,
                 description="Create GitHub PR draft — never auto-merge")
    reg.register(ActionType.WRITE_REPORT, not_implemented_handler,
                 required_capabilities={"write"},
                 risk_level=RiskLevel.LOW,
                 description="Write structured report to workspace")
    return reg
