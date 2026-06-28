"""
agent_workflows — SOP multi-agent workflow layer (MetaGPT/ChatDev/CrewAI pattern).

Provides:
    ReviewVerdict     — structured verdict from any review step
    VerdictSeverity   — P0 (blocker) → P3 (info)
    SOPWorkflowEngine — runs a defined sequence of SOP steps, collecting verdicts
    AgentRole         — typed roles for multi-agent workflows
"""
from __future__ import annotations

from agent_workflows.verdicts import ReviewVerdict, VerdictSeverity
from agent_workflows.roles import AgentRole
from agent_workflows.engine import SOPWorkflowEngine, SOPStep, WorkflowResult

__all__ = [
    "ReviewVerdict",
    "VerdictSeverity",
    "AgentRole",
    "SOPWorkflowEngine",
    "SOPStep",
    "WorkflowResult",
]
