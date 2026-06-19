"""
core/skills/skill_chain.py — Business execution chaining.

Defines preset chains that map high-level intents to ordered skill sequences.
Each chain produces a comprehensive artifact bundle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillChain:
    """A predefined chain of skills triggered by a single intent."""
    chain_id: str
    name: str
    description: str
    skill_sequence: list[str]
    action_sequence: list[str]  # business actions to execute
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "description": self.description,
            "skill_sequence": self.skill_sequence,
            "action_sequence": self.action_sequence,
            "tags": self.tags,
        }


CHAIN_REGISTRY: dict[str, SkillChain] = {
    "full_opportunity_package": SkillChain(
        chain_id="full_opportunity_package",
        name="Full Opportunity Package",
        description="End-to-end: market research → persona → offer → SaaS scope → acquisition → automation blueprint",
        skill_sequence=[
            "market_research.basic",
            "persona.basic",
            "offer_design.basic",
            "saas_scope.basic",
            "acquisition.basic",
            "automation_opportunity.basic",
        ],
        action_sequence=[
            "venture.research_workspace",
            "offer.package",
            "saas.mvp_spec",
            "workflow.blueprint",
        ],
        tags=["full", "end-to-end", "opportunity"],
    ),
    "validate_idea": SkillChain(
        chain_id="validate_idea",
        name="Idea Validation",
        description="Quick validation: market research → persona → offer design",
        skill_sequence=[
            "market_research.basic",
            "persona.basic",
            "offer_design.basic",
        ],
        action_sequence=[
            "venture.research_workspace",
            "offer.package",
        ],
        tags=["validation", "quick"],
    ),
    "technical_blueprint": SkillChain(
        chain_id="technical_blueprint",
        name="Technical Blueprint",
        description="SaaS specification: persona → SaaS scope → automation opportunities",
        skill_sequence=[
            "persona.basic",
            "saas_scope.basic",
            "automation_opportunity.basic",
        ],
        action_sequence=[
            "saas.mvp_spec",
            "workflow.blueprint",
        ],
        tags=["technical", "saas", "blueprint"],
    ),
}


def list_chains() -> list[dict[str, Any]]:
    return [c.to_dict() for c in CHAIN_REGISTRY.values()]


def get_chain(chain_id: str) -> SkillChain | None:
    return CHAIN_REGISTRY.get(chain_id)
