"""
agent_runtime/actions.py — Typed action models for the ACI layer.

ActionRequest and ActionResult are the only way agents communicate with the
execution layer.  No direct shell, no direct filesystem, no direct network.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ActionType(str, Enum):
    """All actions an agent may request.  Unknown actions are denied."""

    READ_FILE = "read_file"
    LIST_FILES = "list_files"
    SEARCH_TEXT = "search_text"
    SEARCH_SYMBOL = "search_symbol"
    APPLY_PATCH = "apply_patch"
    RUN_TESTS = "run_tests"
    RUN_LINTER = "run_linter"
    RUN_TYPECHECK = "run_typecheck"
    RUN_SECURITY_SCAN = "run_security_scan"
    CREATE_BRANCH = "create_branch"
    CREATE_PR_DRAFT = "create_pr_draft"
    WRITE_REPORT = "write_report"


class ActionRequest(BaseModel):
    """A single action requested by an agent."""

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mission_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    action_type: ActionType
    payload: dict[str, Any] = Field(default_factory=dict)
    realm: str = Field(min_length=1)  # "code" | "research" | "data" | "security" | "docs"
    idempotency_key: str | None = None
    requested_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("realm")
    @classmethod
    def normalize_realm(cls, value: str) -> str:
        return value.strip().lower()


class ActionResult(BaseModel):
    """Result returned to the agent after the ACI processes a request."""

    action_id: str
    status: Literal["success", "error", "blocked", "approval_required"]
    output: Any = None
    error: str | None = None
    error_type: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    audit_ref: str | None = None
    duration_ms: int = 0

    @model_validator(mode="after")
    def redact_and_bound(self) -> "ActionResult":
        self.output = redact_value(self.output)
        self.error = _bound_text(redact_text(self.error), 2000)
        return self

    @classmethod
    def blocked(cls, action_id: str, reason: str) -> "ActionResult":
        return cls(action_id=action_id, status="blocked", error=reason, error_type="policy_block")

    @classmethod
    def approval_required(cls, action_id: str, reason: str) -> "ActionResult":
        return cls(action_id=action_id, status="approval_required", error=reason, error_type="approval_required")

    @classmethod
    def error_result(cls, action_id: str, reason: str) -> "ActionResult":
        return cls(action_id=action_id, status="error", error=reason, error_type="handler_error")

    @classmethod
    def success(cls, action_id: str, output: Any, artifacts: list[str] | None = None, duration_ms: int = 0) -> "ActionResult":
        return cls(
            action_id=action_id,
            status="success",
            output=output,
            artifacts=artifacts or [],
            duration_ms=duration_ms,
        )


_SECRET_PATTERNS = (
    (r"sk-or-v1-[A-Za-z0-9_\-]{8,}", "[REDACTED]"),
    (r"(?i)(token|api_key|apikey|authorization|password|secret|cookie)=\S+", r"\1=[REDACTED]"),
    (r"(?i)(bearer)\s+[A-Za-z0-9_\-\.]{8,}", r"\1 [REDACTED]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
)


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    import re

    text = value
    for pattern, repl in _SECRET_PATTERNS:
        text = re.sub(pattern, repl, text, flags=re.DOTALL)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _bound_text(redact_text(value), 50_000)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(secret in str(key).lower() for secret in ("token", "api_key", "authorization", "password", "secret", "cookie")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def _bound_text(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"
