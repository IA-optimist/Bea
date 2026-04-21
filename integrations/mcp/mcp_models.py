"""
integrations/mcp/mcp_models.py — MCP data models.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict


@dataclass
class MCPServer:
    """Registered MCP server."""
    server_id: str
    name: str
    endpoint: str                     # e.g. "http://localhost:3000"
    transport: str = "http"           # http / stdio / websocket
    capabilities: list = field(default_factory=list)
    health_status: str = "unknown"    # ok / degraded / unavailable / unknown
    risk_level: str = "low"           # low / medium / high
    requires_approval: bool = False
    metadata: dict = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""
    tool_id: str
    server_id: str
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    risk_level: str = "low"
    requires_approval: bool = False
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
