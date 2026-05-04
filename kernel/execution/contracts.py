"""
kernel/execution/contracts.py — Canonical execution contracts.

K1 RULE: ZERO imports from core/, agents/, api/, tools/.
Pure data types — no business logic, no side effects.

Contracts:
  ExecutionRequest   — what the kernel asks to execute
  ExecutionResult    — what the kernel gets back
  ExecutionHandle    — lightweight reference to a running execution
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class ExecutionStatus(str, Enum):
    CREATED           = "CREATED"
    RUNNING           = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REVIEW            = "REVIEW"
    DONE              = "DONE"
    FAILED            = "FAILED"
    CANCELLED         = "CANCELLED"


@dataclass
class ExecutionRequest:
    """
    What the kernel submits for execution.

    Produced by JarvisKernel.execute() after cognitive pre-computation
    (classify → plan → route → retrieve).
    """
    goal:        str
    mission_id:  str               = field(default_factory=lambda: f"ke-{uuid.uuid4().hex[:8]}")
    mode:        str               = "auto"
    callback:    Optional[Callable] = field(default=None, repr=False)
    metadata:    dict              = field(default_factory=dict)
    created_at:  float             = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "mission_id":  self.mission_id,
            "goal":        self.goal[:200],
            "mode":        self.mode,
            "metadata":    self.metadata,
            "created_at":  self.created_at,
        }


@dataclass
class ExecutionResult:
    """
    What the kernel gets back from execution.

    Wraps whatever the delegate (MetaOrchestrator) returns — MissionContext
    or dict — into a stable kernel-level contract.

    The API reads ExecutionResult instead of raw MissionContext, making
    kernel.execute() the authoritative execution interface.
    """
    mission_id:  str
    status:      ExecutionStatus  = ExecutionStatus.DONE
    result:      str              = ""
    error:       Optional[str]    = None
    metadata:    dict             = field(default_factory=dict)
    goal:        str              = ""
    mode:        str              = "auto"
    created_at:  float            = field(default_factory=time.time)

    # Backward-compat: allow attribute access like MissionContext
    def get_output(self, agent: str) -> str:
        """Compatibility with JarvisSession.get_output() interface."""
        outputs = self.metadata.get("agent_outputs", {})
        if isinstance(outputs, dict):
            out = outputs.get(agent, "")
            return out if isinstance(out, str) else str(out) if out else ""
        return ""

    @property
    def final_report(self) -> str:
        """Compatibility with JarvisSession.final_report."""
        return self.result

    def is_terminal(self) -> bool:
        return self.status in (
            ExecutionStatus.DONE,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        )

    def to_dict(self) -> dict:
        return {
            "mission_id":  self.mission_id,
            "status":      self.status.value,
            "result":      (self.result or "")[:2000],
            "error":       self.error,
            "metadata":    self.metadata,
            "goal":        self.goal[:200],
            "mode":        self.mode,
            "created_at":  self.created_at,
        }

    @classmethod
    def from_context(cls, ctx: Any) -> "ExecutionResult":
        """
        Build ExecutionResult from a MissionContext (or dict) returned by MetaOrchestrator.

        Handles both MissionContext objects and plain dicts — fail-open.
        """
        if ctx is None:
            return cls(mission_id="unknown", status=ExecutionStatus.FAILED,
                       error="Null context returned by executor")

        if isinstance(ctx, dict):
            status_raw = ctx.get("status", "DONE")
        else:
            _s = getattr(ctx, "status", None)
            status_raw = _s.value if hasattr(_s, "value") else str(_s or "DONE")

        # Map string status to ExecutionStatus
        try:
            status = ExecutionStatus(status_raw)
        except ValueError:
            status = ExecutionStatus.DONE if "DONE" in status_raw.upper() else ExecutionStatus.FAILED

        if isinstance(ctx, dict):
            return cls(
                mission_id=str(ctx.get("mission_id", "unknown")),
                status=status,
                result=str(ctx.get("result", "") or ""),
                error=ctx.get("error"),
                metadata=ctx.get("metadata", {}),
                goal=str(ctx.get("goal", ""))[:200],
                mode=str(ctx.get("mode", "auto")),
            )
        else:
            # Extract result — if ctx.result is an ExecutionOutcome, unwrap .result
            _raw_result = getattr(ctx, "result", "") or ""
            if hasattr(_raw_result, "result"):  # ExecutionOutcome or similar
                _raw_result = getattr(_raw_result, "result", "") or ""
            return cls(
                mission_id=str(getattr(ctx, "mission_id", "unknown")),
                status=status,
                result=str(_raw_result),
                error=getattr(ctx, "error", None),
                metadata=getattr(ctx, "metadata", {}),
                goal=str(getattr(ctx, "goal", ""))[:200],
                mode=str(getattr(ctx, "mode", "auto")),
            )


@dataclass
class ExecutionHandle:
    """
    Lightweight reference to a running or completed execution.
    Used for async status polling and cancellation.
    """
    mission_id: str
    status:     ExecutionStatus = ExecutionStatus.RUNNING
    started_at: float           = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "status":     self.status.value,
            "started_at": self.started_at,
        }
