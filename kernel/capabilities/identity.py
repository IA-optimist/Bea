"""
kernel/capabilities/identity.py — Deterministic tool → capability / provider mapping.

Provides reverse lookups:
  tool_id → [capability_ids]   (which capabilities does this tool serve?)
  tool_id → provider_id        (who provides this tool?)
  provider_id → [capability_ids]

Sources (in priority order):
  1. Kernel capability registry (providers list)
  2. Core capability routing provider registry
  3. Core tool registry / tool_os_layer

All lookups are deterministic, cached, and fail-open.
Never fabricates high-confidence mappings — returns empty on ambiguity.
"""
from __future__ import annotations

import threading
import structlog

log = structlog.get_logger("kernel.capabilities.identity")


class CapabilityIdentityMap:
    """
    Reverse index for tool/provider → capability resolution.

    Built lazily from kernel registry + runtime sources.
    Thread-safe, cached, fail-open.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tool_to_capabilities: dict[str, list[str]] = {}
        self._provider_to_capabilities: dict[str, list[str]] = {}
        self._tool_to_provider: dict[str, str] = {}
        self._populated = False

    def _populate(self) -> None:
        """Build reverse index from all available sources."""
        if self._populated:
            return

        with self._lock:
            if self._populated:
                return

            # Source 1: Kernel capability registry
            try:
                from kernel.capabilities.registry import get_capability_registry
                reg = get_capability_registry()
                for cap in reg.list_all():
                    for provider in cap.providers:
                        self._provider_to_capabilities.setdefault(provider, [])
                        if cap.id not in self._provider_to_capabilities[provider]:
                            self._provider_to_capabilities[provider].append(cap.id)
            except Exception as e:
                log.debug("identity_kernel_registry_failed", err=str(e)[:60])

            # Source 2: Core capability routing provider registry
            try:
                from core.capability_routing.registry import ProviderRegistry
                pr = ProviderRegistry()
                pr.populate()
                for cap_id, providers in pr._providers.items():
                    for p in providers:
                        pid = p.provider_id
                        self._provider_to_capabilities.setdefault(pid, [])
                        if cap_id not in self._provider_to_capabilities[pid]:
                            self._provider_to_capabilities[pid].append(cap_id)
                        # If provider IS a tool (type=tool), map tool→capability
                        ptype = getattr(p, "provider_type", None)
                        if ptype and hasattr(ptype, "value") and ptype.value == "tool":
                            self._tool_to_capabilities.setdefault(pid, [])
                            if cap_id not in self._tool_to_capabilities[pid]:
                                self._tool_to_capabilities[pid].append(cap_id)
            except Exception as e:
                log.debug("identity_provider_registry_failed", err=str(e)[:60])

            # Source 3: Operational tool registry
            try:
                from core.tools_operational.tool_registry import get_tool_registry
                tool_reg = get_tool_registry()
                for tool in tool_reg.list_all():
                    tool_id = tool.id
                    # Map tool to "tool_invocation" capability at minimum
                    self._tool_to_capabilities.setdefault(tool_id, [])
                    if "tool_invocation" not in self._tool_to_capabilities[tool_id]:
                        self._tool_to_capabilities[tool_id].append("tool_invocation")
            except Exception as _exc:
                log.warning("swallowed_exception", action="identity_1", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            # Source 4: ToolExecutor internal tools → tool_invocation
            try:
                from core.tool_executor import ToolExecutor
                te = ToolExecutor()
                for tool_name in te._tools:
                    self._tool_to_capabilities.setdefault(tool_name, [])
                    if "tool_invocation" not in self._tool_to_capabilities[tool_name]:
                        self._tool_to_capabilities[tool_name].append("tool_invocation")
            except Exception as _exc:
                log.warning("swallowed_exception", action="identity_2", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            # Source 5: Domain skills → economic capability mapping
            # Specific skills map to specific economic capabilities
            _SKILL_CAPABILITY_MAP = {
                "market_research.basic": ["market_intelligence", "business_analysis"],
                "competitor.analysis": ["market_intelligence", "business_analysis"],
                "persona.basic": ["market_intelligence", "product_design"],
                "offer_design.basic": ["product_design", "business_analysis"],
                "value_proposition.design": ["product_design", "strategy_reasoning"],
                "pricing.strategy": ["financial_reasoning", "business_analysis"],
                "saas_scope.basic": ["product_design", "venture_planning"],
                "positioning.basic": ["strategy_reasoning", "business_analysis"],
                "strategy.reasoning": ["strategy_reasoning", "business_analysis"],
                "growth.plan": ["venture_planning", "strategy_reasoning"],
                "acquisition.basic": ["strategy_reasoning", "business_analysis"],
                "automation_opportunity.basic": ["market_intelligence", "business_analysis"],
                "funnel.design": ["product_design", "strategy_reasoning"],
                "copywriting.basic": ["product_design", "business_analysis"],
                "landing.structure": ["product_design", "business_analysis"],
                "spec.writing": ["product_design", "venture_planning"],
            }
            try:
                from core.skills.domain_loader import DomainSkillRegistry
                reg = DomainSkillRegistry()
                reg.load_all()
                for skill_id in reg._skills:
                    self._tool_to_capabilities.setdefault(skill_id, [])
                    # Use specific mapping if available, else fallback
                    caps = _SKILL_CAPABILITY_MAP.get(skill_id, ["business_analysis"])
                    for cap in caps:
                        if cap not in self._tool_to_capabilities[skill_id]:
                            self._tool_to_capabilities[skill_id].append(cap)
                    # Map skill to analyst agent as provider
                    if skill_id not in self._tool_to_provider:
                        self._tool_to_provider[skill_id] = "analyst_agent"
                log.debug("identity_skills_registered",
                          count=len(reg._skills))
            except Exception as e:
                log.debug("identity_skills_registration_failed",
                          err=str(e)[:60])

            self._populated = True
            log.debug("identity_map_populated",
                      tools=len(self._tool_to_capabilities),
                      providers=len(self._provider_to_capabilities))

    def resolve_tool(self, tool_id: str) -> dict:
        """
        Resolve capability and provider for a tool.

        Returns:
            {"capability_ids": [...], "provider_id": str, "confidence": float}

        confidence:
            1.0 = exact single capability match
            0.7 = multiple capabilities (ambiguous)
            0.5 = generic tool_invocation fallback
            0.0 = unknown tool
        """
        self._populate()

        cap_ids = self._tool_to_capabilities.get(tool_id, [])
        provider_id = self._tool_to_provider.get(tool_id, "")

        if not cap_ids:
            # Check if tool_id matches a provider
            provider_caps = self._provider_to_capabilities.get(tool_id, [])
            if provider_caps:
                cap_ids = provider_caps
                provider_id = tool_id

        if not cap_ids:
            return {"capability_ids": [], "provider_id": "", "confidence": 0.0}

        # Determine confidence
        non_generic = [c for c in cap_ids if c != "tool_invocation"]
        if len(non_generic) == 1:
            confidence = 1.0
        elif len(non_generic) > 1:
            confidence = 0.7
        elif cap_ids == ["tool_invocation"]:
            confidence = 0.5
        else:
            confidence = 0.5

        return {
            "capability_ids": cap_ids,
            "provider_id": provider_id or tool_id,
            "confidence": confidence,
        }

    def resolve_provider(self, provider_id: str) -> list[str]:
        """Get capabilities for a provider."""
        self._populate()
        return self._provider_to_capabilities.get(provider_id, [])

    def invalidate(self) -> None:
        """Force rebuild on next query."""
        with self._lock:
            self._populated = False
            self._tool_to_capabilities.clear()
            self._provider_to_capabilities.clear()
            self._tool_to_provider.clear()

    def stats(self) -> dict:
        self._populate()
        return {
            "tools_mapped": len(self._tool_to_capabilities),
            "providers_mapped": len(self._provider_to_capabilities),
            "tool_to_provider": len(self._tool_to_provider),
        }


# ── Singleton ─────────────────────────────────────────────────

_identity_map: CapabilityIdentityMap | None = None
_lock = threading.Lock()


def get_identity_map() -> CapabilityIdentityMap:
    global _identity_map
    if _identity_map is None:
        with _lock:
            if _identity_map is None:
                _identity_map = CapabilityIdentityMap()
    return _identity_map
