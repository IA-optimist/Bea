"""
core/tools_operational/tool_schema.py — Schema for external operational tools.

An operational tool represents an external system Bea can invoke:
webhooks, APIs, automation platforms, notification services, etc.

Each tool declares its contract: inputs, outputs, risk, secrets, retry policy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RetryPolicy:
    """Retry policy for tool execution."""
    max_retries: int = 0
    backoff_seconds: float = 2.0
    retry_on_status: list[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])
    enabled: bool = False

    def to_dict(self) -> dict:
        return {
            "max_retries": self.max_retries,
            "backoff_seconds": self.backoff_seconds,
            "retry_on_status": self.retry_on_status,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RetryPolicy:
        return cls(
            max_retries=d.get("max_retries", 0),
            backoff_seconds=d.get("backoff_seconds", 2.0),
            retry_on_status=d.get("retry_on_status", [429, 500, 502, 503, 504]),
            enabled=d.get("enabled", False),
        )


@dataclass
class OperationalTool:
    """
    An external tool that Bea can invoke as part of business workflows.

    Unlike internal agent tools (read_file, shell), operational tools
    represent external system integrations with real-world side effects.
    """
    id: str
    name: str = ""
    description: str = ""
    category: str = ""  # webhook, api, automation, notification, data
    risk_level: str = "low"  # low, medium, high, critical
    requires_approval: bool = False
    required_secrets: list[str] = field(default_factory=list)
    required_configs: list[str] = field(default_factory=list)
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: int = 30  # seconds
    tags: list[str] = field(default_factory=list)
    version: str = "1.0"
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "required_secrets": self.required_secrets,
            "required_configs": self.required_configs,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "retry_policy": self.retry_policy.to_dict(),
            "timeout": self.timeout,
            "tags": self.tags,
            "version": self.version,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> OperationalTool:
        retry = d.get("retry_policy", {})
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            description=d.get("description", ""),
            category=d.get("category", ""),
            risk_level=d.get("risk_level", "low"),
            requires_approval=d.get("requires_approval", False),
            required_secrets=d.get("required_secrets", []),
            required_configs=d.get("required_configs", []),
            input_schema=d.get("input_schema", {}),
            output_schema=d.get("output_schema", {}),
            retry_policy=RetryPolicy.from_dict(retry) if isinstance(retry, dict) else RetryPolicy(),
            timeout=d.get("timeout", 30),
            tags=d.get("tags", []),
            version=d.get("version", "1.0"),
            enabled=d.get("enabled", True),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> OperationalTool:
        with open(path) as f:
            return cls.from_dict(json.load(f))


@dataclass
class ToolExecutionResult:
    """Result of executing an operational tool."""
    tool_id: str
    ok: bool
    status_code: int = 0
    response: Any = None
    error: str = ""
    duration_ms: float = 0
    attempt: int = 1
    approved: bool = True
    simulated: bool = False

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "ok": self.ok,
            "status_code": self.status_code,
            "response": str(self.response)[:2000] if self.response else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "attempt": self.attempt,
            "approved": self.approved,
            "simulated": self.simulated,
        }


@dataclass
class ApprovalDecision:
    """Decision record for a tool/plan approval."""
    decision_id: str = ""
    target_type: str = ""  # tool, plan
    target_id: str = ""
    approved: bool = False
    reason: str = ""
    decided_by: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "approved": self.approved,
            "reason": self.reason,
            "decided_by": self.decided_by,
            "timestamp": self.timestamp,
        }
