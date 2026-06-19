"""
core/skills/domain_skill_router.py — Generic domain skill routing.

Extensible base for domain-specific skill routers.
Pattern: capability_router → domain_router → skill_router

Current implementations:
  - SecuritySkillRouter (security.*)

Future implementations:
  - EngineeringSkillRouter (code.*)
  - ResearchSkillRouter (research.*)
  - BusinessSkillRouter (business.*)
  - AutomationSkillRouter (workflow.*)
  - DataSkillRouter (data.*)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger("skills.domain_router")


@dataclass
class SkillMeta:
    """Universal enriched metadata for a domain skill."""
    id: str
    name: str
    domain: str
    subdomain: str = ""
    description: str = ""
    risk_level: str = "low"                          # low | medium | high | critical
    confidence_weight: float = 0.8                   # 0.0-1.0
    tool_requirements: list[str] = field(default_factory=list)
    requires_activation: bool = False
    expected_output_type: str = "report"             # report | artifact | action | assessment
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "domain": self.domain,
            "subdomain": self.subdomain, "description": self.description,
            "risk_level": self.risk_level, "confidence_weight": self.confidence_weight,
            "tool_requirements": self.tool_requirements,
            "requires_activation": self.requires_activation,
            "expected_output_type": self.expected_output_type,
            "tags": self.tags,
        }


class BaseDomainRouter(ABC):
    """
    Base class for domain-specific skill routers.

    Subclasses implement:
      - domain_prefix: str (e.g., "security", "code", "research")
      - load(): load skills from catalog
      - capability_to_domain_map(): mapping from capability_id → domain string
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillMeta] = {}
        self._loaded = False

    @property
    @abstractmethod
    def domain_prefix(self) -> str:
        """Capability prefix this router handles (e.g., 'security')."""
        ...

    @abstractmethod
    def _load_catalog(self) -> int:
        """Load skills from domain-specific catalog. Return count."""
        ...

    @abstractmethod
    def _get_domain_for_capability(self, capability_id: str) -> str | None:
        """Map capability_id to domain string."""
        ...

    def load(self) -> int:
        if self._loaded:
            return len(self._skills)
        count = self._load_catalog()
        self._loaded = True
        return count

    def handles(self, capability_id: str) -> bool:
        """Does this router handle this capability?"""
        return capability_id.startswith(f"{self.domain_prefix}.")

    def resolve(self, capability_id: str, goal: str = "") -> list[SkillMeta]:
        """Find matching skills for a capability, sorted by relevance."""
        if not self._loaded:
            self.load()

        domain = self._get_domain_for_capability(capability_id)
        if not domain:
            return []

        candidates = [s for s in self._skills.values() if s.domain == domain]

        if goal:
            goal_lower = goal.lower()
            scored = []
            for skill in candidates:
                score = 0
                for word in skill.name.split("_"):
                    if word in goal_lower:
                        score += 3
                for word in skill.description.lower().split():
                    if len(word) > 3 and word in goal_lower:
                        score += 1
                scored.append((score, skill))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [s for _, s in scored]

        return candidates

    def get_skill(self, skill_id: str) -> SkillMeta | None:
        if not self._loaded:
            self.load()
        return self._skills.get(skill_id)

    def get_routing_context(self, capability_id: str, goal: str = "") -> dict[str, Any]:
        """Full routing context — override in subclass for domain-specific logic."""
        domain = self._get_domain_for_capability(capability_id)
        if not domain:
            return {"matched": False, "capability_id": capability_id}

        skills = self.resolve(capability_id, goal)
        return {
            "matched": True,
            "capability_id": capability_id,
            "domain": domain,
            "router": self.domain_prefix,
            "skills_count": len(skills),
            "top_skills": [s.to_dict() for s in skills[:5]],
            "blocked": False,
            "block_reason": None,
        }

    def stats(self) -> dict[str, Any]:
        if not self._loaded:
            self.load()
        by_domain: dict[str, int] = {}
        by_risk: dict[str, int] = {}
        for s in self._skills.values():
            by_domain[s.domain] = by_domain.get(s.domain, 0) + 1
            by_risk[s.risk_level] = by_risk.get(s.risk_level, 0) + 1
        return {
            "prefix": self.domain_prefix,
            "total": len(self._skills),
            "by_domain": by_domain,
            "by_risk": by_risk,
            "loaded": self._loaded,
        }


# ── Router Registry ──

_domain_routers: dict[str, BaseDomainRouter] = {}


def register_domain_router(router: BaseDomainRouter) -> None:
    """Register a domain router for a capability prefix."""
    _domain_routers[router.domain_prefix] = router
    log.info("domain_router_registered", prefix=router.domain_prefix)


def get_domain_router(capability_id: str) -> BaseDomainRouter | None:
    """Find the domain router that handles this capability."""
    for prefix, router in _domain_routers.items():
        if capability_id.startswith(f"{prefix}."):
            return router
    return None


def get_all_domain_routers() -> dict[str, BaseDomainRouter]:
    """Get all registered domain routers."""
    return dict(_domain_routers)


def resolve_via_domain_routers(capability_id: str, goal: str = "") -> dict[str, Any] | None:
    """
    Try to resolve via registered domain routers.
    Returns routing context if matched, None otherwise.
    """
    router = get_domain_router(capability_id)
    if router:
        return router.get_routing_context(capability_id, goal)
    return None
