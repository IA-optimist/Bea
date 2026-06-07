"""
core/capabilities/registry.py — Capability registry for tool execution policy.

All tools must be registered here. Executor checks this registry before execution.
Unregistered tools are rejected. HIGH risk tools require approval.
"""
from __future__ import annotations

import structlog
from typing import Optional

from core.capabilities.schema import Capability

log = structlog.get_logger("bea.capabilities")


# ── Core tool capabilities ────────────────────────────────────────────────────

_CORE_CAPABILITIES: list[Capability] = [
    Capability(
        name="web_search",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=15,
        description="Search the web for information",
    ),
    Capability(
        name="web_fetch",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=15,
        description="Fetch and extract content from a URL",
    ),
    Capability(
        name="shell_execute",
        risk_level="HIGH",
        requires_approval=True,
        timeout_seconds=30,
        description="Execute shell commands on the host",
    ),
    Capability(
        name="file_write",
        risk_level="MEDIUM",
        requires_approval=False,
        timeout_seconds=10,
        description="Write or create files in workspace",
    ),
    Capability(
        name="file_read",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=10,
        description="Read files from workspace",
    ),
    Capability(
        name="memory_write",
        risk_level="MEDIUM",
        requires_approval=False,
        timeout_seconds=10,
        description="Write to Bea memory (vault, skills)",
    ),
    Capability(
        name="memory_read",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=10,
        description="Read from Bea memory",
    ),
    Capability(
        name="api_call",
        risk_level="MEDIUM",
        requires_approval=False,
        timeout_seconds=20,
        description="Make external API calls",
    ),
    Capability(
        name="code_execute",
        risk_level="HIGH",
        requires_approval=True,
        timeout_seconds=30,
        description="Execute Python code snippets",
    ),
    Capability(
        name="browser_navigate",
        risk_level="MEDIUM",
        requires_approval=False,
        timeout_seconds=30,
        description="Navigate browser to URL",
    ),

    # ── Business tools ────────────────────────────────────────────────────────────
    Capability(
        name="email_send",
        risk_level="MEDIUM",
        requires_approval=True,
        timeout_seconds=15,
        description="Send email via SMTP",
    ),
    Capability(
        name="http_request",
        risk_level="MEDIUM",
        requires_approval=False,
        timeout_seconds=15,
        description="Make HTTP requests to external APIs",
    ),
    Capability(
        name="http_test",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=10,
        description="Test HTTP endpoints for health and content",
    ),
    Capability(
        name="markdown_generate",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=5,
        description="Generate markdown documents",
    ),
    Capability(
        name="html_generate",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=5,
        description="Generate HTML pages",
    ),
    Capability(
        name="json_schema_generate",
        risk_level="LOW",
        requires_approval=False,
        timeout_seconds=5,
        description="Generate JSON Schema documents",
    ),
]


class CapabilityRegistry:
    """Singleton registry of tool capabilities."""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        # Register core capabilities
        for cap in _CORE_CAPABILITIES:
            self.register(cap)

    def register(self, capability: Capability) -> None:
        """Register a capability. Overwrites if already exists."""
        self._capabilities[capability.name] = capability
        log.debug("capability_registered", name=capability.name, risk=capability.risk_level)

    def get(self, name: str) -> Optional[Capability]:
        """Get a registered capability by name."""
        return self._capabilities.get(name)

    def is_registered(self, name: str) -> bool:
        return name in self._capabilities

    def check_permission(self, tool_name: str, agent_name: str = "") -> dict:
        """
        Check if a tool execution is permitted.

        Returns:
            {"allowed": bool, "requires_approval": bool, "reason": str, "capability": dict|None}
        """
        cap = self._capabilities.get(tool_name)
        if not cap:
            return {
                "allowed": False,
                "requires_approval": False,
                "reason": f"unregistered_tool: {tool_name}",
                "capability": None,
            }

        if agent_name and not cap.allows_agent(agent_name):
            return {
                "allowed": False,
                "requires_approval": False,
                "reason": f"agent_not_allowed: {agent_name} cannot use {tool_name}",
                "capability": cap.to_dict(),
            }

        return {
            "allowed": True,
            "requires_approval": cap.requires_approval,
            "reason": "ok",
            "capability": cap.to_dict(),
        }

    def list_all(self) -> list[dict]:
        """List all registered capabilities."""
        return [cap.to_dict() for cap in self._capabilities.values()]

    def list_by_risk(self, risk_level: str) -> list[dict]:
        """List capabilities filtered by risk level."""
        return [
            cap.to_dict() for cap in self._capabilities.values()
            if cap.risk_level == risk_level.upper()
        ]

    def stats(self) -> dict:
        """Summary statistics."""
        caps = list(self._capabilities.values())
        return {
            "total": len(caps),
            "by_risk": {
                "LOW": sum(1 for c in caps if c.risk_level == "LOW"),
                "MEDIUM": sum(1 for c in caps if c.risk_level == "MEDIUM"),
                "HIGH": sum(1 for c in caps if c.risk_level == "HIGH"),
            },
            "requiring_approval": sum(1 for c in caps if c.requires_approval),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: Optional[CapabilityRegistry] = None


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry
