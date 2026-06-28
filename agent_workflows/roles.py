"""
agent_workflows/roles.py — Agent roles for SOP multi-agent workflows.

Roles define what an agent is responsible for in a workflow step.
Inspired by MetaGPT's role-based architecture.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """Standard agent roles in the SOP framework."""

    PLANNER = "planner"       # decomposes goal into subtasks
    CODER = "coder"           # implements code changes
    REVIEWER = "reviewer"     # reviews code and produces verdicts
    TESTER = "tester"         # runs tests and reports results
    RESEARCHER = "researcher" # gathers external knowledge
    ANALYST = "analyst"       # interprets data / reports
    COORDINATOR = "coordinator"  # orchestrates other agents
    GATEKEEPER = "gatekeeper" # human-approval checkpoint


# Capabilities bundled with each role (default set)
_ROLE_CAPABILITIES: dict[AgentRole, frozenset[str]] = {
    AgentRole.PLANNER:      frozenset({"read", "write"}),
    AgentRole.CODER:        frozenset({"read", "write", "execute", "sandbox"}),
    AgentRole.REVIEWER:     frozenset({"read", "execute"}),
    AgentRole.TESTER:       frozenset({"read", "execute", "sandbox"}),
    AgentRole.RESEARCHER:   frozenset({"read"}),
    AgentRole.ANALYST:      frozenset({"read"}),
    AgentRole.COORDINATOR:  frozenset({"read", "write"}),
    AgentRole.GATEKEEPER:   frozenset(),  # gatekeeper is a human pause, no auto caps
}


class AgentProfile(BaseModel):
    """A concrete agent instance with a role, id, and capabilities."""

    agent_id: str
    role: AgentRole
    name: str
    capabilities: frozenset[str] = Field(default_factory=frozenset)
    description: str = ""

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_role(cls, agent_id: str, role: AgentRole, name: str = "") -> "AgentProfile":
        return cls(
            agent_id=agent_id,
            role=role,
            name=name or f"{role.value}-{agent_id[:8]}",
            capabilities=_ROLE_CAPABILITIES.get(role, frozenset()),
        )
