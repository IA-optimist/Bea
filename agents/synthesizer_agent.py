"""
BEA MAX — SynthesizerAgent
Fusionne les résultats de plusieurs agents en une réponse unique cohérente.

Rôle :
    - Merge des outputs agents (textes potentiellement redondants ou contradictoires)
    - Détection et résolution des conflits
    - Génération d'un plan final exploitable

Deux modes :
    1. LLM (Ollama llama3.1:8b) : synthèse intelligente si disponible
    2. Heuristique locale : concaténation structurée si LLM timeout/absent

Interface :
    synth   = SynthesizerAgent(settings)
    result  = await synth.merge_results(outputs, mission)
    plan    = await synth.generate_final_plan(merged, mission)
    merged  = synth.resolve_conflicts(outputs)    # sync, heuristique
"""
from __future__ import annotations

import asyncio
import inspect
import structlog
from typing import Callable, Awaitable

log = structlog.get_logger()

CB = Callable[[str], Awaitable[None]]

_SYNTH_TIMEOUT = 45    # secondes pour la synthèse LLM
_MAX_OUTPUT    = 600   # chars par agent dans le prompt


class SynthesizerAgent:
    """
    Synthétise les sorties de plusieurs agents en une réponse unique.

    Flux :
        1. resolve_conflicts() — supprime les doublons, trie par pertinence
        2. merge_results() — appelle le LLM ou fallback heuristique
        3. generate_final_plan() — extrait un plan actionnable
    """

    def __init__(self, settings):
        self.s = settings

    # ── API publique ──────────────────────────────────────────

    async def merge_results(
        self,
        agent_outputs: dict[str, str],
        mission: str = "",
        emit: CB | None = None,
    ) -> str:
        """
        Fusionne les outputs agents en un texte synthétique.
        Essaie d'abord le LLM local ; fallback heuristique si timeout.
        """
        if not agent_outputs:
            return "(aucun résultat agent)"

        _emit = emit or (lambda m: asyncio.sleep(0))
        if not inspect.iscoroutinefunction(_emit):
            _s = _emit
            async def _emit(msg: str):  # type: ignore[misc]
                _s(msg)

        # 1. Résoudre conflits et préparer le contexte
        deduped = self.resolve_conflicts(agent_outputs)

        # 2. Essayer la synthèse LLM
        try:
            merged = await asyncio.wait_for(
                self._llm_merge(deduped, mission),
                timeout=_SYNTH_TIMEOUT,
            )
            await _emit("[Synthesizer] Fusion LLM terminée")
            return merged
        except asyncio.TimeoutError:
            log.warning("synthesizer_llm_timeout")
            await _emit("[Synthesizer] Timeout LLM — synthèse heuristique")
        except Exception as e:
            log.warning("synthesizer_llm_error", err=str(e)[:80])

        # 3. Fallback heuristique
        return self._heuristic_merge(deduped, mission)

    def resolve_conflicts(self, agent_outputs: dict[str, str]) -> dict[str, str]:
        """
        Détection et résolution heuristique des conflits :
        - Supprime les outputs vides
        - Tronque les outputs trop longs
        - Dédoublonne les contenus quasi-identiques (similarité de début)
        - Retourne un dict nettoyé {agent: output}
        """
        cleaned: dict[str, str] = {}
        seen_prefixes: set[str] = set()

        for agent, output in agent_outputs.items():
            if not output or not output.strip():
                continue

            text = output.strip()

            # Clé de déduplication : 200 premiers chars normalisés
            prefix = " ".join(text[:200].lower().split())
            if prefix in seen_prefixes:
                log.debug("synthesizer_duplicate_skipped", agent=agent)
                continue

            seen_prefixes.add(prefix)
            cleaned[agent] = text

        return cleaned

    async def generate_final_plan(
        self,
        merged: str,
        mission: str = "",
    ) -> str:
        """
        Extrait un plan d'action final à partir de la synthèse.
        Format attendu : liste d'étapes numérotées.
        """
        if not merged:
            return "(plan non générable — synthèse vide)"

        prompt = (
            f"Mission : {mission[:200]}\n\n"
            f"Synthèse :\n{merged[:1200]}\n\n"
            "Extrais un plan d'action concis en 3-7 étapes numérotées. "
            "Chaque étape doit être concrète et actionnable. "
            "Pas d'introduction, pas de conclusion — uniquement les étapes."
        )

        try:
            llm  = self.s.get_llm("fast")
            from langchain_core.messages import HumanMessage
            resp = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=_SYNTH_TIMEOUT,
            )
            return resp.content.strip()
        except (asyncio.TimeoutError, Exception) as e:
            log.warning("synthesizer_plan_llm_failed", err=str(e)[:60])

        # Fallback : extraire les premières lignes de la synthèse
        lines = [l for l in merged.splitlines() if l.strip()][:7]
        return "\n".join(
            f"{i+1}. {l.strip().lstrip('-*•').strip()}"
            for i, l in enumerate(lines)
        )

    # ── LLM merge ────────────────────────────────────────────

    async def _llm_merge(self, outputs: dict[str, str], mission: str) -> str:
        """Synthèse LLM : fusionne les outputs agents en une réponse cohérente."""
        if not outputs:
            return "(synthèse vide)"

        # Construire le contexte agents pour le prompt
        context_parts = []
        for agent, text in outputs.items():
            snippet = text[:_MAX_OUTPUT]
            context_parts.append(f"[{agent}]\n{snippet}")
        context = "\n\n".join(context_parts)

        prompt = (
            f"Mission : {mission[:300] if mission else 'Analyse générale'}\n\n"
            f"Résultats des agents :\n{context}\n\n"
            "Synthétise ces résultats en une réponse structurée et cohérente :\n"
            "1) Synthèse globale (3-5 phrases)\n"
            "2) Points clés identifiés\n"
            "3) Contradictions ou incertitudes détectées\n"
            "Sois factuel, concis, en français."
        )

        llm  = self.s.get_llm("fast")
        from langchain_core.messages import SystemMessage, HumanMessage
        resp = await llm.ainvoke([
            SystemMessage(content=(
                f"Tu es {getattr(self.s, 'bea_name', 'Bea')}, "
                "agent de synthèse. Tu fusionnes les résultats de plusieurs agents "
                "spécialisés en une réponse unique, claire et exploitable."
            )),
            HumanMessage(content=prompt),
        ])
        return resp.content.strip()

    # ── Fallback heuristique ──────────────────────────────────

    def _heuristic_merge(self, outputs: dict[str, str], mission: str) -> str:
        """
        Fusion heuristique sans LLM.
        Structure : en-tête + section par agent + résumé des longueurs.
        """
        if not outputs:
            return "(aucun résultat à fusionner)"

        parts = []
        if mission:
            parts.append(f"Mission : {mission[:200]}\n")

        parts.append(f"Résultats de {len(outputs)} agent(s) :\n")

        for agent, text in outputs.items():
            # Prendre les 3 premières lignes non vides comme résumé
            lines = [l.strip() for l in text.splitlines() if l.strip()][:3]
            preview = " • ".join(lines)
            parts.append(f"[{agent}] {preview[:300]}")

        return "\n".join(parts)

    # ── Méthode d'intégration complète ───────────────────────

    async def synthesize(
        self,
        agent_outputs: dict[str, str],
        mission: str = "",
        emit: CB | None = None,
        include_plan: bool = False,
    ) -> dict:
        """
        Point d'entrée unique : merge + optionnellement génère un plan.

        Retourne :
            {
                "merged":   "<texte fusionné>",
                "plan":     "<plan optionnel>",
                "agents_ok": 3,
                "agents_total": 4,
            }
        """
        merged = await self.merge_results(agent_outputs, mission, emit)

        result = {
            "merged":       merged,
            "plan":         "",
            "agents_ok":    len(agent_outputs),
            "agents_total": len(agent_outputs),
        }

        if include_plan:
            result["plan"] = await self.generate_final_plan(merged, mission)

        log.info("synthesizer_done",
                 agents=len(agent_outputs), plan=bool(result["plan"]))
        return result
