"""
core/agents/roles.py — Canonical agent role definitions for BeaMax.

Defines the 6 structured agent roles with clear responsibilities,
capabilities, and communication contracts.

These roles are consumed by MetaOrchestrator for delegation,
by capability routing for provider selection, and by the dashboard for display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentRole(str, Enum):
    """Canonical agent roles."""
    CEO = "ceo"
    ARCHITECT = "architect"
    ENGINEER = "engineer"
    ANALYST = "analyst"
    OPERATOR = "operator"
    REVIEWER = "reviewer"


@dataclass
class AgentRoleSpec:
    """Structured specification for an agent role."""
    role: AgentRole
    name: str
    description: str
    responsibilities: list[str]
    capabilities: list[str]
    inputs: list[str]  # what it receives
    outputs: list[str]  # what it produces
    can_delegate_to: list[AgentRole] = field(default_factory=list)
    requires_approval_for: list[str] = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "name": self.name,
            "description": self.description,
            "responsibilities": self.responsibilities,
            "capabilities": self.capabilities,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "can_delegate_to": [r.value for r in self.can_delegate_to],
            "requires_approval_for": self.requires_approval_for,
            "risk_level": self.risk_level,
        }


# ── Role Definitions ──────────────────────────────────────────

ROLE_SPECS: dict[AgentRole, AgentRoleSpec] = {
    AgentRole.CEO: AgentRoleSpec(
        role=AgentRole.CEO,
        name="CEO Agent",
        description="High-level reasoning, goal decomposition, and task prioritization. Decides what to do and delegates to specialists.",
        responsibilities=[
            "Interpret user goals into structured objectives",
            "Decompose complex goals into agent-assignable tasks",
            "Prioritize tasks by impact and feasibility",
            "Monitor overall mission progress",
            "Escalate to human when confidence is low",
        ],
        capabilities=["goal_decomposition", "prioritization", "delegation", "progress_monitoring"],
        inputs=["user_goal", "context", "constraints"],
        outputs=["task_list", "delegation_plan", "priority_ranking"],
        can_delegate_to=[AgentRole.ARCHITECT, AgentRole.ANALYST, AgentRole.ENGINEER],
        risk_level="low",
    ),
    AgentRole.ARCHITECT: AgentRoleSpec(
        role=AgentRole.ARCHITECT,
        name="Architect Agent",
        description="System design decisions, dependency awareness, and technical planning. Designs before building.",
        responsibilities=[
            "Design system architecture for new features",
            "Identify dependencies and integration points",
            "Evaluate technical trade-offs",
            "Produce design specs and diagrams",
            "Review engineer output for architectural coherence",
        ],
        capabilities=["system_design", "dependency_analysis", "trade_off_evaluation"],
        inputs=["requirements", "constraints", "existing_architecture"],
        outputs=["design_spec", "dependency_map", "technical_decisions"],
        can_delegate_to=[AgentRole.ENGINEER],
        risk_level="low",
    ),
    AgentRole.ENGINEER: AgentRoleSpec(
        role=AgentRole.ENGINEER,
        name="Engineer Agent",
        description="Code generation, modification, and implementation. Builds what the architect designs.",
        responsibilities=[
            "Generate code from specifications",
            "Modify existing code safely",
            "Write tests for new functionality",
            "Follow coding standards and patterns",
            "Produce clean, documented implementations",
        ],
        capabilities=["code_generation", "code_modification", "test_writing", "refactoring"],
        inputs=["design_spec", "requirements", "existing_code"],
        outputs=["code_changes", "tests", "documentation"],
        can_delegate_to=[],
        requires_approval_for=["production_code_changes", "dependency_additions"],
        risk_level="medium",
    ),
    AgentRole.ANALYST: AgentRoleSpec(
        role=AgentRole.ANALYST,
        name="Analyst Agent",
        description="Research, evaluation, and business analysis. Produces structured intelligence from unstructured information.",
        responsibilities=[
            "Conduct market research and competitive analysis",
            "Build customer personas and value propositions",
            "Evaluate business opportunities",
            "Produce structured analysis artifacts",
            "Score and rank options with justification",
        ],
        capabilities=["market_research", "competitive_analysis", "persona_creation",
                      "opportunity_scoring", "offer_design", "saas_scoping"],
        inputs=["research_goal", "sector", "constraints", "prior_analysis"],
        outputs=["research_dossier", "analysis_report", "scored_opportunities",
                "persona_profiles", "offer_packages"],
        can_delegate_to=[],
        risk_level="low",
    ),
    AgentRole.OPERATOR: AgentRoleSpec(
        role=AgentRole.OPERATOR,
        name="Operator Agent",
        description="Safe tool usage and execution. Interacts with external systems under approval constraints.",
        responsibilities=[
            "Execute approved tool operations",
            "Validate tool readiness before execution",
            "Capture and store execution artifacts",
            "Handle tool failures gracefully",
            "Report execution results",
        ],
        capabilities=["tool_execution", "webhook_triggering", "file_operations",
                      "artifact_storage"],
        inputs=["tool_id", "inputs", "approval_status"],
        outputs=["execution_result", "artifacts", "status_report"],
        can_delegate_to=[],
        requires_approval_for=["external_api_calls", "automation_triggers",
                              "file_modifications_outside_workspace"],
        risk_level="high",
    ),
    AgentRole.REVIEWER: AgentRoleSpec(
        role=AgentRole.REVIEWER,
        name="Reviewer Agent",
        description="Quality validation and output evaluation. Ensures outputs meet standards before delivery.",
        responsibilities=[
            "Review code changes for quality and safety",
            "Validate business artifacts for completeness",
            "Check skill outputs against quality criteria",
            "Provide structured feedback",
            "Gate promotion of self-improvement patches",
        ],
        capabilities=["code_review", "artifact_validation", "quality_scoring",
                      "feedback_generation"],
        inputs=["artifact", "quality_criteria", "context"],
        outputs=["review_result", "quality_score", "feedback", "approval_recommendation"],
        can_delegate_to=[],
        risk_level="low",
    ),
}


def get_role_spec(role: AgentRole | str) -> AgentRoleSpec | None:
    """Get the specification for a role."""
    if isinstance(role, str):
        try:
            role = AgentRole(role)
        except ValueError:
            return None
    return ROLE_SPECS.get(role)


def list_roles() -> list[dict]:
    """List all role specifications."""
    return [spec.to_dict() for spec in ROLE_SPECS.values()]


def get_role_for_capability(capability: str) -> AgentRole | None:
    """Find which role owns a capability."""
    for role, spec in ROLE_SPECS.items():
        if capability in spec.capabilities:
            return role
    return None
