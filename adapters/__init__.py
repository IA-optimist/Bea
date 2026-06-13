"""
BEA MAX — Framework Adapters
Adaptateurs pour les frameworks multi-agents externes.

Exports :
    CrewAIAdapter    — wraps BeaMax agents as CrewAI crew
    OpenAIAgentsAdapter — wraps BeaMax agents as OpenAI Agents SDK
    get_best_adapter  — factory retournant le meilleur adapter dispo
"""
from __future__ import annotations

import structlog
from typing import Any

log = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# BASE ADAPTER
# ═══════════════════════════════════════════════════════════════

class BaseAdapter:
    """Interface commune à tous les adapters."""
    name = "base"

    def is_available(self) -> bool:
        return False

    async def run(self, agents_plan: list[dict], session: Any) -> list[dict]:
        """Exécute le plan d'agents. Retourne une liste de résultats."""
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════
# CREWAI ADAPTER
# ═══════════════════════════════════════════════════════════════

class CrewAIAdapter(BaseAdapter):
    """
    Wraps BeaMax agents en agents CrewAI + tasks CrewAI.

    Chaque agent de `agents_plan` devient :
    - Un `crewai.Agent` avec le system_prompt de l'agent BeaMax
    - Une `crewai.Task` avec la description de la tâche

    Fallback transparent vers AgentCrew si CrewAI non disponible.
    """
    name = "crewai"

    def __init__(self, settings=None):
        self.s = settings
        self._crewai_available = self._check_crewai()

    def _check_crewai(self) -> bool:
        try:
            import crewai  # noqa: F401
            return True
        except ImportError:
            log.debug("crewai_not_available", adapter="crewai")
            return False

    def is_available(self) -> bool:
        return self._crewai_available

    async def run(self, agents_plan: list[dict], session: Any) -> list[dict]:
        """
        Exécute un plan via CrewAI.
        Retourne la liste des résultats par agent.
        """
        if not self._crewai_available:
            raise RuntimeError("CrewAI non disponible")

        try:
            import crewai
            from core.llm_factory import LLMFactory

            factory  = LLMFactory(self.s)
            llm      = factory.get_llm("research")  # LLM principal

            # Construire les agents CrewAI
            crew_agents = []
            crew_tasks  = []

            # Loader lazy de la crew BeaMax pour les prompts
            from config.settings import get_settings
            from agents.crew import AgentCrew
            bea_crew = AgentCrew(self.s or get_settings())

            for step in agents_plan:
                agent_name = step.get("agent", "")
                task_desc  = step.get("task", "")

                # Récupérer le system_prompt depuis l'agent BeaMax
                bea_agent = bea_crew.registry.get(agent_name)
                system_p = (
                    bea_agent.system_prompt()
                    if bea_agent else f"Tu es {agent_name}, agent BeaMax."
                )

                crew_agent = crewai.Agent(
                    role=agent_name,
                    goal=task_desc[:200],
                    backstory=system_p[:500],
                    llm=llm,
                    verbose=False,
                )
                crew_task = crewai.Task(
                    description=f"Mission: {session.mission_summary or session.user_input}\nTâche: {task_desc}",
                    agent=crew_agent,
                    expected_output="Résultat complet et structuré de la tâche",
                )
                crew_agents.append(crew_agent)
                crew_tasks.append(crew_task)

            # Créer et lancer le Crew
            crew = crewai.Crew(
                agents=crew_agents,
                tasks=crew_tasks,
                verbose=False,
                process=crewai.Process.sequential,
            )

            # Kick-off (sync dans CrewAI — run dans thread via asyncio)
            import asyncio
            loop   = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, crew.kickoff)

            log.info(
                "crewai_run_complete",
                agents=len(crew_agents),
                tasks=len(crew_tasks),
                sid=getattr(session, "session_id", ""),
            )

            return [{
                "adapter": "crewai",
                "agents":  [a.role for a in crew_agents],
                "result":  str(result)[:3000],
                "success": True,
            }]

        except Exception as e:
            log.error("crewai_run_failed", err=str(e)[:100])
            return [{"adapter": "crewai", "success": False, "error": str(e)[:200]}]


# ═══════════════════════════════════════════════════════════════
# OPENAI AGENTS ADAPTER
# ═══════════════════════════════════════════════════════════════

