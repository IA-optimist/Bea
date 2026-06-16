"""
core.connectors.hexstrike
=========================
Béa connector wrapping the hexstrike_v2 security tool suite.

Exposes 17 pentest tools (nmap, sqlmap, nuclei, metasploit, etc.) through
Béa's standard connector interface with approval gating and observability.

Usage by agents:
    from core.connectors.hexstrike import execute_security_tool, list_security_tools
    result = execute_security_tool("nmap", {"target": "192.168.1.0/24", "options": "-sV"})
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from core.connectors.contracts import ConnectorResult, ConnectorSpec

log = structlog.get_logger("bea.connectors.hexstrike")


# ── Lazy registry access (avoids import-time tool registration noise) ─────────

def _get_registry():
    from mcp.hexstrike_v2.registry import registry
    return registry


# ── Connector specs (one per risk tier) ──────────────────────────────────────

HEXSTRIKE_RECON_SPEC = ConnectorSpec(
    name="hexstrike_recon",
    category="security",
    description="Passive/active reconnaissance tools: nmap, masscan, amass, subfinder, dnsenum",
    input_schema={"tool": "str", "target": "str", "options": "str?"},
    output_schema={"tool": "str", "target": "str", "output": "str", "available": "bool"},
    risk_level="medium",
    requires_approval=True,
    retry_compatible=False,
    estimated_latency_ms=30_000,
    failure_modes=["tool_not_installed", "timeout", "network_error", "permission_denied"],
)

HEXSTRIKE_SCAN_SPEC = ConnectorSpec(
    name="hexstrike_scan",
    category="security",
    description="Vulnerability scanning: nikto, nuclei, wpscan",
    input_schema={"tool": "str", "target": "str", "options": "str?"},
    output_schema={"tool": "str", "target": "str", "output": "str", "available": "bool"},
    risk_level="medium",
    requires_approval=True,
    retry_compatible=False,
    estimated_latency_ms=60_000,
    failure_modes=["tool_not_installed", "timeout", "network_error"],
)

HEXSTRIKE_EXPLOIT_SPEC = ConnectorSpec(
    name="hexstrike_exploit",
    category="security",
    description="Exploitation tools: metasploit (msfconsole), OWASP ZAP, sqlmap",
    input_schema={"tool": "str", "target": "str", "options": "str?"},
    output_schema={"tool": "str", "target": "str", "output": "str", "available": "bool"},
    risk_level="high",
    requires_approval=True,
    retry_compatible=False,
    estimated_latency_ms=120_000,
    failure_modes=["tool_not_installed", "timeout", "requires_root", "network_error"],
)


# ── Public connector functions ────────────────────────────────────────────────

def list_security_tools(category: str | None = None) -> list[dict[str, Any]]:
    """List all registered hexstrike tools with their availability status."""
    registry = _get_registry()
    tools = registry.get_tools_by_category(category) if category else registry.get_all_tools()
    return [
        {
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "risk_level": t.risk_level,
            "requires_approval": t.requires_approval,
            "tags": t.tags,
            "parameters": t.parameters,
            "available": registry.is_available(t.name),
        }
        for t in tools
    ]


def check_tool_availability(tool_name: str) -> dict[str, Any]:
    """Check whether a specific tool is installed and available."""
    registry = _get_registry()
    tool = registry.get_tool(tool_name)
    if not tool:
        return {"tool": tool_name, "available": False, "error": "Tool not registered"}
    available = registry.is_available(tool_name)
    return {
        "tool": tool_name,
        "available": available,
        "category": tool.category,
        "risk_level": tool.risk_level,
        "requires_approval": tool.requires_approval,
    }


def execute_security_tool(
    tool_name: str,
    params: dict[str, Any],
    *,
    approved: bool = False,
) -> ConnectorResult:
    """
    Execute a hexstrike security tool through Béa's connector interface.

    Args:
        tool_name: Registered tool name (e.g. "nmap", "sqlmap", "nuclei")
        params:    Tool-specific parameters (always requires "target")
        approved:  Set True when operator has explicitly approved high-risk execution.
                   Raises ValueError for high-risk tools without approval.

    Returns:
        ConnectorResult with success/data/error/latency_ms
    """
    registry = _get_registry()
    tool = registry.get_tool(tool_name)

    if not tool:
        return ConnectorResult(
            success=False,
            error=f"Unknown tool '{tool_name}'. Call list_security_tools() to see registered tools.",
            connector="hexstrike",
        )

    if tool.requires_approval and not approved:
        return ConnectorResult(
            success=False,
            error=(
                f"Tool '{tool_name}' (risk={tool.risk_level}) requires operator approval. "
                "Pass approved=True after explicit human confirmation."
            ),
            connector="hexstrike",
        )

    if not registry.is_available(tool_name):
        return ConnectorResult(
            success=False,
            error=f"Tool '{tool_name}' not installed on this system. Install it and retry.",
            connector="hexstrike",
        )

    target = params.get("target", "")
    log.info(
        "hexstrike_execute",
        tool=tool_name,
        target=target[:60],
        risk=tool.risk_level,
    )

    t0 = time.perf_counter()
    try:
        raw = registry.execute(tool_name, params)
        latency_ms = (time.perf_counter() - t0) * 1000

        if raw.get("success"):
            return ConnectorResult(
                success=True,
                data=raw.get("data"),
                latency_ms=latency_ms,
                connector="hexstrike",
            )
        else:
            return ConnectorResult(
                success=False,
                error=raw.get("error", "Tool execution failed"),
                latency_ms=latency_ms,
                connector="hexstrike",
            )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        log.error("hexstrike_execute_error", tool=tool_name, err=str(exc))
        return ConnectorResult(
            success=False,
            error=str(exc),
            latency_ms=latency_ms,
            connector="hexstrike",
        )


def get_registry_stats() -> dict[str, Any]:
    """Return statistics about the hexstrike tool registry."""
    return _get_registry().get_stats()
