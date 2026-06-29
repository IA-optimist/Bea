"""
agent_runtime/policy.py - command and sandbox policies for the ACI.

RiskLevel determines whether an action requires approval or is blocked.
CommandPolicy controls which actions an agent may perform in a session.
SandboxPolicy controls isolation for dangerous actions.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent_runtime.actions import ActionType


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


ACTION_RISK: dict[ActionType, RiskLevel] = {
    ActionType.READ_FILE: RiskLevel.SAFE,
    ActionType.LIST_FILES: RiskLevel.SAFE,
    ActionType.SEARCH_TEXT: RiskLevel.SAFE,
    ActionType.SEARCH_SYMBOL: RiskLevel.SAFE,
    ActionType.WRITE_REPORT: RiskLevel.LOW,
    ActionType.RUN_LINTER: RiskLevel.LOW,
    ActionType.RUN_TYPECHECK: RiskLevel.LOW,
    ActionType.RUN_SECURITY_SCAN: RiskLevel.LOW,
    ActionType.RUN_TESTS: RiskLevel.MEDIUM,
    ActionType.APPLY_PATCH: RiskLevel.HIGH,
    ActionType.CREATE_BRANCH: RiskLevel.MEDIUM,
    ActionType.CREATE_PR_DRAFT: RiskLevel.HIGH,
}


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
    allowed_realms: set[str] = Field(default_factory=set)
    allowed_paths: list[str] = Field(default_factory=list)
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
        """Check whether a path is within explicitly allowed scope."""
        if not self.allowed_paths:
            return False
        target = _resolve_path(path)
        for denied in self.denied_paths:
            if _is_within(target, _resolve_path(denied)):
                return False
        return any(_is_within(target, _resolve_path(allowed)) for allowed in self.allowed_paths)

    def realm_allowed(self, realm: str) -> bool:
        if not self.allowed_realms:
            return True
        allowed = {item.lower().strip() for item in self.allowed_realms}
        return realm.lower().strip() in allowed


class SandboxPolicy(BaseModel):
    """Isolation constraints for dangerous action execution."""

    filesystem_scope: list[str] = Field(default_factory=list)
    network: Literal["none", "allowlist", "full"] = "none"
    secrets_access: bool = False
    timeout: int = 120
    allowed_commands: frozenset[str] = frozenset({"pytest", "ruff", "mypy", "python"})

    model_config = {"arbitrary_types_allowed": True}


def _resolve_path(path: str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_within(target: Path, allowed_root: Path) -> bool:
    try:
        target.relative_to(allowed_root)
        return True
    except ValueError:
        return False
