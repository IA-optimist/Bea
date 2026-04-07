"""
core/skills/security_skill_router.py — Security domain skill routing.

Extends BaseDomainRouter to provide security-specific routing:
  - Maps security.* capabilities to blue_team/red_team/compliance/osint domains
  - Enforces red team activation gate (pack must be active)
  - Loads skill catalog from business/skills/cybersecurity/skill.json
  - Provides structured routing context with pack status

Pattern: capability_router → domain_router → security_skill_router → skills
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog

from core.skills.domain_skill_router import (
    BaseDomainRouter,
    SkillMeta,
    register_domain_router,
)

log = structlog.get_logger("skills.security_router")

# Backward compatibility alias
SecuritySkillMeta = SkillMeta

# ── Capability → Domain mapping ──

CAPABILITY_TO_DOMAIN: dict[str, str] = {
    "security.blue_team": "blue_team",
    "security.red_team": "red_team",
    "security.compliance": "compliance",
    "security.osint": "osint",
    "security.audit": "blue_team",       # legacy pattern → blue team
    "security.secrets": "blue_team",     # secret management → blue team
}

# ── Domain → Specialist Pack mapping ──

DOMAIN_TO_PACK: dict[str, str] = {
    "blue_team": "blue_team",
    "red_team": "red_team_ethical",
    "compliance": "nis2_compliance",
    "osint": "osint_legal",
}


class SecuritySkillRouter(BaseDomainRouter):
    """
    Security domain skill router.

    Loads skills from business/skills/cybersecurity/skill.json
    and provides security-specific routing with red team activation gate.
    """

    @property
    def domain_prefix(self) -> str:
        return "security"

    def _get_domain_for_capability(self, capability_id: str) -> str | None:
        """Map security.* capability_id to domain string."""
        return CAPABILITY_TO_DOMAIN.get(capability_id)

    def _load_catalog(self) -> int:
        """Load security skills from cybersecurity skill.json."""
        catalog_path = self._find_catalog()
        if not catalog_path:
            log.warning("security_router.catalog_not_found")
            return 0

        try:
            with open(catalog_path) as f:
                data = json.load(f)

            for skill_data in data.get("skills", []):
                skill = SkillMeta(
                    id=skill_data["id"],
                    name=skill_data["name"],
                    domain=skill_data["domain"],
                    subdomain=skill_data.get("subdomain", ""),
                    description=skill_data.get("description", ""),
                    risk_level=skill_data.get("risk_level", "low"),
                    confidence_weight=skill_data.get("confidence_weight", 0.8),
                    tool_requirements=skill_data.get("tool_requirements", []),
                    requires_activation=skill_data.get("requires_activation", False),
                    expected_output_type=skill_data.get("expected_output_type", "report"),
                    tags=skill_data.get("tags", []),
                )
                self._skills[skill.id] = skill

            log.info("security_router.loaded",
                     skills=len(self._skills),
                     path=str(catalog_path))
            return len(self._skills)

        except Exception as e:
            log.error("security_router.load_failed", err=str(e)[:80])
            return 0

    def _find_catalog(self) -> Path | None:
        """Find the cybersecurity skill.json catalog."""
        # Try relative to project root
        candidates = [
            Path(__file__).parent.parent.parent / "business" / "skills" / "cybersecurity" / "skill.json",
            Path(os.getcwd()) / "business" / "skills" / "cybersecurity" / "skill.json",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def get_routing_context(self, capability_id: str, goal: str = "") -> dict[str, Any]:
        """
        Full routing context with security-specific logic.

        Overrides base to add:
        - Red team activation gate
        - Pack status information
        - Specialist pack mapping
        """
        domain = self._get_domain_for_capability(capability_id)
        if not domain:
            return {"matched": False, "capability_id": capability_id}

        skills = self.resolve(capability_id, goal)
        pack_id = DOMAIN_TO_PACK.get(domain, "")

        # Check pack activation status
        pack_active = False
        requires_activation = (domain == "red_team")
        blocked = False
        block_reason = None

        try:
            from core.agents.canonical_agents import SPECIALIST_PACKS
            pack = SPECIALIST_PACKS.get(pack_id)
            if pack:
                pack_active = pack.active
        except Exception:
            pass  # fail-open

        # Red team gate: block if pack not activated
        if domain == "red_team" and not pack_active:
            blocked = True
            block_reason = "Red team pack 'red_team_ethical' not activated — requires explicit activation via Safety Guardian"

        return {
            "matched": True,
            "capability_id": capability_id,
            "domain": domain,
            "router": self.domain_prefix,
            "specialist_pack": pack_id,
            "pack_active": pack_active,
            "requires_activation": requires_activation,
            "skills_count": len(skills),
            "top_skills": [s.to_dict() for s in skills[:5]],
            "blocked": blocked,
            "block_reason": block_reason,
        }


# ── Singleton ──

_security_router: SecuritySkillRouter | None = None


def get_security_skill_router() -> SecuritySkillRouter:
    """Get singleton security skill router."""
    global _security_router
    if _security_router is None:
        _security_router = SecuritySkillRouter()
        _security_router.load()
    return _security_router


# ── Auto-register on import ──
register_domain_router(get_security_skill_router())
