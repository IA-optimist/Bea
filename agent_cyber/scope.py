from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AuthorizationStatus(str, Enum):
    EXPLICIT = "explicit"
    MISSING = "missing"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_LOCAL_TARGETS = frozenset({"localhost", "127.0.0.1", "::1"})


class CyberScopePolicy(BaseModel):
    scope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str
    requested_by: str
    authorization_status: AuthorizationStatus = AuthorizationStatus.UNKNOWN
    authorization_ref: Optional[str] = None
    targets: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_ports: list[int] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    blocked_hosts: list[str] = Field(default_factory=list)
    blocked_paths: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    max_requests: int = 0
    max_runtime_seconds: int = 300
    rate_limit_per_minute: int = 10
    report_only: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    risk_level: RiskLevel = RiskLevel.LOW
    notes: str = ""

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    @property
    def is_local_only(self) -> bool:
        if not self.targets:
            return True
        return all(
            t in _LOCAL_TARGETS or t.startswith("local:")
            for t in self.targets
        )
