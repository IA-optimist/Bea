"""
core/tools_operational/tool_readiness.py — Check if operational tools are ready to execute.

Validates required secrets, configs, and connectivity.
"""
from __future__ import annotations

import os
import structlog

from core.tools_operational.tool_registry import get_tool_registry

log = structlog.get_logger("tools_operational.readiness")


def check_readiness(tool_id: str) -> dict:
    """
    Check if a specific tool has all dependencies satisfied.

    Returns:
        {
            "tool_id": str,
            "ready": bool,
            "enabled": bool,
            "missing_secrets": list[str],
            "missing_configs": list[str],
            "requires_approval": bool,
            "risk_level": str,
        }
    """
    tool = get_tool_registry().get(tool_id)
    if not tool:
        return {"tool_id": tool_id, "ready": False, "error": f"Unknown tool: {tool_id}"}

    missing_secrets = [s for s in tool.required_secrets if not os.environ.get(s)]
    missing_configs = [c for c in tool.required_configs if not os.environ.get(c)]

    return {
        "tool_id": tool_id,
        "ready": tool.enabled and not missing_secrets and not missing_configs,
        "enabled": tool.enabled,
        "missing_secrets": missing_secrets,
        "missing_configs": missing_configs,
        "requires_approval": tool.requires_approval,
        "risk_level": tool.risk_level,
    }


def check_all_readiness() -> list[dict]:
    """Check readiness of all registered tools."""
    tools = get_tool_registry().list_all()
    return [check_readiness(t.id) for t in tools]


def get_ready_tools() -> list[str]:
    """Return IDs of tools that are ready to execute."""
    return [r["tool_id"] for r in check_all_readiness() if r.get("ready")]


def get_blocked_tools() -> list[dict]:
    """Return tools that are not ready with reasons."""
    return [r for r in check_all_readiness() if not r.get("ready")]
