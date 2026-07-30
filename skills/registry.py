"""
SkillRegistry — registre singleton des skills chargées.
Distinct du ToolRegistry : les skills sont découvertes dynamiquement,
les tools sont enregistrés au démarrage.
"""
from __future__ import annotations

import logging

from skills.loader import discover_skills
from skills.types import LoadedSkill, SkillStatus

logger = logging.getLogger(__name__)

_SKILLS: dict[str, LoadedSkill] = {}
_initialized = False


def initialize(force: bool = False) -> None:
    """Découvre et charge toutes les skills. Idempotent sauf si force=True."""
    global _initialized
    if _initialized and not force:
        return
    _SKILLS.clear()
    for skill in discover_skills():
        _SKILLS[skill.name] = skill
    _initialized = True
    logger.info("SkillRegistry initialisé avec %d skills", len(_SKILLS))


def get(name: str) -> LoadedSkill | None:
    """Récupère une skill par son nom."""
    if not _initialized:
        initialize()
    return _SKILLS.get(name)


def list_skills(active_only: bool = True) -> list[LoadedSkill]:
    """Liste les skills, optionnellement filtrées sur le statut ACTIVE."""
    if not _initialized:
        initialize()
    if active_only:
        return [s for s in _SKILLS.values() if s.status == SkillStatus.ACTIVE]
    return list(_SKILLS.values())


def list_for_llm() -> list[dict]:
    """Retourne les descriptions des skills pour injection dans le prompt LLM."""
    if not _initialized:
        initialize()
    return [
        {
            "name": s.name,
            "description": s.description,
            "tags": s.metadata.tags,
            "requires_approval": s.metadata.requires_approval,
        }
        for s in list_skills(active_only=True)
    ]


def reload() -> None:
    """Recharge toutes les skills depuis le filesystem."""
    initialize(force=True)


def reset() -> None:
    """Vide le registre (tests uniquement)."""
    global _initialized
    _SKILLS.clear()
    _initialized = False