class OpenAIAgentsAdapter(BaseAdapter):
    """
    Wraps BeaMax agents en agents OpenAI Agents SDK.
    Utilise les handoffs inter-agents du SDK.

    SDK : openai-agents-python (local dans GitHub/)
    Fallback transparent vers AgentCrew si SDK non disponible.
    """
    name = "openai-agents"

    def __init__(self, settings=None):
        self.s = settings
        self._sdk_available = self._check_sdk()

    def _check_sdk(self) -> bool:
        try:
            import agents  # OpenAI Agents SDK  # noqa: F401
            return True
        except ImportError:
            try:
                import openai_agents  # noqa: F401
                return True
            except ImportError:
                log.debug("openai_agents_sdk_not_available")
                return False

    def is_available(self) -> bool:
        return self._sdk_available

    async def run(self, agents_plan: list[dict], session: Any) -> list[dict]:
        """Exécute un plan via OpenAI Agents SDK."""
        if not self._sdk_available:
            raise RuntimeError("OpenAI Agents SDK non disponible")

        try:
            # SDK import
            try:
                from agents import Agent, Runner, handoff
            except ImportError:
                from openai_agents import Agent, Runner, handoff  # type: ignore

            from config.settings import get_settings
            from agents.crew import AgentCrew as BeaCrewClass
            bea_crew = BeaCrewClass(self.s or get_settings())

            sdk_agents = []
            for step in agents_plan:
                agent_name = step.get("agent", "")
                task_desc  = step.get("task", "")
                bea_agent = bea_crew.registry.get(agent_name)
                instructions = (
                    bea_agent.system_prompt()
                    if bea_agent else f"Tu es {agent_name}."
                )
                sdk_agent = Agent(
                    name=agent_name,
                    instructions=instructions[:1500],
                    model="gpt-4o-mini",
                )
                sdk_agents.append((sdk_agent, task_desc))

            if not sdk_agents:
                return [{"adapter": "openai-agents", "success": False, "error": "Aucun agent"}]

            # Exécuter le premier agent avec la mission
            first_agent, first_task = sdk_agents[0]
            mission_text = (
                f"Mission : {session.mission_summary or session.user_input}\n"
                f"Tâche : {first_task}"
            )
            result = await Runner.run(first_agent, mission_text)

            log.info(
                "openai_agents_run_complete",
                agents=len(sdk_agents),
                sid=getattr(session, "session_id", ""),
            )

            return [{
                "adapter": "openai-agents",
                "agents":  [a.name for a, _ in sdk_agents],
                "result":  str(result.final_output)[:3000],
                "success": True,
            }]

        except Exception as e:
            log.error("openai_agents_run_failed", err=str(e)[:100])
            return [{"adapter": "openai-agents", "success": False, "error": str(e)[:200]}]


# ═══════════════════════════════════════════════════════════════
# BEA NATIVE ADAPTER (Fallback)
# ═══════════════════════════════════════════════════════════════

class BeaNativeAdapter(BaseAdapter):
    """Adapter natif BeaMax — toujours disponible, toujours fonctionnel."""
    name = "bea-native"

    def is_available(self) -> bool:
        return True

    async def run(self, agents_plan: list[dict], session: Any) -> list[dict]:
        from agents.parallel_executor import ParallelExecutor
        from config.settings import get_settings
        pex = ParallelExecutor(get_settings())
        await pex.run(session, agents_plan)
        return [
            {
                "adapter": "bea-native",
                "agent":   name,
                "success": out.success,
                "result":  out.content[:500] if out.success else "",
                "error":   getattr(out, "error", ""),
            }
            for name, out in session.outputs.items()
        ]


# ═══════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════

def get_best_adapter(settings=None, prefer: str = "auto") -> BaseAdapter:
    """
    Retourne le meilleur adapter disponible.

    prefer : "crewai" | "openai-agents" | "native" | "auto"
    """
    adapters = {
        "crewai":        CrewAIAdapter(settings),
        "openai-agents": OpenAIAgentsAdapter(settings),
        "native":        BeaNativeAdapter(),
    }

    if prefer != "auto" and prefer in adapters:
        candidate = adapters[prefer]
        if candidate.is_available():
            log.info("adapter_selected", name=prefer, reason="explicit")
            return candidate

    # Auto : priorité CrewAI > OpenAI Agents > Natif
    for name in ("crewai", "openai-agents", "native"):
        adapter = adapters[name]
        if adapter.is_available():
            log.info("adapter_selected", name=name, reason="auto")
            return adapter

    return BeaNativeAdapter()


__all__ = [
    "BaseAdapter",
    "CrewAIAdapter",
    "OpenAIAgentsAdapter",
    "BeaNativeAdapter",
    "get_best_adapter",
]
