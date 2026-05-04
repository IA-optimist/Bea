"""
core/capabilities/schema.py — Capability schema for tool registry.

Each tool/capability has a defined risk level, approval requirement,
timeout, and agent allowlist. The executor checks this before execution.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal


@dataclass(frozen=True)
class Capability:
    """A registered tool capability with execution policy."""
    name: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    requires_approval: bool = False
    timeout_seconds: int = 30
    allowed_agents: tuple[str, ...] = ()  # empty = all agents allowed
    description: str = ""

    def allows_agent(self, agent_name: str) -> bool:
        """Check if an agent is allowed to use this capability."""
        if not self.allowed_agents:
            return True  # empty = unrestricted
        return agent_name in self.allowed_agents

    def to_dict(self) -> dict:
        d = asdict(self)
        d["allowed_agents"] = list(self.allowed_agents)
        return d
