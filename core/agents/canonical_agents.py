"""
core/agents/canonical_agents.py — Canonical Runtime Agent Architecture.

Compresses AGI-inspired role set into a small practical runtime core
of 6 canonical agents + specialist capability packs activable on demand.

Canonical Runtime Agents (always active):
  1. Cognitive Architect      — system design, dependency awareness, architectural decisions
  2. Planning Engineer        — goal decomposition, plan construction, step sequencing
  3. Systems Engineer         — kernel, infrastructure, tool management, deployment
  4. Execution Engineer       — code generation, artifact building, tool invocation
  5. Safety Guardian          — policy enforcement, risk assessment, approval gates
  6. Learning Engineer        — self-improvement, memory, performance tracking, adaptation

Specialist Packs (activated on demand):
  - business_intelligence    — market research, competitive analysis, opportunity scoring
  - financial_reasoning      — pricing, revenue, cost analysis, compliance
  - product_design           — offer design, persona creation, landing pages
  - content_creation         — copywriting, documentation, technical writing
  - devops_operations        — deployment, monitoring, infrastructure automation

Integration points:
  - capability_routing: CanonicalAgent → capabilities → ProviderRegistry
  - self_model: canonical agents reported as core components
  - strategic_memory: agent performance tracked per canonical role
  - mission_planning: canonical agents assigned to plan steps
  - safety_flow: SafetyGuardian consulted on every high-risk action

Design: purely additive, fail-open, does NOT replace existing roles.py.
Maps new canonical agents onto existing AgentRole enum values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import structlog

log = structlog.get_logger("agents.canonical")


# ═══════════════════════════════════════════════════════════════
# CANONICAL AGENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════

class CanonicalAgentId(str, Enum):
    """6 canonical runtime agents."""
    COGNITIVE_ARCHITECT = "cognitive_architect"
    PLANNING_ENGINEER = "planning_engineer"
    SYSTEMS_ENGINEER = "systems_engineer"
    EXECUTION_ENGINEER = "execution_engineer"
    SAFETY_GUARDIAN = "safety_guardian"
    LEARNING_ENGINEER = "learning_engineer"


@dataclass
class CanonicalAgent:
    """Specification for a canonical runtime agent."""
    id: CanonicalAgentId
    name: str
    description: str
    capabilities: list[str]
    llm_role: str           # maps to LLMFactory role for model selection
    risk_level: str = "low"
    always_active: bool = True
    requires_approval: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id.value,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "llm_role": self.llm_role,
            "risk_level": self.risk_level,
            "always_active": self.always_active,
            "requires_approval": self.requires_approval,
        }


CANONICAL_AGENTS: dict[CanonicalAgentId, CanonicalAgent] = {
    CanonicalAgentId.COGNITIVE_ARCHITECT: CanonicalAgent(
        id=CanonicalAgentId.COGNITIVE_ARCHITECT,
        name="Cognitive Architect",
        description="System design, dependency awareness, architectural decisions, trade-off evaluation.",
        capabilities=[
            "system_design", "dependency_analysis", "trade_off_evaluation",
            "architecture_review", "pattern_detection",
        ],
        llm_role="architect",
    ),
    CanonicalAgentId.PLANNING_ENGINEER: CanonicalAgent(
        id=CanonicalAgentId.PLANNING_ENGINEER,
        name="Planning & Reasoning Engineer",
        description="Goal decomposition, plan construction, step sequencing, priority ranking, replanning.",
        capabilities=[
            "goal_decomposition", "plan_construction", "step_sequencing",
            "prioritization", "delegation", "progress_monitoring", "replanning",
        ],
        llm_role="planner",
    ),
    CanonicalAgentId.SYSTEMS_ENGINEER: CanonicalAgent(
        id=CanonicalAgentId.SYSTEMS_ENGINEER,
        name="Kernel & Systems Engineer",
        description="Infrastructure management, tool registry, deployment, MCP coordination, kernel operations.",
        capabilities=[
            "tool_execution", "tool_management", "mcp_coordination",
            "deployment", "infrastructure", "file_operations", "webhook_triggering",
        ],
        llm_role="operator",
        risk_level="medium",
        requires_approval=["external_api_calls", "deployment", "infrastructure_changes"],
    ),
    CanonicalAgentId.EXECUTION_ENGINEER: CanonicalAgent(
        id=CanonicalAgentId.EXECUTION_ENGINEER,
        name="Execution & Tooling Engineer",
        description="Code generation, artifact building, test writing, refactoring, implementation.",
        capabilities=[
            "code_generation", "code_modification", "test_writing",
            "refactoring", "artifact_building", "documentation",
        ],
        llm_role="coder",
        risk_level="medium",
        requires_approval=["production_code_changes"],
    ),
    CanonicalAgentId.SAFETY_GUARDIAN: CanonicalAgent(
        id=CanonicalAgentId.SAFETY_GUARDIAN,
        name="Safety & Alignment Guardian",
        description="Policy enforcement, risk assessment, approval gates, secret protection, boundary enforcement.",
        capabilities=[
            "policy_enforcement", "risk_assessment", "approval_gating",
            "secret_protection", "code_review", "quality_scoring",
            "artifact_validation", "feedback_generation",
        ],
        llm_role="reviewer",
    ),
    CanonicalAgentId.LEARNING_ENGINEER: CanonicalAgent(
        id=CanonicalAgentId.LEARNING_ENGINEER,
        name="Learning & Self-Improvement Engineer",
        description="Self-improvement, memory management, performance tracking, adaptation, experiment management.",
        capabilities=[
            "self_improvement", "memory_management", "performance_tracking",
            "experiment_management", "weakness_detection", "strategy_learning",
        ],
        llm_role="analyst",
    ),
}


# ═══════════════════════════════════════════════════════════════
# SPECIALIST CAPABILITY PACKS (on-demand)
# ═══════════════════════════════════════════════════════════════

@dataclass
class SpecialistPack:
    """Activable specialist capability bundle."""
    id: str
    name: str
    description: str
    capabilities: list[str]
    llm_role: str
    parent_agent: CanonicalAgentId  # which canonical agent activates this
    active: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "llm_role": self.llm_role,
            "parent_agent": self.parent_agent.value,
            "active": self.active,
        }


SPECIALIST_PACKS: dict[str, SpecialistPack] = {
    "business_intelligence": SpecialistPack(
        id="business_intelligence",
        name="Business Intelligence",
        description="Market research, competitive analysis, opportunity scoring, persona creation.",
        capabilities=[
            "market_research", "competitive_analysis", "persona_creation",
            "opportunity_scoring", "market_intelligence",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.PLANNING_ENGINEER,
    ),
    "financial_reasoning": SpecialistPack(
        id="financial_reasoning",
        name="Financial Reasoning",
        description="Pricing analysis, revenue modeling, cost analysis, compliance checks.",
        capabilities=[
            "financial_reasoning", "pricing_analysis", "revenue_modeling",
            "compliance_reasoning",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.PLANNING_ENGINEER,
    ),
    "product_design": SpecialistPack(
        id="product_design",
        name="Product Design",
        description="Offer design, value proposition, landing page creation, SaaS scoping.",
        capabilities=[
            "offer_design", "product_design", "saas_scoping",
            "value_proposition", "landing_page_creation",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.EXECUTION_ENGINEER,
    ),
    "content_creation": SpecialistPack(
        id="content_creation",
        name="Content Creation",
        description="Copywriting, documentation, technical writing, content strategy.",
        capabilities=[
            "content_creation", "copywriting", "documentation",
            "technical_writing", "content_strategy",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.EXECUTION_ENGINEER,
    ),
    "devops_operations": SpecialistPack(
        id="devops_operations",
        name="DevOps Operations",
        description="Deployment automation, monitoring, infrastructure management, CI/CD.",
        capabilities=[
            "deployment_automation", "monitoring", "ci_cd",
            "infrastructure_automation",
        ],
        llm_role="operator",
        parent_agent=CanonicalAgentId.SYSTEMS_ENGINEER,
    ),
    "blue_team": SpecialistPack(
        id="blue_team",
        name="Blue Team — Defensive Security",
        description="SIEM analysis, incident response, forensics, cloud security, endpoint protection, network defense.",
        capabilities=[
            "siem_analysis", "incident_response", "digital_forensics",
            "cloud_security", "endpoint_protection", "network_defense",
            "threat_detection", "log_analysis", "malware_analysis",
            "vulnerability_management",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.SAFETY_GUARDIAN,
    ),
    "red_team_ethical": SpecialistPack(
        id="red_team_ethical",
        name="Red Team — Ethical Offensive Security",
        description="Penetration testing, web app security, social engineering assessment, infrastructure testing.",
        capabilities=[
            "penetration_testing", "web_app_security", "social_engineering_assessment",
            "infrastructure_testing", "exploit_development", "red_team_operations",
            "wireless_testing", "physical_security_assessment",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.SAFETY_GUARDIAN,
        active=False,  # Requires explicit activation — safety gate
    ),
    "nis2_compliance": SpecialistPack(
        id="nis2_compliance",
        name="NIS2 & Regulatory Compliance",
        description="NIS2 directive compliance, GDPR, risk assessment, policy writing, audit preparation.",
        capabilities=[
            "nis2_compliance", "gdpr_compliance", "risk_assessment",
            "policy_writing", "audit_preparation", "gap_analysis",
            "regulatory_mapping", "incident_reporting_compliance",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.SAFETY_GUARDIAN,
    ),
    "osint_legal": SpecialistPack(
        id="osint_legal",
        name="OSINT — Legal Open Source Intelligence",
        description="Domain reconnaissance, threat intelligence, breach monitoring, social media OSINT.",
        capabilities=[
            "domain_reconnaissance", "threat_intelligence", "breach_monitoring",
            "social_media_osint", "dark_web_monitoring", "asset_discovery",
            "reputation_monitoring", "supply_chain_intelligence",
        ],
        llm_role="analyst",
        parent_agent=CanonicalAgentId.SAFETY_GUARDIAN,
    ),
}


# ═══════════════════════════════════════════════════════════════
# ROLE MAPPING (canonical → existing)
# ═══════════════════════════════════════════════════════════════

# Maps canonical agents to existing AgentRole enum for backward compatibility
CANONICAL_TO_LEGACY: dict[CanonicalAgentId, str] = {
    CanonicalAgentId.COGNITIVE_ARCHITECT: "architect",
    CanonicalAgentId.PLANNING_ENGINEER: "ceo",
    CanonicalAgentId.SYSTEMS_ENGINEER: "operator",
    CanonicalAgentId.EXECUTION_ENGINEER: "engineer",
    CanonicalAgentId.SAFETY_GUARDIAN: "reviewer",
    CanonicalAgentId.LEARNING_ENGINEER: "analyst",
}

# Complete capability → canonical agent map
CAPABILITY_TO_AGENT: dict[str, CanonicalAgentId] = {}
for _agent_id, _agent in CANONICAL_AGENTS.items():
    for _cap in _agent.capabilities:
        CAPABILITY_TO_AGENT[_cap] = _agent_id
for _pack_id, _pack in SPECIALIST_PACKS.items():
    for _cap in _pack.capabilities:
        if _cap not in CAPABILITY_TO_AGENT:
            CAPABILITY_TO_AGENT[_cap] = _pack.parent_agent


# ═══════════════════════════════════════════════════════════════
# RUNTIME INTEGRATION
# ═══════════════════════════════════════════════════════════════

class CanonicalAgentRuntime:
    """
    Runtime manager for canonical agents and specialist packs.

    Integrates with:
    - Capability routing (agent → capabilities → provider selection)
    - Self-model (reports agent status and health)
    - Strategic memory (tracks agent performance)
    - Mission planning (assigns agents to plan steps)
    - Safety flow (guardian consulted on risk)
    """

    def __init__(self):
        self._active_packs: set[str] = set()

    def get_agent(self, agent_id: CanonicalAgentId | str) -> CanonicalAgent | None:
        """Get canonical agent by ID."""
        if isinstance(agent_id, str):
            try:
                agent_id = CanonicalAgentId(agent_id)
            except ValueError:
                return None
        return CANONICAL_AGENTS.get(agent_id)

    def get_agent_for_capability(self, capability: str) -> CanonicalAgentId | None:
        """Resolve which canonical agent handles a capability."""
        return CAPABILITY_TO_AGENT.get(capability)

    def get_llm_role_for_capability(self, capability: str) -> str:
        """Get the LLM role to use for a capability."""
        agent_id = CAPABILITY_TO_AGENT.get(capability)
        if agent_id:
            agent = CANONICAL_AGENTS.get(agent_id)
            if agent:
                return agent.llm_role
        # Check specialist packs
        for pack in SPECIALIST_PACKS.values():
            if capability in pack.capabilities:
                return pack.llm_role
        return "analyst"  # safe default

    def activate_pack(self, pack_id: str) -> bool:
        """Activate a specialist capability pack."""
        if pack_id in SPECIALIST_PACKS:
            self._active_packs.add(pack_id)
            SPECIALIST_PACKS[pack_id].active = True
            log.info("specialist_pack_activated", pack=pack_id)
            return True
        return False

    def deactivate_pack(self, pack_id: str) -> bool:
        """Deactivate a specialist capability pack."""
        if pack_id in SPECIALIST_PACKS:
            self._active_packs.discard(pack_id)
            SPECIALIST_PACKS[pack_id].active = False
            log.info("specialist_pack_deactivated", pack=pack_id)
            return True
        return False

    def get_active_capabilities(self) -> list[str]:
        """Get all currently active capabilities (agents + active packs)."""
        caps: list[str] = []
        for agent in CANONICAL_AGENTS.values():
            caps.extend(agent.capabilities)
        for pack_id in self._active_packs:
            pack = SPECIALIST_PACKS.get(pack_id)
            if pack:
                caps.extend(pack.capabilities)
        return list(set(caps))

    def get_status(self) -> dict:
        """Full runtime status."""
        return {
            "canonical_agents": {
                a.id.value: {
                    "name": a.name,
                    "capabilities": len(a.capabilities),
                    "llm_role": a.llm_role,
                    "risk_level": a.risk_level,
                }
                for a in CANONICAL_AGENTS.values()
            },
            "specialist_packs": {
                p.id: {
                    "name": p.name,
                    "active": p.active,
                    "capabilities": len(p.capabilities),
                    "parent": p.parent_agent.value,
                }
                for p in SPECIALIST_PACKS.values()
            },
            "active_packs": list(self._active_packs),
            "total_capabilities": len(self.get_active_capabilities()),
        }

    def enrich_self_model(self, self_model_data: dict) -> dict:
        """Enrich self-model with canonical agent information."""
        try:
            self_model_data["canonical_agents"] = {
                a.id.value: a.to_dict() for a in CANONICAL_AGENTS.values()
            }
            self_model_data["specialist_packs"] = {
                p.id: p.to_dict() for p in SPECIALIST_PACKS.values()
            }
            self_model_data["capability_map"] = {
                cap: agent_id.value
                for cap, agent_id in CAPABILITY_TO_AGENT.items()
            }
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
        return self_model_data

    def enrich_routing_decision(self, capability: str, decision: dict) -> dict:
        """Enrich a routing decision with canonical agent context."""
        try:
            agent_id = self.get_agent_for_capability(capability)
            if agent_id:
                agent = CANONICAL_AGENTS[agent_id]
                decision["canonical_agent"] = agent.id.value
                decision["canonical_llm_role"] = agent.llm_role
                decision["canonical_risk_level"] = agent.risk_level
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
        return decision

    def should_require_approval(self, capability: str) -> bool:
        """Check if a capability requires approval based on its canonical agent."""
        agent_id = CAPABILITY_TO_AGENT.get(capability)
        if not agent_id:
            return False
        agent = CANONICAL_AGENTS.get(agent_id)
        if not agent:
            return False
        return len(agent.requires_approval) > 0 and agent.risk_level in ("medium", "high")


# Singleton
_runtime: CanonicalAgentRuntime | None = None


def get_canonical_runtime() -> CanonicalAgentRuntime:
    """Get singleton canonical agent runtime."""
    global _runtime
    if _runtime is None:
        _runtime = CanonicalAgentRuntime()
    return _runtime
