"""
BEA MAX — OpenHandsAgent (Phase 11)
Agent Worker Délégué.
Permet à l'orchestrateur BeaMax de déporter l'écriture du code
vers le système OpenHands (Official Repo) via son interface CLI Headless.
"""
from __future__ import annotations
import time
import structlog
from agents.crew import BaseAgent
from core.state import BeaSession
from adapters.openhands_client import OpenHandsLocalClient

log = structlog.get_logger()

class OpenHandsAgent(BaseAgent):
    name = "openhands-agent"
    role = "builder" # Agent spécialisé dans la construction logicielle de A à Z
    timeout_s = 3600 # Très long timeout, un run OpenHands peut durer 1 heure

    def system_prompt(self) -> str:
        return "" # Géré nativement par OpenHands

    def user_message(self, session: BeaSession) -> str:
        return "" # Géré nativement par OpenHands

    async def run(self, session: BeaSession) -> str:
        t0 = time.monotonic()
        log.info("openhands_agent_start", mission_id=session.session_id)

        try:
            client = OpenHandsLocalClient()
            # On prend la mission globale s'il n'y a pas d'instruction hyper spécifique
            # Idéalement, le Planner de BeaMax devrait populer session.metadata["openhands_prompt"]
            mission_prompt = session.metadata.get("openhands_prompt", session.mission_summary or session.user_input)

            # Récupération du workspace commun
            workspace = session.metadata.get("workspace_path", "C:/Users/maxen/Documents/beamax/workspace")

            # Délégation de la tâche à OpenHands
            success, raw_output = await client.run_delegated_mission(mission_prompt, workspace)

            ms = int((time.monotonic() - t0) * 1000)

            if success:
                summary = f"✅ OpenHands a manipulé le projet avec succès. Derniers logs:\n{raw_output[-500:]}"
                session.set_output(self.name, summary, success=True, ms=ms)
            else:
                summary = f"❌ OpenHands a lamentablement échoué:\n{raw_output[-500:]}"
                session.set_output(self.name, summary, success=False, error=summary, ms=ms)

            log.info("openhands_agent_done", success=success, ms=ms)
            return summary

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            log.exception("openhands_agent_crashed", sid=session.session_id)
            session.set_output(self.name, "", success=False, error=str(e), ms=ms)
            return str(e)
