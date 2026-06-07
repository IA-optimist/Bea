"""
BEA MAX — Capability Graph
=================================
Maps what the system CAN do, WHO can do it, and HOW WELL.

Extends existing CapabilityIntelligence with a structured graph of:
  agent → capabilities → tools → constraints

Used for:
  - Capability-first mission routing (instead of role-based)
  - Gap detection (what capabilities are missing?)
  - Agent selection optimization
  - Capacity planning
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import structlog

log = structlog.get_logger()


@dataclass
class Capability:
    """A single capability the system can perform."""
    id: str = ""
    name: str = ""
    description: str = ""
    category: str = ""  # coding, analysis, communication, deployment, etc.
    required_tools: List[str] = field(default_factory=list)
    provided_by: List[str] = field(default_factory=list)  # agent IDs
    reliability: float = 0.0  # 0.0-1.0 from reputation data
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    constraints: List[str] = field(default_factory=list)  # e.g., "requires_approval", "offline_only"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "category": self.category, "required_tools": self.required_tools,
            "provided_by": self.provided_by,
            "reliability": round(self.reliability, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "avg_cost_usd": round(self.avg_cost_usd, 4),
            "constraints": self.constraints,
        }


class CapabilityGraph:
    """
    Maps system capabilities to agents and tools.

    Not a replacement for CapabilityIntelligence — it's a structured
    overlay that makes capability routing possible.
    """

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._agent_capabilities: Dict[str, Set[str]] = {}  # agent_id → set of cap_ids
        self._tool_capabilities: Dict[str, Set[str]] = {}   # tool_name → set of cap_ids

    def register_capability(self, cap: Capability) -> Capability:
        """Register a capability."""
        self._capabilities[cap.id] = cap
        for agent_id in cap.provided_by:
            self._agent_capabilities.setdefault(agent_id, set()).add(cap.id)
        for tool in cap.required_tools:
            self._tool_capabilities.setdefault(tool, set()).add(cap.id)
        return cap

    def find_agents_for_task(self, task_keywords: List[str]) -> List[Dict[str, Any]]:
        """Find agents that can handle a task based on capability matching."""
        matched_caps = []
        for cap in self._capabilities.values():
            score = 0
            for kw in task_keywords:
                kw_lower = kw.lower()
                if kw_lower in cap.name.lower() or kw_lower in cap.description.lower():
                    score += 1
                if kw_lower in cap.category.lower():
                    score += 2
            if score > 0:
                matched_caps.append((cap, score))
        # Rank agents by total capability match score
        agent_scores: Dict[str, float] = {}
        for cap, score in matched_caps:
            for agent_id in cap.provided_by:
                agent_scores[agent_id] = agent_scores.get(agent_id, 0) + score * cap.reliability
        return sorted(
            [{"agent_id": aid, "score": round(s, 2)} for aid, s in agent_scores.items()],
            key=lambda x: x["score"], reverse=True,
        )

    def get_agent_capabilities(self, agent_id: str) -> List[Capability]:
        cap_ids = self._agent_capabilities.get(agent_id, set())
        return [self._capabilities[cid] for cid in cap_ids if cid in self._capabilities]

    def find_gaps(self, required_capabilities: List[str]) -> List[str]:
        """Find capabilities that are required but not registered."""
        existing = set(self._capabilities.keys())
        return [c for c in required_capabilities if c not in existing]

    def get_capability(self, cap_id: str) -> Optional[Capability]:
        return self._capabilities.get(cap_id)

    def list_all(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in sorted(self._capabilities.values(), key=lambda c: c.reliability, reverse=True)]

    def stats(self) -> Dict[str, Any]:
        by_category = {}
        for c in self._capabilities.values():
            by_category[c.category] = by_category.get(c.category, 0) + 1
        return {
            "total_capabilities": len(self._capabilities),
            "total_agents": len(self._agent_capabilities),
            "total_tools": len(self._tool_capabilities),
            "by_category": by_category,
            "avg_reliability": round(
                sum(c.reliability for c in self._capabilities.values()) / max(len(self._capabilities), 1), 2
            ),
        }

    def update_reliability_from_reputation(self, reputation_tracker) -> None:
        """Pull reliability scores from agent reputation tracker."""
        try:
            for cap in self._capabilities.values():
                if cap.provided_by:
                    scores = [reputation_tracker.get_score(a) for a in cap.provided_by]
                    cap.reliability = sum(scores) / len(scores) if scores else 0.5
        except Exception as e:
            log.debug("capability_graph_reputation_sync_failed", err=str(e))

    # ── Auto-population from runtime ──

    def populate_from_runtime(self) -> Dict[str, int]:
        """Auto-populate graph from real runtime registries.

        Sources: agent tool access, MCP registry, module manager, tool
        permissions. Returns counts of what was populated.
        """
        counts = {"agents": 0, "tools": 0, "mcp": 0, "modules": 0}
        try:
            counts["agents"] = self._populate_agents()
        except Exception as e:
            log.debug("cap_graph_agents_failed", err=str(e))
        try:
            counts["tools"] = self._populate_tools()
        except Exception as e:
            log.debug("cap_graph_tools_failed", err=str(e))
        try:
            counts["mcp"] = self._populate_mcp()
        except Exception as e:
            log.debug("cap_graph_mcp_failed", err=str(e))
        try:
            counts["modules"] = self._populate_modules()
        except Exception as e:
            log.debug("cap_graph_modules_failed", err=str(e))
        return counts

    def _populate_agents(self) -> int:
        """Create capabilities from agent tool access matrix."""
        try:
            from agents.bea_team.tools import AGENT_TOOL_ACCESS
        except ImportError:
            return 0

        # Map agent roles to capability categories
        ROLE_CATEGORIES = {
            "bea-architect": ("architecture", "System design, code analysis, dependency mapping"),
            "bea-coder": ("coding", "Code writing, patching, git workflow"),
            "bea-reviewer": ("review", "Code review, quality analysis, regression detection"),
            "bea-qa": ("testing", "Test execution, test writing, regression detection"),
            "bea-devops": ("deployment", "Docker config, environment checks, dependency validation"),
            "bea-watcher": ("monitoring", "Log analysis, error pattern detection, system monitoring"),
        }

        count = 0
        for agent_id, tools in AGENT_TOOL_ACCESS.items():
            category, desc = ROLE_CATEGORIES.get(agent_id, ("general", agent_id))
            cap_id = f"cap-{agent_id}"
            if cap_id not in self._capabilities:
                self.register_capability(Capability(
                    id=cap_id,
                    name=f"{agent_id.replace('bea-', '').title()} capabilities",
                    description=desc,
                    category=category,
                    required_tools=sorted(tools),
                    provided_by=[agent_id],
                    reliability=0.8,  # Default, updated by reputation
                ))
                count += 1
        return count

    def _populate_tools(self) -> int:
        """Create capabilities from gated/restricted tools."""
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
            cap_id = f"cap-tool-{tool_name}"
            if cap_id not in self._capabilities:
                self.register_capability(Capability(
                    id=cap_id,
                    name=f"Tool: {tool_name}",
                    description=f"Access to gated tool '{tool_name}'",
                    category="restricted-tool",
                    required_tools=[tool_name],
                    constraints=["requires_approval"],
                    reliability=1.0,
                ))
                count += 1
        return count

    def _populate_mcp(self) -> int:
        """Create capabilities from MCP server registry."""
        try:
            from core.mcp.mcp_registry import MCPRegistry
            registry = MCPRegistry()
        except Exception:
            return 0

        count = 0
        for server in registry.list_all():
            cap_id = f"cap-mcp-{server.id}"
            if cap_id not in self._capabilities:
                tools = [t.get("name", "?") for t in server.discovered_tools]
                constraints = []
                if server.requires_approval:
                    constraints.append("requires_approval")
                if server.status == "disabled":
                    constraints.append("disabled")
                if server.risk_level in ("high", "critical"):
                    constraints.append(f"risk:{server.risk_level}")

                self.register_capability(Capability(
                    id=cap_id,
                    name=f"MCP: {server.name}",
                    description=server.description[:200],
                    category=server.category or "mcp",
                    required_tools=tools,
                    constraints=constraints,
                    reliability=0.7 if server.status == "enabled" else 0.3,
                ))
                count += 1
        return count

    def _populate_modules(self) -> int:
        """Create capabilities from module manager (agents, skills, connectors)."""
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
                cap_id = f"cap-mod-{mod_type}-{mid}"
                if cap_id not in self._capabilities:
                    self.register_capability(Capability(
                        id=cap_id,
                        name=f"{mod_type.rstrip('s').title()}: {item.get('name', mid)}",
                        description=item.get("description", item.get("purpose", ""))[:200],
                        category=mod_type,
                        reliability=0.8 if item.get("status") == "enabled" else 0.4,
                    ))
                    count += 1
        return count

    def record_mission_usage(self, mission_id: str, capabilities_used: List[str]) -> None:
        """Record that a mission used specific capabilities (enrichment)."""
        for cap_id in capabilities_used:
            cap = self._capabilities.get(cap_id)
            if cap:
                # Lightweight usage tracking — increment reliability slightly
                cap.reliability = min(1.0, cap.reliability + 0.01)
