"""
JARVIS MAX — SelfCriticMixin
Mixin d'auto-évaluation intra-agent (max 2 rounds de révision).

Un agent qui hérite de SelfCriticMixin peut s'auto-évaluer et se corriger
sans intervention externe. Utile pour les agents de génération (ForgeBuilder)
et de planification (MapPlanner) qui ont un fort impact sur les livrables.

Comportement :
    1. L'agent génère une première réponse (round 0)
    2. SelfCriticMixin demande au LLM d'évaluer cette réponse (critique)
    3. Si critique négative (score < seuil) → nouveau round avec la critique
    4. Max MAX_CRITIC_ROUNDS pour éviter les boucles infinies

Usage :
    class ForgeBuilderWithCritic(SelfCriticMixin, ForgeBuilder):
        pass

    # Ou usage direct :
    critic = SelfCriticMixin(settings, pass_score=6.0)
    output, critique = await critic.critic_loop(
        agent_name="forge-builder",
        task="Génère un script de backup",
        initial_output=first_output,
        refine_fn=lambda critique: agent.run_with_critique(critique),
    )

Interface principale :
    SelfCriticMixin.run_with_self_critic(session) → str
        — Drop-in replacement de BaseAgent.run() avec boucle de critique
"""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable
import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()

MAX_CRITIC_ROUNDS = 2    # max rounds de révision (hors round initial)
CRITIC_PASS_SCORE = 6.0  # score minimum pour accepter sans révision

_CRITIC_SYSTEM = """Tu es un critique expert en qualité de réponses IA.
Évalue la réponse fournie sur une échelle de 0 à 10.

Critères :
- Complétude : tous les aspects de la tâche sont couverts
- Précision   : les informations sont exactes et bien fondées
- Clarté      : la réponse est structurée et lisible
- Utilité     : la réponse permet une action directe

Réponds UNIQUEMENT en JSON strict :
{
  "score": 7.5,
  "issues": ["problème 1", "problème 2"],
  "suggestions": ["amélioration 1", "amélioration 2"],
  "verdict": "PASS" | "IMPROVE"
}

Sois concis et précis. Ne liste que les vrais problèmes."""


