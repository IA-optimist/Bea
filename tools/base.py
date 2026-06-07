"""
BEA MAX — Base Tool primitives
BaseTool, ToolResult, ToolRisk — shared by all tool implementations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolRisk(str, Enum):
    SAFE       = "safe"        # Read-only, no side effects
    SUPERVISED = "supervised"  # Side effects, requires human oversight
    DANGEROUS  = "dangerous"   # Destructive / irreversible, opt-in only


@dataclass
class ToolResult:
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


class BaseTool:
    name: str      = "base"
    risk: ToolRisk = ToolRisk.SAFE

    async def close(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
