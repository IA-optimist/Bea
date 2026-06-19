"""
plugins/plugin_models.py — Plugin data models.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class PluginMetadata:
    """Describes a registered plugin."""
    plugin_id: str
    name: str
    description: str
    version: str = "1.0.0"
    capability_type: str = "tool"  # tool / data_source / integration / notification
    required_config: list = field(default_factory=list)
    risk_level: str = "low"        # low / medium / high
    requires_approval: bool = False
    tags: list = field(default_factory=list)
    author: str = ""
    signature: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def canonical_payload(self) -> dict:
        """Return a dict suitable for signing (signature excluded)."""
        d = self.to_dict()
        d.pop("signature", None)
        return d


@dataclass
class PluginStatus:
    """Runtime health status of a plugin."""
    plugin_id: str
    health_status: str = "unknown"  # ok / degraded / unavailable / disabled
    last_checked: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)
