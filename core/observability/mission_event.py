"""Lightweight structured event for mission observability.

Captures provider/model/duration/error without exposing prompts or secrets.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from core.observability.redactor import redact_dict


@dataclass
class MissionEvent:
    mission_id: str
    mission_type: str = "unknown"
    status: str = "pending"
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    agent_used: Optional[str] = None
    duration_ms: Optional[float] = None
    error_category: Optional[str] = None
    artifact_status: Optional[str] = None
    validation_status: Optional[str] = None
    rate_limited: bool = False
    fallback_used: bool = False
    timestamp: float = field(default_factory=time.time)
    _start: float = field(default_factory=time.time, repr=False)

    def complete(self, *, status: str, error_category: str | None = None) -> None:
        self.status = status
        self.error_category = error_category
        self.duration_ms = round((time.time() - self._start) * 1000, 1)

    def to_log_dict(self) -> dict:
        """Return redacted dict safe for structured logging. Never includes prompts."""
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        return redact_dict(d)
