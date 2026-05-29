"""Public connector contract types.

Kept separate from concrete connector implementations so callers can depend on
stable schemas without importing the full connector runtime registry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ConnectorSpec:
    """Metadata for a connector."""

    name: str
    category: str
    description: str
    input_schema: dict
    output_schema: dict
    risk_level: str = "low"
    requires_approval: bool = False
    retry_compatible: bool = True
    estimated_latency_ms: int = 500
    failure_modes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConnectorResult:
    """Standardized connector output."""

    success: bool = False
    data: Any = None
    error: str = ""
    latency_ms: float = 0.0
    connector: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.success,
            "success": self.success,
            "data": self.data,
            "result": str(self.data)[:2000] if self.data else "",
            "error": self.error,
            "latency_ms": self.latency_ms,
            "output": str(self.data)[:2000] if self.data else "",
        }
