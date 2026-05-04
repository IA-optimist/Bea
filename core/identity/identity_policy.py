"""
JARVIS MAX — Identity Policy Engine
=======================================
Access control and governance for identity operations.

Enforces:
- RBAC (admin/operator/viewer/agent)
- Environment isolation (dev secrets ≠ prod secrets)
- High-risk identity approval gates
- Agent-level identity access control
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


# ── RBAC ──

IDENTITY_PERMISSIONS = {
    "admin":    {"create", "update", "delete", "use", "reveal", "list", "link", "rotate", "revoke", "logs"},
    "operator": {"use", "list", "link"},
    "viewer":   {"list"},
    "agent":    {"use"},
}


def check_identity_permission(role: str, action: str) -> bool:
    """Check if a role has permission for an identity action."""
    perms = IDENTITY_PERMISSIONS.get(role, set())
    return action in perms


# ── Policy ──

@dataclass
class IdentityPolicy:
    """Policy governing identity access and behavior."""
    allowed_agents: list[str] = field(default_factory=lambda: ["*"])
    allowed_environments: list[str] = field(default_factory=lambda: ["dev", "staging", "prod"])
    requires_approval: bool = False
    max_uses_per_hour: int = 200
    auto_rotate_days: int = 0     # 0 = no auto-rotation
    session_timeout_s: int = 3600  # 1 hour
    allow_cross_env: bool = False  # Can dev identity be used in prod context?

    def to_dict(self) -> dict:
        return {
            "allowed_agents": self.allowed_agents,
            "environments": self.allowed_environments,
            "requires_approval": self.requires_approval,
            "rate_limit": self.max_uses_per_hour,
            "auto_rotate_days": self.auto_rotate_days,
            "session_timeout": self.session_timeout_s,
            "cross_env": self.allow_cross_env,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IdentityPolicy":
        return cls(
            allowed_agents=data.get("allowed_agents", ["*"]),
            allowed_environments=data.get("environments", ["dev", "staging", "prod"]),
            requires_approval=data.get("requires_approval", False),
            max_uses_per_hour=data.get("rate_limit", 200),
            auto_rotate_days=data.get("auto_rotate_days", 0),
            session_timeout_s=data.get("session_timeout", 3600),
            allow_cross_env=data.get("cross_env", False),
        )


class IdentityPolicyEngine:
    """Evaluates identity access requests."""

    def __init__(self):
        self._use_counts: dict[str, list[float]] = {}

    def check_use(
        self,
        identity_id: str,
        identity_status: str,
        identity_env: str,
        policy: IdentityPolicy,
        agent_name: str,
        request_env: str,
        role: str = "operator",
    ) -> tuple[bool, str]:
        """Check if an agent can use an identity."""
        # RBAC
        if not check_identity_permission(role, "use"):
            return False, f"Role '{role}' cannot use identities"

        # Status
        if identity_status != "active":
            return False, f"Identity status is '{identity_status}', not active"

        # Agent allowlist
        if "*" not in policy.allowed_agents and agent_name not in policy.allowed_agents:
            return False, f"Agent '{agent_name}' not allowed"

        # Environment check
        if not policy.allow_cross_env and identity_env != request_env:
            return False, f"Environment mismatch: identity={identity_env}, request={request_env}"

        if request_env not in policy.allowed_environments:
            return False, f"Environment '{request_env}' not allowed"

        # Rate limit
        if not self._check_rate(identity_id, policy.max_uses_per_hour):
            return False, f"Rate limit exceeded ({policy.max_uses_per_hour}/hour)"

        return True, "allowed"

    def check_create(
        self,
        risk_level: str,
        requires_approval: bool,
        role: str = "admin",
    ) -> tuple[bool, str]:
        """Check if identity creation is allowed."""
        if not check_identity_permission(role, "create"):
            return False, f"Role '{role}' cannot create identities"

        if requires_approval and risk_level in ("high", "critical"):
            return True, "allowed_with_approval"

        return True, "allowed"

    def _check_rate(self, identity_id: str, max_per_hour: int) -> bool:
        now = time.time()
        window = now - 3600
        if identity_id not in self._use_counts:
            self._use_counts[identity_id] = []
        self._use_counts[identity_id] = [
            t for t in self._use_counts[identity_id] if t > window
        ]
        if len(self._use_counts[identity_id]) >= max_per_hour:
            return False
        self._use_counts[identity_id].append(now)
        return True
