"""Pydantic request schemas for mission routes."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
class TaskRequest(BaseModel):
    input: str
    mode:  str = "auto"

    @field_validator("input", mode="before")
    @classmethod
    def input_not_empty(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("Mission input cannot be empty")
        if len(v) > 50000:
            raise ValueError("Mission input too long (max 50000 chars)")
        # Sanitization anti-prompt injection
        from core.security.input_sanitizer import sanitize_user_input
        result = sanitize_user_input(v, strict=False)
        if result.warnings:
            import structlog as _sl
            _sl.get_logger().warning("mission_input_sanitized", warnings=result.warnings)
        return result.value


class ModeRequest(BaseModel):
    mode:       str = "SUPERVISED"
    changed_by: str = "api"


class TriggerRequest(BaseModel):
    mission: str = ""


class AbortRequest(BaseModel):
    reason: str = ""


class MissionSubmitRequest(BaseModel):
    goal: str = Field(default="", min_length=0, max_length=8000)
    mode: str = "auto"


class ApproveRequest(BaseModel):
    note: str = "Approved by human supervisor"
