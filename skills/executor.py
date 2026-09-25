"""Exécution d'une skill par nom."""
from __future__ import annotations

import logging

from skills.registry import get, initialize, list_skills
from skills.types import SkillStatus

logger = logging.getLogger(__name__)


async def run_skill(name: str, input: dict, context: dict | None = None) -> dict:
    """
    Exécute une skill par son nom.

    Returns:
        dict avec "success", "output", "error"
    """
    initialize()
    skill = get(name)

    if skill is None:
        available = [s.name for s in list_skills()]
        return {
            "success": False,
            "output": None,
            "error": f"Skill '{name}' introuvable. Disponibles: {available}",
        }

    if skill.status != SkillStatus.ACTIVE:
        return {
            "success": False,
            "output": None,
            "error": f"Skill '{name}' en erreur: {skill.error}",
        }

    # Essayer d'abord le tool_instance (BEATool)
    if skill.tool_instance is not None:
        from tools.result import ToolResult
        result: ToolResult = await skill.tool_instance(input, context)
        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
        }

    # Sinon, execute_fn directe
    if skill.execute_fn is not None:
        try:
            output = await skill.execute_fn(input, context)
            return {"success": True, "output": output, "error": None}
        except Exception as e:
            logger.exception("Skill '%s' execute_fn raised", name)
            return {"success": False, "output": None, "error": str(e)}

    # Pas d'implémentation → skill documentation-only
    return {
        "success": True,
        "output": f"Skill '{name}' est documentation-only (pas de skill.py). Description: {skill.description}",
        "error": None,
    }
