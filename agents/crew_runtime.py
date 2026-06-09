"""Runtime AgentCrew registry extracted from agents.crew.

This module owns the crew registry/dispatch class. It imports concrete agent
classes lazily from agents.crew during construction to keep legacy imports
compatible while reducing the original monolith.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agents.crew import BaseAgent
    from core.state import BeaSession

log = structlog.get_logger()
class AgentCrew:
    def __init__(self, settings):
        from agents.crew import (
            AtlasDirector,
            ForgeBuilderWithCritic,
            ImageAgent,
            LensReviewer,
            MapPlannerWithCritic,
            NightWorker,
            PulseOps,
            ScoutResearch,
            ShadowAdvisor,
            VaultMemory,
        )

        self.s = settings
        self.registry: dict[str, BaseAgent] = {
            "atlas-director": AtlasDirector(settings),
            "scout-research": ScoutResearch(settings),
            # Critic variants activés en production (1 round de révision)
            "map-planner":    MapPlannerWithCritic(settings),
            "forge-builder":  ForgeBuilderWithCritic(settings),
            "lens-reviewer":  LensReviewer(settings),
            "vault-memory":   VaultMemory(settings),
            "shadow-advisor": ShadowAdvisor(settings),
            "pulse-ops":      PulseOps(settings),
            "night-worker":   NightWorker(settings),
            # HuggingFace image generation agent
            "image-agent":    ImageAgent(settings),
        }
        self._register_v2_agents(settings)
        self.tools: dict = self._init_tools()

    def _init_tools(self) -> dict:
        """Initialise les outils disponibles pour les agents (BrowserTool, …)."""
        tools: dict = {}
        try:
            from tools.browser_tool import BrowserTool
            tools["browser"] = BrowserTool()
            log.info("tool_registered", name="browser")
        except Exception as e:
            log.warning("tool_init_failed", name="browser", err=str(e)[:80])
        return tools

    def _register_v2_agents(self, settings) -> None:
        """Enregistre les agents v2 (DebugAgent, RecoveryAgent, MonitoringAgent)."""
        for agent_name, module_path, class_name in [
            ("debug-agent",      "agents.debug_agent",      "DebugAgent"),
            ("recovery-agent",   "agents.recovery_agent",   "RecoveryAgent"),
            ("monitoring-agent", "agents.monitoring_agent", "MonitoringAgent"),
        ]:
            try:
                mod = __import__(module_path, fromlist=[class_name])
                cls = getattr(mod, class_name)
                self.registry[agent_name] = cls(settings)
                log.info("agent_registered", name=agent_name)
            except Exception as e:
                log.warning("agent_register_failed", name=agent_name, err=str(e)[:80])
        self._register_bea_team(settings)

    def _register_bea_team(self, settings) -> None:
        """Register bea-team agents (meta-level codebase agents). Fail-open."""
        try:
            from agents.bea_team import BEA_TEAM_AGENTS
            for agent_name, agent_cls in BEA_TEAM_AGENTS.items():
                try:
                    self.registry[agent_name] = agent_cls(settings)
                    log.info("agent_registered", name=agent_name, team="bea")
                except Exception as e:
                    log.warning("bea_team_agent_failed", name=agent_name, err=str(e)[:80])
        except Exception as e:
            log.debug("bea_team_import_skipped", err=str(e)[:80])
        self._register_catalog_agents(settings)

    def _register_catalog_agents(self, settings) -> None:
        """Register any agent from agents.registry.AGENT_CLASSES not yet in registry.
        Covers business layer agents (venture-builder, offer-designer, saas-builder…)."""
        try:
            from agents.registry import AGENT_CLASSES
            for agent_name, agent_cls in AGENT_CLASSES.items():
                if agent_name not in self.registry:
                    try:
                        self.registry[agent_name] = agent_cls(settings)
                        log.info("agent_registered", name=agent_name, team="catalog")
                    except Exception as e:
                        log.warning("catalog_agent_failed", name=agent_name, err=str(e)[:80])
        except Exception as e:
            log.debug("catalog_import_skipped", err=str(e)[:80])

    def discover(self, extra_agents=None) -> None:
        """Enregistre des agents supplementaires dynamiquement."""
        for agent in (extra_agents or []):
            self.registry[agent.name] = agent
            log.info("agent_discovered", name=agent.name)

    def list_agents(self) -> list:
        """Retourne la liste des agents enregistres avec leurs metadonnees."""
        return [
            {"name": name, "role": getattr(a, "role", "?"), "timeout": getattr(a, "timeout_s", "?")}
            for name, a in self.registry.items()
        ]

    async def run(self, name: str, session: BeaSession) -> str:
        agent = self.registry.get(name)
        if not agent:
            log.warning("unknown_agent", name=name)
            return ""
        return await agent.run(session)

    def add(self, agent: BaseAgent):
        """Enregistre un agent personnalisé (extensibilité)."""
        self.registry[agent.name] = agent
        log.info("agent_registered", name=agent.name)
