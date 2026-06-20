"""
core/agents/role_definitions.py — AI OS Agent Role Definitions.

Defines 6 stable core roles with clear responsibilities, I/O, and success criteria.
Maps existing 19 agents to these roles without creating new agents.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Literal

CoreRole = Literal["planner", "researcher", "critic", "reviewer", "operator", "memory_curator"]


@dataclass
class RoleDefinition:
    """Clear definition of an agent role."""
    role: CoreRole
    responsibility: str
    input_type: str
    output_type: str
    success_criteria: str
    assigned_agents: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["assigned_agents"] = list(self.assigned_agents)
        return d


ROLE_DEFINITIONS: dict[CoreRole, RoleDefinition] = {
    "planner": RoleDefinition(
        role="planner",
        responsibility="Decompose goals into executable plans with ordered steps",
        input_type="goal: str, context: dict",
        output_type="plan: list[Step], estimated_duration: int",
        success_criteria="Plan is executable, all steps map to known capabilities",
        assigned_agents=("atlas-director", "map-planner", "bea-architect"),
    ),
    "researcher": RoleDefinition(
        role="researcher",
        responsibility="Gather information, search memory/web, assemble context",
        input_type="query: str, scope: str",
        output_type="findings: list[str], sources: list[str], confidence: float",
        success_criteria="Findings are relevant, sourced, and actionable",
        assigned_agents=("scout-research", "vault-memory"),
    ),
    "critic": RoleDefinition(
        role="critic",
        responsibility="Evaluate plans, results, and proposals for quality and safety",
        input_type="artifact: str, criteria: list[str]",
        output_type="verdict: str, issues: list[str], score: float",
        success_criteria="Issues are specific, actionable, and severity-ranked",
        assigned_agents=("shadow-advisor", "lens-reviewer", "bea-reviewer"),
    ),
    "reviewer": RoleDefinition(
        role="reviewer",
        responsibility="Final quality gate before output delivery",
        input_type="result: str, goal: str",
        output_type="approved: bool, feedback: str",
        success_criteria="Result meets goal, no hallucinations, format correct",
        assigned_agents=("lens-reviewer", "bea-qa"),
    ),
    "operator": RoleDefinition(
        role="operator",
        responsibility="Execute tools, write code, run commands, build artifacts",
        input_type="action: str, tool: str, params: dict",
        output_type="result: dict, artifacts: list[str]",
        success_criteria="Action completed successfully, output matches spec",
        assigned_agents=("forge-builder", "pulse-ops", "night-worker",
                         "bea-coder", "bea-devops"),
    ),
    "memory_curator": RoleDefinition(
        role="memory_curator",
        responsibility="Manage memory: store learnings, prune stale entries, maintain quality",
        input_type="memory_action: str, content: str?",
        output_type="updated: bool, entries_affected: int",
        success_criteria="Memory is relevant, bounded, and up-to-date",
        assigned_agents=("vault-memory", "bea-watcher"),
    ),
}


def get_role(role: CoreRole) -> RoleDefinition:
    return ROLE_DEFINITIONS[role]

def role_for_agent(agent_name: str) -> str:
    """Find the primary role for an agent name."""
    for role_def in ROLE_DEFINITIONS.values():
        if agent_name in role_def.assigned_agents:
            return role_def.role
    return "operator"  # Default fallback

def list_roles() -> list[dict[str, Any]]:
    return [r.to_dict() for r in ROLE_DEFINITIONS.values()]

def agent_role_map() -> dict[str, str]:
    """Map all agents to their roles."""
    mapping: dict[str, str] = {}
    for role_def in ROLE_DEFINITIONS.values():
        for agent in role_def.assigned_agents:
            mapping[agent] = role_def.role
    return mapping
