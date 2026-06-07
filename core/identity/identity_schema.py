"""
BEA MAX — Identity Schema
================================
Core data models for digital identities.

Each identity represents a single account/credential bundle
on a specific service (Gmail, Stripe, GitHub, etc.).

Identities link to secrets in the Vault — never store credentials directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


# ── Identity Types ──

class IdentityType(str, Enum):
    EMAIL_ACCOUNT = "email_account"
    API_ACCOUNT = "api_account"
    SAAS_ACCOUNT = "saas_account"
    DOMAIN_ACCOUNT = "domain_account"
    SOCIAL_ACCOUNT = "social_account"
    DEVELOPER_ACCOUNT = "developer_account"
    PAYMENT_ACCOUNT = "payment_account"


class IdentityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    PENDING = "pending"       # Awaiting creation/approval


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class SessionState(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    NONE = "none"


# ── Core Identity ──

@dataclass
class Identity:
    """
    A digital identity on a specific service.
    Credentials are stored in the Secret Vault — only secret_ids referenced here.
    """
    identity_id: str
    identity_type: str              # IdentityType value
    display_name: str
    provider: str                   # e.g., "gmail", "stripe", "github"
    email: str = ""
    username: str = ""
    environment: str = "prod"       # dev/staging/prod
    workspace_id: str = ""          # Project or workspace this belongs to

    # Vault links (secret IDs, NOT actual secrets)
    linked_secrets: list[str] = field(default_factory=list)

    # Service connections
    linked_domains: list[str] = field(default_factory=list)
    linked_services: list[str] = field(default_factory=list)

    # Risk & status
    risk_level: str = "medium"      # low/medium/high/critical
    status: str = "active"          # IdentityStatus value
    session_state: str = "none"     # SessionState value

    # Metadata
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used_at: float | None = None
    last_rotated_at: float | None = None

    def to_dict(self) -> dict:
        """Safe dict — no secret values, only IDs."""
        return {
            "id": self.identity_id,
            "type": self.identity_type,
            "name": self.display_name,
            "provider": self.provider,
            "email": self.email,
            "username": self.username,
            "environment": self.environment,
            "workspace": self.workspace_id,
            "linked_secrets": len(self.linked_secrets),
            "linked_domains": self.linked_domains,
            "linked_services": self.linked_services,
            "risk_level": self.risk_level,
            "status": self.status,
            "session": self.session_state,
            "tags": self.tags,
            "created": self.created_at,
            "last_used": self.last_used_at,
            "last_rotated": self.last_rotated_at,
        }

    @property
    def is_active(self) -> bool:
        return self.status == IdentityStatus.ACTIVE.value

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in ("high", "critical")

    def mark_used(self) -> None:
        self.last_used_at = time.time()
        self.updated_at = time.time()


# ── Linked Secret Reference ──

@dataclass
class SecretLink:
    """Reference to a secret in the Vault, with role context."""
    secret_id: str
    secret_role: str            # e.g., "password", "api_key", "oauth_token", "totp_seed"
    identity_id: str
    provider: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "secret_id": self.secret_id,
            "role": self.secret_role,
            "identity_id": self.identity_id,
            "provider": self.provider,
        }
