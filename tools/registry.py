"""
ToolRegistry — registre singleton de tous les outils BEATool de Béa.
"""
from __future__ import annotations

import logging

from tools.base import BEATool
from tools.result import ToolResult

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, BEATool] = {}


def register(tool: BEATool) -> None:
    """Enregistre une instance d'outil dans le registre global."""
    if tool.name in _REGISTRY:
        logger.warning("Tool '%s' already registered — overwriting", tool.name)
    _REGISTRY[tool.name] = tool
    logger.debug("Registered tool: %s", tool.name)


def get(name: str) -> BEATool | None:
    """Récupère un outil par son nom. Retourne None si non trouvé."""
    return _REGISTRY.get(name)


def get_or_raise(name: str) -> BEATool:
    """Récupère un outil par son nom. Lève KeyError si non trouvé."""
    tool = _REGISTRY.get(name)
    if tool is None:
        available = list(_REGISTRY.keys())
        raise KeyError(f"Tool '{name}' not found. Available: {available}")
    return tool


def list_tools() -> list[BEATool]:
    """Retourne tous les outils enregistrés."""
    return list(_REGISTRY.values())


def list_schemas() -> list[dict]:
    """Retourne les schémas de tous les outils (pour injection LLM)."""
    return [tool.to_schema_dict() for tool in _REGISTRY.values()]


async def dispatch(name: str, raw_input: dict, context: dict | None = None) -> ToolResult:
    """
    Dispatch principal : trouve l'outil par nom et l'exécute.
    Remplace progressivement executor/capability_dispatch.py.
    """
    tool = get(name)
    if tool is None:
        return ToolResult.fail(f"Unknown tool: '{name}'")
    return await tool(raw_input, context)


def reset() -> None:
    """Vide le registre (usage tests uniquement)."""
    _REGISTRY.clear()
