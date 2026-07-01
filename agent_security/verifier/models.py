from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class ActionType(str, Enum):
    EXEC_COMMAND = "exec_command"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK_REQUEST = "network_request"
    API_CALL = "api_call"
    SEND_MESSAGE = "send_message"
    SELF_MODIFICATION = "self_modification"
    SPAWN_AGENT = "spawn_agent"
    MODIFY_MEMORY = "modify_memory"
    MODIFY_SECURITY_CONFIG = "modify_security_config"


class EffectScope(str, Enum):
    LOCAL_READONLY = "local_readonly"
    LOCAL_WRITE = "local_write"
    LOCAL_SENSITIVE = "local_sensitive"
    EXTERNAL_READONLY = "external_readonly"
    EXTERNAL_WRITE = "external_write"
    SYSTEM = "system"


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerifierVerdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    HOLD = "hold"
    HALT = "halt"


class ActionIntent(BaseModel):
    """Structured action intent. Never contains persuasive text in policy-facing fields."""

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    actor_id: str
    action_type: ActionType
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    declared_scope: EffectScope
    risk_hint: Optional[RiskLevel] = None  # caller-provided, NEVER trusted by policy
    # metadata is for audit ONLY — never read by policy logic
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("actor_id")
    @classmethod
    def actor_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("actor_id cannot be empty")
        return v

    @field_validator("target")
    @classmethod
    def target_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("target cannot be empty")
        return v

    model_config = {"frozen": True}  # intents are immutable once created


class VerifierDecision(BaseModel):
    """Returned by policy evaluation. Immutable."""

    verdict: VerifierVerdict
    reason: str
    action_id: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_human_approval: bool = False
    audit_ref: Optional[str] = None

    model_config = {"frozen": True}
