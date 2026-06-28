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

from pydantic import BaseModel, Field


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
    mission_id: str
    agent_id: str
    action_type: ActionType
    payload: dict[str, Any] = Field(default_factory=dict)
    realm: str  # "code" | "research" | "data" | "security" | "docs"
    requested_at: datetime = Field(default_factory=datetime.utcnow)


class ActionResult(BaseModel):
    """Result returned to the agent after the ACI processes a request."""

    action_id: str
    status: Literal["success", "error", "blocked", "approval_required"]
    output: Any = None
    error: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    audit_ref: str | None = None
    duration_ms: int = 0

    @classmethod
    def blocked(cls, action_id: str, reason: str) -> "ActionResult":
        return cls(action_id=action_id, status="blocked", error=reason)

    @classmethod
    def approval_required(cls, action_id: str, reason: str) -> "ActionResult":
        return cls(action_id=action_id, status="approval_required", error=reason)

    @classmethod
    def error_result(cls, action_id: str, reason: str) -> "ActionResult":
        return cls(action_id=action_id, status="error", error=reason)

    @classmethod
    def success(cls, action_id: str, output: Any, artifacts: list[str] | None = None, duration_ms: int = 0) -> "ActionResult":
        return cls(
            action_id=action_id,
            status="success",
            output=output,
            artifacts=artifacts or [],
            duration_ms=duration_ms,
        )
