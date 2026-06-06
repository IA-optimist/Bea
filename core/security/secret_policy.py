"""
JARVIS MAX — Secret Access Policy Engine
============================================
Controls WHO can access WHICH secrets and HOW.

Each secret has a policy defining:
- allowed_agents: which agents can use it
- allowed_domains: which target domains the secret can be sent to
- risk_level: low/medium/high/critical
- reveal_policy: never/admin_only/on_approval
- auto_use_allowed: whether agents can use without per-request approval
- max_uses_per_hour: rate limit
- expires_at: optional expiry timestamp

RBAC roles:
- admin: full access (create, read, update, delete, reveal, use)
- operator: use + list metadata only
- viewer: list metadata only (no values, no use)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RevealPolicy(str, Enum):
    NEVER = "never"
    ADMIN_ONLY = "admin_only"
    ON_APPROVAL = "on_approval"


class SecretType(str, Enum):
    CREDENTIAL = "credential"
    API_KEY = "api_key"
    COOKIE = "cookie"
    TOTP = "totp"
    PRIVATE_KEY = "private_key"
    TOKEN = "token"  # nosec B105 — enum category label


class PolicyViolation(Exception):
    """Raised when a secret access violates policy."""
    pass


@dataclass
class SecretPolicy:
    """Access policy for a single secret."""
    allowed_agents: list[str] = field(default_factory=lambda: ["*"])  # * = any
    allowed_domains: list[str] = field(default_factory=lambda: ["*"])
    risk_level: str = "medium"
    reveal_policy: str = "admin_only"
    auto_use_allowed: bool = True
    max_uses_per_hour: int = 100
    expires_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "allowed_agents": self.allowed_agents,
            "allowed_domains": self.allowed_domains,
            "risk_level": self.risk_level,
            "reveal_policy": self.reveal_policy,
            "auto_use": self.auto_use_allowed,
            "rate_limit": self.max_uses_per_hour,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SecretPolicy":
        return cls(
            allowed_agents=data.get("allowed_agents", ["*"]),
            allowed_domains=data.get("allowed_domains", ["*"]),
            risk_level=data.get("risk_level", "medium"),
            reveal_policy=data.get("reveal_policy", "admin_only"),
            auto_use_allowed=data.get("auto_use", True),
            max_uses_per_hour=data.get("rate_limit", 100),
            expires_at=data.get("expires_at"),
        )


@dataclass
class SecretMetadata:
    """Non-sensitive metadata for a secret."""
    secret_id: str
    name: str
    secret_type: str = "api_key"
    description: str = ""
    domain: str = ""         # Primary domain (e.g., "openai.com")
    policy: SecretPolicy = field(default_factory=SecretPolicy)
    version: int = 1
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used_at: float | None = None
    revoked: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.secret_id, "name": self.name,
            "type": self.secret_type, "description": self.description[:200],
            "domain": self.domain, "version": self.version,
            "policy": self.policy.to_dict(),
            "created": self.created_at, "updated": self.updated_at,
            "last_used": self.last_used_at, "revoked": self.revoked,
        }


# ── RBAC Permission Checks ──

ROLE_PERMISSIONS = {
    "admin":    {"create", "update", "delete", "use", "reveal", "list", "logs", "rotate", "revoke"},
    "operator": {"use", "list"},
    "viewer":   {"list"},
}


def check_permission(role: str, action: str) -> bool:
    """Check if a role has permission for an action."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return action in perms


# ── Policy Engine ──

class PolicyEngine:
    """Evaluates access requests against secret policies."""

    def __init__(self):
        self._use_counts: dict[str, list[float]] = {}  # secret_id → [timestamps]

    def check_use(
        self,
        secret_meta: SecretMetadata,
        agent_name: str,
        target_domain: str,
        role: str = "operator",
    ) -> tuple[bool, str]:
        """
        Check if an agent can USE a secret for a specific domain.
        Returns (allowed, reason).
        """
        policy = secret_meta.policy

        # Check revocation
        if secret_meta.revoked:
            return False, "Secret has been revoked"

        # Check expiry
        if policy.expires_at and time.time() > policy.expires_at:
            return False, "Secret has expired"

        # Check RBAC
        if not check_permission(role, "use"):
            return False, f"Role '{role}' lacks 'use' permission"

        # Check auto-use
        if not policy.auto_use_allowed and role != "admin":
            return False, "Auto-use disabled — requires admin approval"

        # Check agent allowlist
        if "*" not in policy.allowed_agents and agent_name not in policy.allowed_agents:
            return False, f"Agent '{agent_name}' not in allowed list"

        # Check domain allowlist
        if "*" not in policy.allowed_domains and target_domain not in policy.allowed_domains:
            return False, f"Domain '{target_domain}' not in allowed list"

        # Rate limit
        if not self._check_rate(secret_meta.secret_id, policy.max_uses_per_hour):
            return False, f"Rate limit exceeded ({policy.max_uses_per_hour}/hour)"

        return True, "allowed"

    def check_reveal(
        self,
        secret_meta: SecretMetadata,
        role: str = "admin",
    ) -> tuple[bool, str]:
        """Check if a secret can be REVEALED (plaintext shown)."""
        if not check_permission(role, "reveal"):
            return False, f"Role '{role}' cannot reveal secrets"

        policy = secret_meta.policy
        if policy.reveal_policy == RevealPolicy.NEVER.value:
            return False, "Reveal policy is NEVER"

        if policy.reveal_policy == RevealPolicy.ADMIN_ONLY.value and role != "admin":
            return False, "Only admin can reveal this secret"

        return True, "allowed"

    def _check_rate(self, secret_id: str, max_per_hour: int) -> bool:
        """Sliding window rate limiter."""
        now = time.time()
        window = now - 3600

        if secret_id not in self._use_counts:
            self._use_counts[secret_id] = []

        # Clean old entries
        self._use_counts[secret_id] = [
            t for t in self._use_counts[secret_id] if t > window
        ]

        if len(self._use_counts[secret_id]) >= max_per_hour:
            return False

        self._use_counts[secret_id].append(now)
        return True
