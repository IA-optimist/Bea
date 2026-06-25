"""
BEATool — interface unifiée pour tous les outils exécutables par les agents Béa.
Inspiré de src/Tool.ts (Claude Code source, 2026-03-31).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, TYPE_CHECKING

from pydantic import BaseModel

from tools.permissions import PermissionLevel
from tools.result import ToolResult as BEAToolResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BEATool(ABC):
    """
    Classe de base pour tous les outils Béa.

    Chaque sous-classe doit définir :
    - name        : identifiant unique snake_case
    - description : description courte pour le LLM
    - InputSchema : classe Pydantic qui valide l'input
    - permission  : niveau d'approbation requis
    - execute()   : logique d'exécution
    """

    name: ClassVar[str]
    description: ClassVar[str]
    permission: ClassVar[PermissionLevel] = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        """Schéma Pydantic de l'input. À surcharger dans chaque outil."""
        pass

    def validate_input(self, raw: dict) -> InputSchema:
        """Valide et parse l'input brut. Lève ValidationError si invalide."""
        return self.InputSchema(**raw)

    @abstractmethod
    async def execute(self, input: InputSchema, context: dict | None = None) -> BEAToolResult:
        """
        Exécute l'outil.

        Args:
            input   : input validé par InputSchema
            context : contexte de la mission (mission_id, principal_id, etc.)

        Returns:
            ToolResult avec success=True/False
        """
        ...

    async def __call__(self, raw_input: dict, context: dict | None = None) -> BEAToolResult:
        """Point d'entrée principal. Valide puis exécute."""
        try:
            validated = self.validate_input(raw_input)
        except Exception as e:
            return BEAToolResult.fail(f"Input validation error for {self.name}: {e}")

        try:
            result = await self.execute(validated, context)
        except Exception as e:
            logger.exception("Tool %s raised unexpected error", self.name)
            return BEAToolResult.fail(f"Tool {self.name} failed: {e}")

        return result

    def to_schema_dict(self) -> dict:
        """Retourne la description de l'outil pour injection dans le prompt LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "input_schema": self.InputSchema.model_json_schema(),
        }


# ── Backward-compat primitives (used by browser_tool, web_research_tool) ──────

class ToolRisk(str, Enum):
    SAFE       = "safe"        # Read-only, no side effects
    SUPERVISED = "supervised"  # Side effects, requires human oversight
    DANGEROUS  = "dangerous"   # Destructive / irreversible, opt-in only


@dataclass
class _LegacyToolResult:
    """Legacy ToolResult with data/meta fields. Import from tools.result for new code."""
    success: bool
    data:    Any  = None
    error:   str  = ""
    meta:    dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data":    self.data,
            "error":   self.error,
            "meta":    self.meta,
        }


ToolResult = _LegacyToolResult


class BaseTool:
    name: str      = "base"
    risk: ToolRisk = ToolRisk.SAFE

    async def close(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
