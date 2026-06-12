"""
bea_mcp/qdrant_mcp_adapter.py — Qdrant MCP sidecar adapter.

Registers the qdrant-mcp sidecar into Bea's MCPRegistry so that
agents can query/upsert vectors via the standard MCP tool invocation path.

Feature flag : QDRANT_MCP_ENABLED=true
Sidecar URL  : QDRANT_MCP_URL (default: http://qdrant-mcp:8000)

NOTE: This module is in bea_mcp/ (not mcp/) to avoid namespace collision
with the mcp pip package (MCP SDK).
"""
from __future__ import annotations

import structlog

log = structlog.get_logger("mcp.qdrant_adapter")


def register_qdrant_mcp(registry, settings) -> bool:
    """
    Register the Qdrant MCP sidecar in the Bea MCPRegistry.

    Args:
        registry: MCPRegistry instance (from integrations.mcp.mcp_registry)
        settings: Settings instance (from config.settings)

    Returns:
        True if registered, False if disabled or already registered.
    """
    if not getattr(settings, "qdrant_mcp_enabled", False):
        log.debug("qdrant_mcp_disabled", reason="QDRANT_MCP_ENABLED not set")
        return False

    # Avoid double registration
    if registry.get_server("qdrant-mcp") is not None:
        log.debug("qdrant_mcp_already_registered")
        return True

    from integrations.mcp.mcp_models import MCPServer, MCPTool

    url = getattr(settings, "qdrant_mcp_url", "http://qdrant-mcp:8000")

    # Register sidecar server
    server = MCPServer(
        server_id="qdrant-mcp",
        name="Qdrant Vector Memory (MCP)",
        endpoint=url,
        transport="http",
        capabilities=["search", "upsert", "delete"],
        health_status="unknown",
        risk_level="medium",
        requires_approval=False,
        metadata={
            "provider": "qdrant/mcp-server-qdrant",
            "collection": "bea_unified_memory",
            "docs": "https://github.com/qdrant/mcp-server-qdrant",
        },
    )
    registry.register_server(server)

    # Register search tool
    registry.register_tool(MCPTool(
        tool_id="qdrant::search",
        server_id="qdrant-mcp",
        name="qdrant_search",
        description=(
            "Search Bea's Qdrant vector memory. "
            "Returns the top_k most similar documents to the query."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "collection": {
                    "type": "string",
                    "description": "Qdrant collection name",
                    "default": "bea_unified_memory",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["query"],
        },
        risk_level="low",
        requires_approval=False,
        tags=["memory", "search", "qdrant", "vector"],
    ))

    # Register upsert tool
    registry.register_tool(MCPTool(
        tool_id="qdrant::upsert",
        server_id="qdrant-mcp",
        name="qdrant_upsert",
        description=(
            "Store a document in Bea's Qdrant vector memory. "
            "The document is embedded and persisted for future searches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Document text to store",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata (source, tags, mission_id, ...)",
                    "default": {},
                },
                "collection": {
                    "type": "string",
                    "description": "Qdrant collection name",
                    "default": "bea_unified_memory",
                },
            },
            "required": ["text"],
        },
        risk_level="medium",
        requires_approval=False,
        tags=["memory", "upsert", "qdrant", "vector"],
    ))

    log.info(
        "qdrant_mcp_registered",
        server_id="qdrant-mcp",
        url=url,
        tools=["qdrant::search", "qdrant::upsert"],
    )
    return True


def unregister_qdrant_mcp(registry) -> bool:
    """Remove Qdrant MCP registration (e.g. on settings change or shutdown)."""
    return registry.unregister_server("qdrant-mcp")
