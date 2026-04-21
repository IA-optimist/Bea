"""
executor/capability_contracts.py — Unified capability request/result contracts.

All capability invocations (native tool, plugin, MCP tool) flow through
these contracts. Executor and MetaOrchestrator reason in these types.

This is the canonical interface — do NOT bypass it.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class CapabilityType(str, Enum):
    """Source type of a capability."""
    NATIVE_TOOL = "native_tool"
    PLUGIN = "plugin"
    MCP_TOOL = "mcp_tool"


@dataclass
class CapabilityRequest:
    """
    Request to invoke a capability.

    Fields:
        capability_type: where the capability lives
        capability_id:   tool name / plugin_id / mcp tool_id
        action:          sub-action within the capability (plugin/MCP)
        params:          invocation parameters
        context:         caller context (mission_id, agent, etc.)
        risk_level:      declared risk level (for approval routing)
        requires_approval: force approval gate
    """
    capability_type: CapabilityType
    capability_id: str
    action: str = "invoke"
    params: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    risk_level: str = "low"
    requires_approval: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["capability_type"] = self.capability_type.value
        return d


@dataclass
class CapabilityResult:
    """
    Result of a capability invocation.

    Always returned — never raises.
    Check .ok to determine success/failure.
    """
    ok: bool
    capability_type: CapabilityType
    capability_id: str
    result: Any = None
    error: Optional[str] = None
    execution_ms: int = 0
    used_skill_ids: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        capability_type: CapabilityType,
        capability_id: str,
        result: Any,
        ms: int = 0,
    ) -> "CapabilityResult":
        return cls(
            ok=True,
            capability_type=capability_type,
            capability_id=capability_id,
            result=result,
            execution_ms=ms,
        )

    @classmethod
    def failure(
        cls,
        capability_type: CapabilityType,
        capability_id: str,
        error: str,
        ms: int = 0,
    ) -> "CapabilityResult":
        return cls(
            ok=False,
            capability_type=capability_type,
            capability_id=capability_id,
            error=error,
            execution_ms=ms,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["capability_type"] = self.capability_type.value
        return d
