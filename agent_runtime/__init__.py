"""
agent_runtime — Agent Computer Interface (ACI) for Béa.

Inspired by SWE-agent's Action Computer Interface: agents never get a free
shell. Every action goes through typed, capability-checked, audited handlers.

Public surface:
    from agent_runtime import ACIExecutor, ActionRequest, ActionResult
    from agent_runtime import CommandPolicy, SandboxPolicy, RiskLevel
    from agent_runtime import ActionType, ACIActionRegistry
"""
from __future__ import annotations

from agent_runtime.actions import ActionType, ActionRequest, ActionResult
from agent_runtime.policy import RiskLevel, CommandPolicy, SandboxPolicy
from agent_runtime.registry import ACIActionRegistry
from agent_runtime.executor import ACIExecutor

__all__ = [
    "ActionType",
    "ActionRequest",
    "ActionResult",
    "RiskLevel",
    "CommandPolicy",
    "SandboxPolicy",
    "ACIActionRegistry",
    "ACIExecutor",
]
