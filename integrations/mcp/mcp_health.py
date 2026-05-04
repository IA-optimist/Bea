"""
integrations/mcp/mcp_health.py — Periodic MCP server health monitoring.
"""
from __future__ import annotations
import structlog
from integrations.mcp.mcp_registry import get_mcp_registry
from integrations.mcp.mcp_adapter import MCPAdapter

log = structlog.get_logger("mcp.health")


async def check_all_servers(adapter: MCPAdapter = None) -> dict:
    """Check health of all registered MCP servers. Returns status map."""
    registry = get_mcp_registry()
    adapter = adapter or MCPAdapter(registry)
    results = {}
    for server in registry.list_servers():
        status = await adapter.check_health(server.server_id)
        results[server.server_id] = status
    if results:
        log.info("mcp_health_sweep", results=results)
    return results
