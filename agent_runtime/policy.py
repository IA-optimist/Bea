"""
agent_runtime/policy.py — Command and sandbox policies for the ACI.

RiskLevel determines whether an action requires approval or is auto-blocked.
CommandPolicy controls which actions an agent may perform in a session.
SandboxPolicy controls isolation for dangerous actions.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from agent_runtime.actions import ActionType


class RiskLevel(str, Enum):
    SAFE = "safe"         # read-only, no side effects → auto-approve
    LOW = "low"           # minor side effects → auto-approve if allowed
    MEDIUM = "medium"     # moderate side effects → warn + log
    HIGH = "high"         # significant side effects → approval required
    CRITICAL = "critical" # irreversible / dangerous → always blocked unless explicit


# Default risk classification per ActionType
ACTION_RISK: dict[ActionType, RiskLevel] = {
    ActionType.READ_FILE:        RiskLevel.SAFE,
    ActionType.LIST_FILES:       RiskLevel.SAFE,
    ActionType.SEARCH_TEXT:      RiskLevel.SAFE,
    ActionType.SEARCH_SYMBOL:    RiskLevel.SAFE,
    ActionType.WRITE_REPORT:     RiskLevel.LOW,
    ActionType.RUN_LINTER:       RiskLevel.LOW,
    ActionType.RUN_TYPECHECK:    RiskLevel.LOW,
    ActionType.RUN_SECURITY_SCAN: RiskLevel.LOW,
    ActionType.RUN_TESTS:        RiskLevel.MEDIUM,
    ActionType.APPLY_PATCH:      RiskLevel.HIGH,
    ActionType.CREATE_BRANCH:    RiskLevel.MEDIUM,
    ActionType.CREATE_PR_DRAFT:  RiskLevel.HIGH,
}


# Sensitive path prefixes — accessing these outside an explicit allow requires approval
SENSITIVE_PATH_PREFIXES: tuple[str, ...] = (
    ".env",
    "secrets",
    "core/security",
    "core/tool_executor",
    "core/meta_orchestrator",
    "kernel/improvement",
    "api/_deps",
)


def is_sensitive_path(path: str) -> bool:
    """Return True if path touches a sensitive area."""
    p = path.replace("\\", "/").lstrip("/")
    return any(p.startswith(prefix) or p == prefix for prefix in SENSITIVE_PATH_PREFIXES)


class CommandPolicy(BaseModel):
    """What an agent is allowed to do in a given execution context."""

    allowed_actions: set[ActionType] = Field(default_factory=set)
    denied_actions: set[ActionType] = Field(default_factory=set)
    allowed_paths: list[str] = Field(default_factory=list)  # empty = deny all writes
    denied_paths: list[str] = Field(default_factory=list)
    max_runtime_seconds: int = 60
    max_output_size: int = 50_000
    require_approval_above_risk: RiskLevel = RiskLevel.HIGH

    def allows(self, action: ActionType) -> bool:
        if action in self.denied_actions:
            return False
        if self.allowed_actions and action not in self.allowed_actions:
            return False
        return True

    def path_allowed(self, path: str) -> bool:
        """Check whether a path is within allowed scope."""
        if not self.allowed_paths:
            return False  # deny-by-default: no explicit allow → denied
        p = path.replace("\\", "/")
        return any(p.startswith(a.replace("\\", "/")) for a in self.allowed_paths)


class SandboxPolicy(BaseModel):
    """Isolation constraints for dangerous action execution."""

    filesystem_scope: list[str] = Field(default_factory=list)
    network: Literal["none", "allowlist", "full"] = "none"
    secrets_access: bool = False  # always False in production
    timeout: int = 120
    allowed_commands: frozenset[str] = frozenset({"pytest", "ruff", "mypy", "python"})

    model_config = {"arbitrary_types_allowed": True}
