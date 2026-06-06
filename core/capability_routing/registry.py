"""
core/capability_routing/registry.py — Provider Registry.

Maps capability_id → candidate providers, populated from real runtime
sources (capability graph, MCP registry, module manager, tool permissions).

Thread-safe. Fail-open. Never raises from populate().
"""
from __future__ import annotations

import threading
import time
from typing import Any

import structlog

from core.capability_routing.spec import (
    ProviderSpec, ProviderType, ProviderStatus,
)

log = structlog.get_logger("capability_routing.registry")


class ProviderRegistry:
    """
    Maps capability_id → list[ProviderSpec].

    Call populate() to scan runtime sources. Subsequent calls refresh.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # capability_id → list[ProviderSpec]
        self._providers: dict[str, list[ProviderSpec]] = {}
        self._last_populated: float = 0.0
        self._populate_count: int = 0

    # ── Public API ────────────────────────────────────────────

    def populate(self) -> dict[str, int]:
        """
        Scan all runtime sources and build provider index.

        Returns counts: {"agents": N, "mcp": N, "tools": N, "modules": N, "total": N}
        """
        counts = {"agents": 0, "mcp": 0, "tools": 0, "modules": 0}

        with self._lock:
            self._providers.clear()

        for source_name, source_fn in (
            ("agents", self._populate_agents),
            ("mcp", self._populate_mcp),
            ("tools", self._populate_tools),
            ("modules", self._populate_modules),
        ):
            try:
                n = source_fn()
                counts[source_name] = n
            except Exception as e:
                log.debug(f"capability_registry.{source_name}_failed", err=str(e)[:80])

        counts["total"] = sum(counts.values())
        self._last_populated = time.time()
        self._populate_count += 1

        log.info("capability_registry.populated", **counts)
        return counts

    def get_providers(self, capability_id: str) -> list[ProviderSpec]:
        """Get all providers that can satisfy a capability."""
        with self._lock:
            return list(self._providers.get(capability_id, []))

    def get_all_capabilities(self) -> list[str]:
        """List all known capability IDs."""
        with self._lock:
            return sorted(self._providers.keys())

    def find_providers_by_type(
        self, capability_id: str, provider_type: ProviderType
    ) -> list[ProviderSpec]:
        """Filter providers for a capability by type."""
        return [
            p for p in self.get_providers(capability_id)
            if p.provider_type == provider_type
        ]

    def find_available(self, capability_id: str) -> list[ProviderSpec]:
        """Get only currently available providers for a capability."""
        return [p for p in self.get_providers(capability_id) if p.is_available]

    def stats(self) -> dict[str, Any]:
        """Summary statistics."""
        with self._lock:
            total_providers = sum(len(v) for v in self._providers.values())
            by_type: dict[str, int] = {}
            for providers in self._providers.values():
                for p in providers:
                    by_type[p.provider_type.value] = by_type.get(p.provider_type.value, 0) + 1
            return {
                "capabilities": len(self._providers),
                "total_providers": total_providers,
                "by_type": by_type,
                "last_populated": self._last_populated,
                "populate_count": self._populate_count,
            }

    # ── Internal: register a provider ─────────────────────────

    def _register(self, spec: ProviderSpec) -> None:
        with self._lock:
            self._providers.setdefault(spec.capability_id, []).append(spec)

    # ── Source: Agents ────────────────────────────────────────

    def _populate_agents(self) -> int:
        """Build providers from agent capability graph."""
        try:
            from core.capability_graph import CapabilityGraph
            graph = CapabilityGraph()
            graph.populate_from_runtime()
        except Exception:
            return 0

        count = 0
        for cap in graph._capabilities.values():
            # Map graph constraints to ProviderStatus
            status = ProviderStatus.READY
            requires_approval = False
            risk = "low"
            for c in cap.constraints:
                if c == "disabled":
                    status = ProviderStatus.DISABLED
                elif c == "requires_approval":
                    requires_approval = True
                    status = ProviderStatus.APPROVAL_REQUIRED
                elif c.startswith("risk:"):
                    risk = c.split(":", 1)[1]

            # Each agent providing this capability is a separate provider
            for agent_id in cap.provided_by:
                self._register(ProviderSpec(
                    provider_id=f"agent:{agent_id}",
                    provider_type=ProviderType.AGENT,
                    capability_id=cap.id,
                    status=status,
                    readiness=1.0 if status == ProviderStatus.READY else 0.3,
                    reliability=cap.reliability,
                    confidence=0.8,  # Agents are purpose-built
                    requires_approval=requires_approval,
                    risk_level=risk,
                    dependencies=cap.required_tools,
                    estimated_latency_ms=cap.avg_latency_ms,
                    estimated_cost_usd=cap.avg_cost_usd,
                    constraints=cap.constraints,
                    metadata={"category": cap.category, "name": cap.name},
                ))
                count += 1

            # If no agent, register capability with the graph as source
            if not cap.provided_by and cap.category == "restricted-tool":
                self._register(ProviderSpec(
                    provider_id=f"tool:{cap.id}",
                    provider_type=ProviderType.TOOL,
                    capability_id=cap.id,
                    status=status,
                    readiness=1.0 if status == ProviderStatus.READY else 0.0,
                    reliability=cap.reliability,
                    confidence=1.0,  # Tool is the definitive provider
                    requires_approval=requires_approval,
                    risk_level=risk,
                    dependencies=cap.required_tools,
                    constraints=cap.constraints,
                    metadata={"category": cap.category, "name": cap.name},
                ))
                count += 1

        return count

    # ── Source: MCP Servers ───────────────────────────────────

    def _populate_mcp(self) -> int:
        """Build providers from MCP registry."""
        try:
            from core.mcp.mcp_registry import MCPRegistry
            registry = MCPRegistry()
        except Exception:
            return 0

        count = 0
        for server in registry.list_all():
            # Map MCP status → ProviderStatus
            if server.status == "disabled":
                status = ProviderStatus.DISABLED
            elif server.status == "needs_setup":
                status = ProviderStatus.NOT_CONFIGURED
            elif server.requires_approval:
                status = ProviderStatus.APPROVAL_REQUIRED
            else:
                status = ProviderStatus.READY

            missing = [s for s in (server.required_secrets or [])
                       if s not in (server.env_vars or {})]

            # Each MCP server is a provider for its own capability domain
            cap_id = f"mcp.{server.id}"
            self._register(ProviderSpec(
                provider_id=f"mcp:{server.id}",
                provider_type=ProviderType.MCP,
                capability_id=cap_id,
                status=status,
                readiness=0.9 if status == ProviderStatus.READY else 0.0,
                reliability=0.7,
                confidence=0.9,
                requires_approval=server.requires_approval,
                risk_level=server.risk_level or "low",
                dependencies=[t.get("name", "?") for t in server.discovered_tools],
                missing_dependencies=missing,
                estimated_latency_ms=500.0,  # MCP = network call
                constraints=[],
                metadata={"server_name": server.name, "category": server.category},
            ))
            count += 1

        return count

    # ── Source: Gated Tools ───────────────────────────────────

    def _populate_tools(self) -> int:
        """Build providers from tool permission registry."""
        try:
            from core.tool_permissions import get_tool_permissions
            perms = get_tool_permissions()
        except Exception:
            return 0

        count = 0
        for entry in perms.list_all():
            tool_name = entry.get("tool", entry.get("tool_name", ""))
            if not tool_name:
                continue

            cap_id = f"tool.{tool_name}"
            self._register(ProviderSpec(
                provider_id=f"tool:{tool_name}",
                provider_type=ProviderType.TOOL,
                capability_id=cap_id,
                status=ProviderStatus.APPROVAL_REQUIRED,
                readiness=1.0,
                reliability=1.0,
                confidence=1.0,
                requires_approval=True,
                risk_level="medium",
                constraints=["gated"],
            ))
            count += 1

        return count

    # ── Source: Module Manager ────────────────────────────────

    def _populate_modules(self) -> int:
        """Build providers from module manager."""
        try:
            from core.modules.module_manager import ModuleManager
            mgr = ModuleManager()
        except Exception:
            return 0

        count = 0
        for mod_type in ("agents", "skills", "connectors"):
            try:
                items = getattr(mgr, f"list_{mod_type}")()
            except Exception:
                log.debug("swallowed_exception", exc_info=True)
                continue
            for item in items:
                mid = item.get("id", item.get("name", ""))
                if not mid:
                    continue

                enabled = item.get("status") == "enabled"
                cap_id = f"module.{mod_type}.{mid}"
                self._register(ProviderSpec(
                    provider_id=f"module:{mod_type}:{mid}",
                    provider_type=ProviderType.MODULE,
                    capability_id=cap_id,
                    status=ProviderStatus.READY if enabled else ProviderStatus.DISABLED,
                    readiness=0.8 if enabled else 0.0,
                    reliability=0.7,
                    confidence=0.6,
                    metadata={"module_type": mod_type, "name": item.get("name", mid)},
                ))
                count += 1

        return count


# ── Singleton ─────────────────────────────────────────────────

_registry: ProviderRegistry | None = None
_registry_lock = threading.Lock()


def get_provider_registry(force_refresh: bool = False) -> ProviderRegistry:
    """Get or create the singleton provider registry."""
    global _registry
    if _registry is None or force_refresh:
        with _registry_lock:
            if _registry is None or force_refresh:
                _registry = ProviderRegistry()
                _registry.populate()
    return _registry
