"""
bea_mcp/github_mcp_adapter.py — GitHub MCP sidecar adapter.

Registers the github-mcp sidecar into Bea's MCPRegistry.
Read tools are open; all write tools require approval.

Feature flag : GITHUB_MCP_ENABLED=true
Sidecar URL  : GITHUB_MCP_URL (default: http://github-mcp:3000)

Security:
  - GITHUB_TOKEN lives in the sidecar env only, never in bea_core
  - Write tools: requires_approval=True (create_issue, create_pr, push_files)
  - disable: GITHUB_MCP_ENABLED=false (default)

NOTE: This module is in bea_mcp/ (not mcp/) to avoid namespace collision
with the mcp pip package (MCP SDK).
"""
from __future__ import annotations

import structlog

log = structlog.get_logger("mcp.github_adapter")

# Tools definition: (tool_id, name, description, risk, approval, tags, schema)
_GITHUB_TOOLS = [
    (
        "github::search_code",
        "github_search_code",
        "Search code across GitHub repositories.",
        "low", False,
        ["github", "search", "code"],
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "GitHub code search query"},
                "repo": {"type": "string", "description": "Optional: owner/repo filter"},
            },
            "required": ["query"],
        },
    ),
    (
        "github::list_issues",
        "github_list_issues",
        "List open issues for a GitHub repository.",
        "low", False,
        ["github", "issues", "read"],
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository (owner/repo)"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["repo"],
        },
    ),
    (
        "github::create_issue",
        "github_create_issue",
        "Create a new issue in a GitHub repository. Requires approval.",
        "medium", True,
        ["github", "issues", "write"],
        {
            "type": "object",
            "properties": {
                "repo":  {"type": "string", "description": "Repository (owner/repo)"},
                "title": {"type": "string", "description": "Issue title"},
                "body":  {"type": "string", "description": "Issue body (markdown)"},
                "labels": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            "required": ["repo", "title"],
        },
    ),
    (
        "github::create_pr",
        "github_create_pr",
        "Create a pull request. High-risk write operation — requires approval.",
        "high", True,
        ["github", "pr", "write"],
        {
            "type": "object",
            "properties": {
                "repo":  {"type": "string", "description": "Repository (owner/repo)"},
                "title": {"type": "string", "description": "PR title"},
                "body":  {"type": "string", "description": "PR description"},
                "head":  {"type": "string", "description": "Head branch"},
                "base":  {"type": "string", "description": "Base branch", "default": "main"},
            },
            "required": ["repo", "title", "head"],
        },
    ),
    (
        "github::push_files",
        "github_push_files",
        "Push file changes to a GitHub repository. High-risk — requires approval.",
        "high", True,
        ["github", "files", "write"],
        {
            "type": "object",
            "properties": {
                "repo":    {"type": "string", "description": "Repository (owner/repo)"},
                "branch":  {"type": "string", "description": "Target branch"},
                "message": {"type": "string", "description": "Commit message"},
                "files": {
                    "type": "array",
                    "description": "Files to push",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path":    {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            "required": ["repo", "branch", "message", "files"],
        },
    ),
]


def register_github_mcp(registry, settings) -> bool:
    """
    Register the GitHub MCP sidecar in the Bea MCPRegistry.

    Returns:
        True if registered, False if disabled or already registered.
    """
    if not getattr(settings, "github_mcp_enabled", False):
        log.debug("github_mcp_disabled", reason="GITHUB_MCP_ENABLED not set")
        return False

    if registry.get_server("github-mcp") is not None:
        log.debug("github_mcp_already_registered")
        return True

    from integrations.mcp.mcp_models import MCPServer, MCPTool

    url = getattr(settings, "github_mcp_url", "http://github-mcp:3000")

    server = MCPServer(
        server_id="github-mcp",
        name="GitHub MCP Server",
        endpoint=url,
        transport="http",
        capabilities=["search", "issues", "pulls", "files"],
        health_status="unknown",
        risk_level="high",
        requires_approval=False,  # per-tool gate below
        metadata={
            "provider": "github/github-mcp-server",
            "docs": "https://github.com/github/github-mcp-server",
            "note": "GITHUB_TOKEN must be set in sidecar env only",
        },
    )
    registry.register_server(server)

    for (tool_id, name, desc, risk, approval, tags, schema) in _GITHUB_TOOLS:
        registry.register_tool(MCPTool(
            tool_id=tool_id,
            server_id="github-mcp",
            name=name,
            description=desc,
            input_schema=schema,
            risk_level=risk,
            requires_approval=approval,
            tags=tags,
        ))

    log.info(
        "github_mcp_registered",
        server_id="github-mcp",
        url=url,
        tools=[t[0] for t in _GITHUB_TOOLS],
    )
    return True


def unregister_github_mcp(registry) -> bool:
    """Remove GitHub MCP registration."""
    return registry.unregister_server("github-mcp")