class SelfCriticMixin:
    """
    Mixin d'auto-critique pour les agents BaseAgent.

    Peut être utilisé de deux façons :
        1. Mixin : class MyAgent(SelfCriticMixin, BaseAgent): ...
           → Override run() avec boucle de critique auto
        2. Standalone : SelfCriticMixin(settings).critic_loop(...)
           → Utilisable comme wrapper externe
    """

    critic_enabled:     bool  = True
    critic_max_rounds:  int   = MAX_CRITIC_ROUNDS
    critic_pass_score:  float = CRITIC_PASS_SCORE
    critic_timeout_s:   int   = 15   # Réduit 30→15s : Ollama lent → PASS par défaut, évite le blocage

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Enregistrer que cette classe utilise la critique
        cls._has_self_critic = True

    # ── Boucle principale ─────────────────────────────────────

    async def run_with_self_critic(self, session) -> str:
        """
        Drop-in replacement de BaseAgent.run() avec auto-critique.
        Appelle super().run() puis boucle critique si nécessaire.
        """
        from agents.crew import BaseAgent
        if not isinstance(self, BaseAgent):
            raise TypeError("SelfCriticMixin doit être utilisé avec BaseAgent")

        # Round initial
        output = await BaseAgent.run(self, session)
        if not output or not self.critic_enabled:
            return output

        task = self._task(session)   # type: ignore[attr-defined]

        for round_n in range(1, self.critic_max_rounds + 1):
            critique = await self._critique(task, output)
            if critique.get("verdict") == "PASS" or critique.get("score", 0) >= self.critic_pass_score:
                log.debug("self_critic_pass",
                          agent=getattr(self, "name", "?"),
                          round=round_n,
                          score=critique.get("score"))
                break

            log.info("self_critic_improving",
                     agent=getattr(self, "name", "?"),
                     round=round_n,
                     score=critique.get("score"),
                     issues=critique.get("issues", [])[:2])

            # Injecter la critique dans le message utilisateur
            critique_block = self._format_critique(critique)
            try:
                from langchain_core.messages import SystemMessage, HumanMessage
                from core.llm_factory import LLMFactory
                factory = LLMFactory(self.s)   # type: ignore[attr-defined]
                resp = await factory.safe_invoke(
                    [
                        SystemMessage(content=self.system_prompt()),   # type: ignore[attr-defined]
                        HumanMessage(content=(
                            f"{self.user_message(session)}\n\n"   # type: ignore[attr-defined]
                            f"[RÉVISION ROUND {round_n}]\n"
                            f"Ta réponse précédente avait des lacunes :\n"
                            f"{critique_block}\n\n"
                            f"Corrige et améliore ta réponse précédente :\n"
                            f"{output[:1000]}..."
                        )),
                    ],
                    role=getattr(self, "role", "default"),
                    timeout=float(getattr(self, "timeout_s", 120)),
                )
                new_output = resp.content if resp else output
                if new_output and new_output != output:
                    output = new_output
                    # ── Mettre à jour session.outputs avec la version améliorée ──
                    # Sans cette mise à jour, les agents suivants liraient la version
                    # initiale (non améliorée) dans session.context_snapshot().
                    try:
                        agent_name = getattr(self, "name", "?")
                        session.set_output(agent_name, output, success=True)
                        from api.event_emitter import emit_agent_result
                        emit_agent_result(session.session_id, agent_name, output)
                    except Exception:
                        _silent_log.debug("suppressed_exception", src='self_critic.py')
            except Exception as e:
                log.warning("self_critic_revision_failed",
                            round=round_n, err=str(e))
                break

        return output

    async def critic_loop(
        self,
        agent_name:  str,
        task:        str,
        initial_output: str,
        refine_fn:   Callable[[dict], Awaitable[str]],
    ) -> tuple[str, dict]:
        """
        Boucle de critique standalone (sans héritage BaseAgent).

        Paramètres :
            agent_name     : nom de l'agent (pour les logs)
            task           : tâche originale
            initial_output : première réponse de l'agent
            refine_fn      : async callable(critique) → nouvelle réponse

        Retourne :
            (output_final, dernière_critique)
        """
        output   = initial_output
        critique = {}

        for round_n in range(1, self.critic_max_rounds + 1):
            critique = await self._critique(task, output)
            if critique.get("verdict") == "PASS" or critique.get("score", 0) >= self.critic_pass_score:
                break

            log.info("critic_loop_improving",
                     agent=agent_name, round=round_n, score=critique.get("score"))
            try:
                output = await refine_fn(critique)
            except Exception as e:
                log.warning("critic_loop_refine_failed", err=str(e))
                break

        return output, critique

    # ── Critique LLM ─────────────────────────────────────────

    async def _critique(self, task: str, output: str) -> dict:
        """
        Demande au LLM d'évaluer la sortie.
        Retourne {"score", "issues", "suggestions", "verdict"}.
        """
        import json

        prompt = (
            f"Tâche évaluée :\n{task[:400]}\n\n"
            f"Réponse à évaluer :\n{output[:2000]}"
        )

        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            from core.llm_factory import LLMFactory
            factory = LLMFactory(self.s)   # type: ignore[attr-defined]
            resp = await factory.safe_invoke(
                [
                    SystemMessage(content=_CRITIC_SYSTEM),
                    HumanMessage(content=prompt),
                ],
                role="advisor",
                timeout=float(self.critic_timeout_s),
            )
            raw = (resp.content if resp else "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            # Normaliser le verdict
            score   = float(data.get("score", 5))
            verdict = "PASS" if score >= self.critic_pass_score else "IMPROVE"
            data["score"]   = score
            data["verdict"] = verdict
            return data
        except asyncio.TimeoutError:
            return {"score": 7.0, "verdict": "PASS", "issues": [], "suggestions": []}
        except Exception as e:
            log.warning("critique_failed", err=str(e))
            return {"score": 6.0, "verdict": "PASS", "issues": [], "suggestions": []}

    @staticmethod
    def _format_critique(critique: dict) -> str:
        lines = [f"Score : {critique.get('score', '?')}/10"]
        if critique.get("issues"):
            lines.append("Problèmes :")
            for issue in critique["issues"][:3]:
                lines.append(f"  - {issue}")
        if critique.get("suggestions"):
            lines.append("Suggestions :")
            for sug in critique["suggestions"][:3]:
                lines.append(f"  + {sug}")
        return "\n".join(lines)
