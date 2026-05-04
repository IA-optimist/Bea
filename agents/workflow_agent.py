"""
JARVIS MAX — WorkflowAgent
Agent spécialisé dans la création et la gestion des workflows.

Deux rôles :
  1. Parser le message utilisateur pour extraire une définition de workflow
  2. Déléguer la création + exécution à WorkflowEngine

Utilisé par JarvisOrchestrator quand l'intent est "workflow" (manuel)
ou en réponse à des commandes /workflow.

Interface :
    agent = WorkflowAgent(settings)
    result = await agent.create_from_text(user_input, emit)
    result = await agent.run_workflow(wf_id, emit)
"""
from __future__ import annotations

import json
import asyncio
import structlog
from typing import Callable, Awaitable

log = structlog.get_logger()
CB = Callable[[str], Awaitable[None]]

# Agents valides pour les étapes d'un workflow
_VALID_AGENTS = {
    "scout-research",
    "shadow-advisor",
    "map-planner",
    "forge-builder",
    "lens-reviewer",
    "vault-memory",
    "pulse-ops",
    "night-worker",
}

# Template par défaut quand le LLM échoue
_FALLBACK_WORKFLOW = {
    "name":        "generic_task",
    "description": "",
    "trigger":     "manual",
    "steps": [
        {"agent": "scout-research", "task": "Analyser la demande"},
        {"agent": "shadow-advisor", "task": "Proposer des alternatives"},
        {"agent": "lens-reviewer",  "task": "Valider les résultats"},
    ],
}


class WorkflowAgent:
    """
    Agent de gestion de workflows.
    Peut créer un workflow depuis du texte libre ou en exécuter un existant.
    """

    def __init__(self, settings):
        self.s = settings

    # ── Création depuis texte ─────────────────────────────────

    async def create_from_text(
        self,
        user_input: str,
        emit: CB | None = None,
    ) -> dict:
        """
        Analyse le texte utilisateur et crée un workflow.
        Retourne {"workflow_id": ..., "workflow": {...}, "status": "created"|"error"}.
        """
        _emit = emit or (lambda m: asyncio.sleep(0))

        await _emit("[WorkflowAgent] Analyse de la demande...")

        # 1. Essayer de parser via LLM
        wf_def = await self._parse_with_llm(user_input)

        # 2. Fallback si LLM échoue
        if not wf_def:
            wf_def = dict(_FALLBACK_WORKFLOW)
            wf_def["description"] = user_input[:200]
            wf_def["name"]        = self._extract_name(user_input)
            await _emit("[WorkflowAgent] LLM indisponible — template générique utilisé")

        # 3. Valider et nettoyer les steps
        wf_def = self._sanitize(wf_def, user_input)

        # 4. Créer via WorkflowEngine
        from workflow.workflow_engine import WorkflowEngine
        engine = WorkflowEngine(self.s)
        try:
            wf_id = await engine.create(wf_def)
            await _emit(f"[WorkflowAgent] Workflow créé : {wf_def['name']} (id={wf_id})")
            log.info("workflow_agent_created", id=wf_id, name=wf_def["name"])
            return {"workflow_id": wf_id, "workflow": wf_def, "status": "created"}
        except Exception as e:
            log.error("workflow_agent_create_failed", err=str(e))
            await _emit(f"[WorkflowAgent] Erreur création : {str(e)[:150]}")
            return {"workflow_id": None, "workflow": wf_def, "status": "error", "error": str(e)}

    # ── Exécution d'un workflow existant ─────────────────────

    async def run_workflow(
        self,
        wf_id: str,
        emit: CB | None = None,
        extra_context: str = "",
    ) -> dict:
        """
        Exécute un workflow par son ID.
        Retourne le rapport d'exécution de WorkflowEngine.
        """
        from workflow.workflow_engine import WorkflowEngine
        engine = WorkflowEngine(self.s)
        return await engine.execute(wf_id, emit=emit, extra_context=extra_context)

    # ── Parse LLM ────────────────────────────────────────────

    async def _parse_with_llm(self, user_input: str) -> dict | None:
        """
        Essaie de faire générer une définition de workflow par le LLM local.
        Retourne None si le LLM échoue ou timeout.
        """
        prompt = (
            "Tu es un assistant qui extrait des définitions de workflows depuis du texte.\n"
            "Retourne UNIQUEMENT un JSON valide avec cette structure :\n"
            '{"name":"<nom>","description":"<desc>","trigger":"manual",'
            '"steps":[{"agent":"<agent>","task":"<tache>"}]}\n'
            f"Agents disponibles : {', '.join(sorted(_VALID_AGENTS))}\n\n"
            f"Texte : {user_input[:400]}"
        )

        try:
            llm = self.s.get_llm("fast")
            from langchain_core.messages import HumanMessage
            resp = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=30,
            )
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            if "name" in data and "steps" in data:
                return data
        except (asyncio.TimeoutError, json.JSONDecodeError):
            log.debug("workflow_agent_llm_failed", reason="timeout_or_parse")
        except Exception as e:
            log.debug("workflow_agent_llm_failed", err=str(e)[:80])
        return None

    # ── Utilitaires ───────────────────────────────────────────

    @staticmethod
    def _extract_name(text: str) -> str:
        """Génère un nom court depuis le texte (snake_case, max 30 chars)."""
        import re
        import unicodedata
        # Normaliser accents
        normalized = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode()
        # Prendre les 4 premiers mots
        words = re.findall(r"[a-zA-Z]+", normalized)[:4]
        name  = "_".join(w.lower() for w in words) if words else "workflow"
        return name[:30]

    @staticmethod
    def _sanitize(wf_def: dict, user_input: str) -> dict:
        """
        Nettoie et valide la définition de workflow :
        - Remplace les agents invalides par scout-research
        - Assure la présence de description
        - Corrige le trigger si invalide
        """
        steps = wf_def.get("steps", [])
        cleaned_steps = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            agent = s.get("agent", "scout-research")
            if agent not in _VALID_AGENTS:
                log.warning("workflow_invalid_agent", agent=agent, fallback="scout-research")
                agent = "scout-research"
            cleaned_steps.append({
                "agent":    agent,
                "task":     s.get("task", user_input[:100]),
                "on_error": s.get("on_error", "continue"),
            })

        if not cleaned_steps:
            cleaned_steps = [
                {"agent": "scout-research", "task": user_input[:100], "on_error": "continue"}
            ]

        wf_def["steps"]       = cleaned_steps
        wf_def["description"] = wf_def.get("description") or user_input[:200]

        # Valider trigger
        trigger = wf_def.get("trigger", "manual")
        t_type  = trigger.split()[0] if trigger else "manual"
        if t_type not in {"manual", "cron", "event"}:
            wf_def["trigger"] = "manual"

        return wf_def

    # ── Listing ───────────────────────────────────────────────

    def list_workflows(self) -> list[dict]:
        """Liste tous les workflows disponibles."""
        from workflow.workflow_engine import WorkflowEngine
        return WorkflowEngine(self.s).list_workflows()
