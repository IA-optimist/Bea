"""
BEA MAX — Agent Crew
BaseAgent + 9 agents spécialisés + registre AgentCrew.
"""
from __future__ import annotations
import asyncio
import json
import time
from typing import TYPE_CHECKING
import structlog
from abc import ABC, abstractmethod
from langchain_core.messages import SystemMessage, HumanMessage
from core.state import BeaSession

if TYPE_CHECKING:
    from agents.contracts import AgentContract
from agents.self_critic import SelfCriticMixin
from core.reasoning_framework import INJECT_SCOUT, INJECT_PLANNER, INJECT_BUILDER, INJECT_REVIEWER, INJECT_ADVISOR

log = structlog.get_logger()


# ══════════════════════════════════════════════════════════════
# BASE AGENT
# ══════════════════════════════════════════════════════════════

class BaseAgent(ABC):
    name:       str = "base"
    role:       str = "default"
    timeout_s:  int = 120

    def __init__(self, settings):
        self.s = settings

    @property
    def llm(self):
        return self.s.get_llm(self.role)

    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def user_message(self, session: BeaSession) -> str: ...

    async def run(self, session: BeaSession) -> str:
        t0 = time.monotonic()
        log.info(f"{self.name}_start", mission_id=session.session_id)
        # Emit agent_start to EventStream (fail-open)
        try:
            from core.event_stream import get_mission_stream
            from core.events import Action
            _es = get_mission_stream(session.session_id)
            if _es:
                asyncio.get_event_loop().create_task(_es.append(Action(
                    source="agent",
                    action_type="agent_start",
                    reasoning=f"Starting {self.name}",
                )))
        except Exception as _exc:
            # Hardening M3: was DEBUG `suppressed_exception` (invisible in prod).
            # Now WARNING with exception class + action so silently-broken event
            # emission is observable in logs.
            log.warning("swallowed_exception", action="agent_start_event_stream",
                        agent=self.name, exc_type=type(_exc).__name__,
                        exc_msg=str(_exc)[:200])
        try:
            from core.llm_factory import LLMFactory
            factory = LLMFactory(self.s)
            _sys = self.system_prompt()
            try:
                from core.learning_loop import get_learning_loop
                _addon = await get_learning_loop().get_agent_system_prompt_addon(self.name)
                if _addon: _sys += "\n\n" + _addon
            except Exception as e:
                log.debug("learning_loop_prompt_addon_skipped", agent=self.name, err=str(e)[:60])
            # Build user message with real repo context injection
            _user_msg = self.user_message(session)
            try:
                from core.tools.repo_inspector import build_agent_context
                _goal = session.mission_summary or session.user_input or ""
                _repo_ctx = build_agent_context(_goal, max_chars=4000)
                if _repo_ctx:
                    _user_msg += f"\n\n## Real Codebase Context\n{_repo_ctx}"
                    log.debug("repo_context_injected", agent=self.name,
                              chars=len(_repo_ctx))
            except Exception as _rc_err:
                log.debug("repo_context_skipped", agent=self.name,
                          err=str(_rc_err)[:60])
            messages = [
                SystemMessage(content=_sys),
                HumanMessage(content=_user_msg),
            ]
            # safe_invoke : circuit breaker Ollama + fallback cloud automatique
            resp = await factory.safe_invoke(
                messages, role=self.role, timeout=float(self.timeout_s)
            )
            out = resp.content if resp else ""
            ms  = int((time.monotonic() - t0) * 1000)
            session.set_output(self.name, out, success=bool(out), ms=ms)
            try:
                from api.event_emitter import emit_agent_result
                emit_agent_result(session.session_id, self.name, out)
            except Exception as _exc:
                # Hardening M3.
                log.warning("swallowed_exception", action="emit_agent_result",
                            agent=self.name, exc_type=type(_exc).__name__,
                            exc_msg=str(_exc)[:200])
            # Emit agent_output to EventStream (fail-open)
            try:
                from core.event_stream import get_mission_stream
                from core.events import Observation
                _es = get_mission_stream(session.session_id)
                if _es:
                    await _es.append(Observation(
                        source="agent",
                        observation_type="agent_output",
                        content=out[:500],
                        metadata={"agent": self.name, "ms": ms, "chars": len(out)},
                    ))
            except Exception as _exc:
                # Hardening M3.
                log.warning("swallowed_exception", action="emit_agent_output_observation",
                            agent=self.name, exc_type=type(_exc).__name__,
                            exc_msg=str(_exc)[:200])
            log.info(f"{self.name}_done", ms=ms, chars=len(out))
            return out
        except asyncio.TimeoutError:
            session.set_output(self.name, "", success=False, error="Timeout")
            log.warning(f"{self.name}_timeout")
            return ""
        except Exception as e:
            session.set_output(self.name, "", success=False, error=str(e))
            log.error(f"{self.name}_error", err=str(e))
            return ""

    def _task(self, session: BeaSession) -> str:
        for t in session.agents_plan:
            if t.get("agent") == self.name:
                return t.get("task", session.mission_summary)
        return session.mission_summary

    # =========================================================================
    # PHASE 3 — Structured contract + memory injection
    # run() is unchanged. run_structured() is the new canonical method.
    # =========================================================================

    def _get_memory_context(
        self,
        session: "BeaSession",
        max_chars: int = 2000,
    ) -> str:
        """
        Builds injectable memory context for this agent's prompt.

        Priority (Kernel Rule K2 — all memory access through MemoryFacade):
          1. MemoryFacade.search_relevant() — canonical unified memory layer
          2. MemoryBus.build_agent_context() — legacy fallback (direct layer)

        Returns "" on failure. Caps output to max_chars to avoid prompt explosion.
        """
        mission_id = getattr(session, "session_id", "")

        # 1 — MemoryFacade (canonical — Kernel Rule K2)
        try:
            from core.memory_facade import MemoryFacade
            facade = MemoryFacade(self.s)
            query = f"agent:{self.name} mission:{mission_id}"
            results = facade.search_relevant(query=query, top_k=5)
            if results:
                ctx = "\n".join(
                    r.get("content", r.get("text", ""))[:400] for r in results if r
                )
                if ctx:
                    if len(ctx) > max_chars:
                        ctx = ctx[:max_chars] + "\n[contexte tronqué]"
                    return ctx
        except Exception as e:
            log.debug("agent_memory_facade_failed", agent=self.name, err=str(e)[:60])

        # 2 — MemoryBus fallback (legacy direct layer)
        try:
            from memory.memory_bus import MemoryBus
            bus = MemoryBus(self.s)
            ctx = bus.build_agent_context(
                agent_id   = self.name,
                mission_id = mission_id,
                max_items  = 5,
            )
            if ctx and len(ctx) > max_chars:
                ctx = ctx[:max_chars] + "\n[contexte tronqué]"
            return ctx or ""
        except Exception as e:
            log.debug("agent_memory_context_failed", agent=self.name, err=str(e)[:60])
            return ""

    async def run_structured(
        self,
        session: "BeaSession",
        inject_memory: bool = True,
        store_output:  bool = True,
    ) -> "AgentContract":
        """
        Canonical run method — returns AgentContract instead of raw str.

        Steps:
            1. Optionally inject memory context into system prompt
            2. Call run() (existing logic, unchanged)
            3. Wrap output in AgentContract with confidence + delegation
            4. Optionally store output in memory (episodic layer)

        Does NOT block or replace run() — fully additive.
        """
        import time
        from agents.contracts import AgentContract

        t0         = time.monotonic()
        mission_id = getattr(session, "session_id", "")

        # 1. Inject memory context (additive to system prompt if supported)
        mem_ctx = ""
        if inject_memory:
            mem_ctx = self._get_memory_context(session)
            if mem_ctx:
                # Store mem context on session for prompt builders that check it
                if not hasattr(session, "_agent_memory_ctx"):
                    session._agent_memory_ctx = {}
                session._agent_memory_ctx[self.name] = mem_ctx

        # 2. Execute via existing run()
        try:
            raw_output = await self.run(session)
        except Exception as e:
            return AgentContract.error_contract(self.name, mission_id, str(e)[:200])

        duration_ms = int((time.monotonic() - t0) * 1000)
        out_obj     = session.outputs.get(self.name)
        success     = out_obj.success if out_obj else bool(raw_output)
        error       = (out_obj.error or "") if out_obj else ""

        # 3. Build AgentContract
        contract = AgentContract.from_raw(
            agent_id    = self.name,
            mission_id  = mission_id,
            output      = raw_output or "",
            success     = success,
            error       = error,
            duration_ms = duration_ms,
        )
        contract.used_memory = [mem_ctx[:80]] if mem_ctx else []

        # 4. Store output in episodic memory via MemoryFacade (Kernel Rule K2)
        if store_output and success and raw_output:
            try:
                from core.memory_facade import MemoryFacade
                facade = MemoryFacade(self.s)
                result = facade.store(
                    content      = raw_output[:500],
                    content_type = "agent_output",
                    tags         = ["agent_output", self.name],
                    metadata     = {
                        "mission_id": mission_id,
                        "agent_id":   self.name,
                        "confidence": contract.confidence,
                        "source":     self.name,
                    },
                )
                mem_id = result.get("id") or result.get("memory_id") or ""
                contract.generated_memory = [mem_id] if mem_id else []
            except Exception as e:
                log.debug("run_structured_store_failed", agent=self.name, err=str(e)[:60])

        log.info(
            "agent.run_structured",
            agent      = self.name,
            mission_id = mission_id,
            status     = contract.status.value,
            confidence = contract.confidence,
            duration_ms = duration_ms,
            next_agent = contract.next_recommended_agent,
        )
        return contract


    def _ctx(self, session: BeaSession, skip: set | None = None, limit: int = 600) -> str:
        sk = (skip or set()) | {self.name}
        parts = [
            f"### {k}\n{v[:limit]}"
            for k, v in session.context_snapshot(limit).items()
            if k not in sk
        ]
        return "\n\n".join(parts)

    def _mem_ctx(self, n: int = 2) -> str:
        """
        Contexte mémoire per-agent : patterns réussis passés.
        Retourne un bloc injectable dans le prompt utilisateur.
        Silencieux si AgentMemory indisponible.
        """
        try:
            from memory.agent_memory import AgentMemory
            am = AgentMemory(self.s)
            return am.get_context(self.name, max_items=n)
        except Exception:
            return ""

    def _knowledge_ctx(self, query: str, n: int = 3) -> str:
        """
        Connaissances validées depuis KnowledgeMemory — injectable dans les prompts.
        Silencieux si KnowledgeMemory indisponible.
        """
        try:
            from memory.legacy_knowledge_memory import get_knowledge_memory
            km = get_knowledge_memory()
            return km.get_context_for_prompt(self.name, query=query, max_items=n)
        except Exception:
            return ""

    def _vec_ctx(self, query: str, n: int = 2, min_score: float = 0.5) -> str:
        """
        Lookup sémantique — MemoryFacade (canonical unified store) en priorité.
        Fallback silencieux si façade indisponible.

        BLOC B (Memory unification): MemoryFacade.search() remplace l'accès direct
        à memory.vector_memory.VectorMemory pour converger vers le store unifié.

        Paramètres :
            query     : requête sémantique (ex: titre de tâche ou mission)
            n         : nombre maximum de résultats
            min_score : score cosine minimum pour inclure un résultat
        """
        try:
            from core.memory_facade import MemoryFacade
            _facade = MemoryFacade(self.s)
            _entries = _facade.search(query, top_k=n)
            if not _entries:
                return ""
            lines = ["## Contexte sémantique (mémoire unifiée)"]
            for e in _entries:
                if isinstance(e, dict):
                    score = float(e.get("score", 0.0))
                    text = e.get("content", e.get("text", ""))[:300]
                else:
                    score = float(getattr(e, "score", 0.0) or 0.0)
                    text = (getattr(e, "content", "") or "")[:300]
                if score >= min_score:
                    lines.append(f"[score={score:.2f}] {text}")
            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception:
            return ""


# ══════════════════════════════════════════════════════════════
# 1. ATLAS DIRECTOR
# ══════════════════════════════════════════════════════════════

class AtlasDirector(BaseAgent):
    name, role, timeout_s = "atlas-director", "director", 60

    def system_prompt(self) -> str:
        return """Tu es AtlasDirector, chef d'orchestre de BeaMax.

Décompose chaque mission en tâches précises pour les agents.

Agents disponibles :
- openhands       (P1) : SUPER-AGENT dev autonome (Docker/Headless) pour TOUT développement complexe (À PRIVILÉGIER POUR LE CODE !).
- scout-research  (P1) : recherche, synthèse d'informations (LLM interne)
- web-scout       (P1) : recherche web RÉELLE via Playwright (données fraîches)
- vault-memory    (P1) : rappel contexte mémorisé (TOUJOURS inclure)
- shadow-advisor  (P1) : angles alternatifs et contre-arguments
- map-planner     (P2) : plan exécutable avec jalons
- forge-builder   (P2) : modifications de code textuelles MINEURES uniquement.
- lens-reviewer   (P3) : contrôle qualité des résultats (TOUJOURS en dernier)
- pulse-ops       (P3) : prépare actions concrètes (si needs_actions=true)

Règle 1 : utilise web-scout quand la mission nécessite des données actuelles.
Règle 2 : Délègue SYSTÉMATIQUEMENT les tâches de programmation complexes, de création de projet, d'architecture ou d'exécution long-terme à `openhands`.

Réponds UNIQUEMENT en JSON :
{
  "mission_summary": "Résumé en 1 phrase",
  "needs_actions": false,
  "tasks": [
    {"agent": "scout-research", "task": "Tâche précise", "priority": 1}
  ],
  "reasoning": "Justification du plan"
}"""

    def user_message(self, session: BeaSession) -> str:
        mem = session.get_output("vault-memory")
        ctx = f"\nContexte mémorisé :\n{mem}" if mem else ""
        return f"Mission : {session.user_input}{ctx}"

    async def run(self, session: BeaSession) -> str:
        out = await super().run(session)
        try:
            raw = out.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            session.mission_summary = data.get("mission_summary", session.user_input)
            session.agents_plan     = data.get("tasks", [])
            session.needs_actions   = data.get("needs_actions", False)
        except Exception as e:
            log.error("director_parse_failed", err=str(e))
            session.mission_summary = session.user_input
            session.agents_plan = [
                {"agent": "scout-research", "task": session.user_input, "priority": 1},
                {"agent": "lens-reviewer",  "task": "Vérifier résultats",  "priority": 3},
            ]
        return out


# ══════════════════════════════════════════════════════════════
# 2. SCOUT RESEARCH
# ══════════════════════════════════════════════════════════════

class ScoutResearch(BaseAgent):
    name, role = "scout-research", "research"

    def system_prompt(self) -> str:
        return (
            "Tu es ScoutResearch, agent de recherche expert de BeaMax.\n\n"
            "MISSION : Analyser, comparer et synthétiser des informations avec rigueur.\n\n"
            "EXPERTISE :\n"
            "- Identification des tendances de fond vs tendances superficielles\n"
            "- Cartographie des acteurs clés et leurs relations\n"
            "- Détection des opportunités cachées et risques sous-estimés\n"
            "- Vérification croisée des informations\n\n"
            "FORMAT DE RÉPONSE OBLIGATOIRE :\n"
            "## Synthèse (2-3 phrases)\n"
            "## Faits clés\n"
            "- Point 1 [source si disponible]\n"
            "- Point 2 [source si disponible]\n"
            "## Tendances identifiées\n"
            "## Acteurs principaux\n"
            "## Risques / Opportunités\n"
            "## Limites de cette analyse\n\n"
            "RÈGLES QUALITÉ :\n"
            "- Distingue faits vérifiables et hypothèses (marque [HYPOTHÈSE])\n"
            "- Signale les lacunes d'information plutôt que d'inventer\n"
            "- Longueur cible : 400-800 mots\n"
            "- Lecture seule — aucune action réelle.\n\n"
            "RÈGLE IMPÉRATIVE : Chaque réponse doit contenir au moins 1 élément concret.\n"
            "- Jamais de réponse abstraite sans exemple ou action concrète.\n"
            "- Format préféré : [Ce que je fais] + [Comment] + [Exemple concret ou output]\n"
            "- Si complexité LOW (question simple) : max 8 lignes, réponse directe."
            + INJECT_SCOUT
        )

    def user_message(self, session: BeaSession) -> str:
        task    = self._task(session)
        ctx     = self._ctx(session)
        mem     = self._mem_ctx(2)
        vec_ctx = self._vec_ctx(task or session.mission_summary, n=2, min_score=0.5)
        know    = self._knowledge_ctx(task or session.mission_summary)
        return (
            f"Mission : {session.mission_summary}\nTâche : {task}"
            + (f"\n\nContexte agents :\n{ctx}" if ctx else "")
            + (f"\n\n{vec_ctx}" if vec_ctx else "")
            + (f"\n\n{mem}" if mem else "")
            + (f"\n\n{know}" if know else "")
        )


# ══════════════════════════════════════════════════════════════
# 3. MAP PLANNER
# ══════════════════════════════════════════════════════════════

class MapPlanner(BaseAgent):
    name, role = "map-planner", "planner"

    def system_prompt(self) -> str:
        return (
            "Tu es MapPlanner, agent de planification stratégique de BeaMax.\n\n"
            "MISSION : Transformer des objectifs en plans exécutables, réalistes et hiérarchisés.\n\n"
            "FORMAT DE RÉPONSE OBLIGATOIRE :\n"
            "## Objectif\n"
            "(1 phrase claire et mesurable)\n\n"
            "## MVP (Minimum Viable Product)\n"
            "(ce qu'il faut faire en premier pour avoir un résultat utile)\n\n"
            "## Jalons\n"
            "**Jalon 1** (J+X) : Description\n"
            "  - Tâche A\n"
            "  - Tâche B\n"
            "  Prérequis : ...\n\n"
            "**Jalon 2** (J+X) : ...\n\n"
            "## Dépendances critiques\n"
            "(qu'est-ce qui peut bloquer le plan ?)\n\n"
            "## Risques\n"
            "| Risque | Probabilité | Impact | Mitigation |\n"
            "|--------|-------------|--------|------------|\n\n"
            "## Estimation effort total\n"
            "(heures/jours, par phase)\n\n"
            "RÈGLES QUALITÉ :\n"
            "- Jalons SMART : Spécifique, Mesurable, Atteignable, Réaliste, Temporel\n"
            "- MVP en priorité absolue — ne pas sur-spécifier l'avenir\n"
            "- Favoriser la délégation de la globalité du code à l'Expert 'OpenHands'.\n"
            "- Signaler explicitement les hypothèses du plan\n"
            "- Aucune exécution — planification uniquement."
            + INJECT_PLANNER
        )

    def user_message(self, session: BeaSession) -> str:
        task    = self._task(session)
        ctx     = self._ctx(session)
        mem     = self._mem_ctx(2)
        vec_ctx = self._vec_ctx(task or session.mission_summary, n=2, min_score=0.5)
        know    = self._knowledge_ctx(task or session.mission_summary)
        return (
            f"Mission : {session.mission_summary}\nTâche : {task}"
            + (f"\n\nInformations disponibles :\n{ctx}" if ctx else "")
            + (f"\n\n{vec_ctx}" if vec_ctx else "")
            + (f"\n\n{mem}" if mem else "")
            + (f"\n\n{know}" if know else "")
        )


# ══════════════════════════════════════════════════════════════
# 4. FORGE BUILDER
# ══════════════════════════════════════════════════════════════

class ForgeBuilder(BaseAgent):
    name, role, timeout_s = "forge-builder", "builder", 180

    def system_prompt(self) -> str:
        return (
            "Tu es ForgeBuilder, agent de génération de code production-ready de BeaMax.\n\n"
            "MISSION : Générer du code Python, Shell, YAML, JSON de qualité professionnelle.\n\n"
            "STANDARDS OBLIGATOIRES :\n"
            "- Type hints Python partout (PEP 484)\n"
            "- Gestion d'erreurs explicite (try/except avec logs, pas bare except)\n"
            "- Commentaires pour la logique non triviale\n"
            "- Pas de hardcoding de credentials / chemins absolus / secrets\n"
            "- Variables nommées de façon descriptive (pas x, i, tmp sauf boucles courtes)\n"
            "- Imports en haut du fichier, regroupés (stdlib / third-party / local)\n\n"
            "FORMAT DE RÉPONSE OBLIGATOIRE :\n"
            "## Description\n"
            "(ce que le code fait, pourquoi ces choix)\n\n"
            "## Code\n"
            "```python\n"
            "# code ici\n"
            "```\n\n"
            "## Utilisation\n"
            "(comment appeler / intégrer ce code)\n\n"
            "## Tests recommandés\n"
            "(cas nominaux et cas d'erreur à vérifier)\n\n"
            "RÈGLES QUALITÉ :\n"
            "- Vérifier mentalement la logique avant de soumettre\n"
            "- Signaler les edge cases non gérés\n"
            "- Signaler les dépendances requises (pip install...)\n"
            "- PulseOps exécute le code — il doit être sûr et testé mentalement.\n\n"
            "RÈGLE IMPÉRATIVE : Chaque réponse doit contenir au moins 1 élément concret.\n"
            "- Jamais de réponse abstraite sans exemple ou action concrète.\n"
            "- Format préféré : [Ce que je fais] + [Comment] + [Exemple concret ou output]\n"
            "- Si complexité LOW (question simple) : max 8 lignes, réponse directe."
            + INJECT_BUILDER
        )

    def user_message(self, session: BeaSession) -> str:
        task    = self._task(session)
        ctx     = self._ctx(session)
        mem     = self._mem_ctx(2)
        vec_ctx = self._vec_ctx(task or session.mission_summary, n=2, min_score=0.5)
        know    = self._knowledge_ctx(task or session.mission_summary)
        return (
            f"Mission : {session.mission_summary}\nTâche : {task}"
            + (f"\n\nContexte :\n{ctx}" if ctx else "")
            + (f"\n\n{vec_ctx}" if vec_ctx else "")
            + (f"\n\n{mem}" if mem else "")
            + (f"\n\n{know}" if know else "")
        )


# ══════════════════════════════════════════════════════════════
# 5. LENS REVIEWER
# ══════════════════════════════════════════════════════════════

class LensReviewer(BaseAgent):
    name, role = "lens-reviewer", "reviewer"

    def system_prompt(self) -> str:
        return (
            "Tu es LensReviewer, agent de contrôle qualité senior de BeaMax.\n\n"
            "MISSION : Évaluer les travaux des autres agents avec rigueur et honnêteté.\n\n"
            "FORMAT DE RÉPONSE OBLIGATOIRE :\n"
            "## Score global : X/10\n\n"
            "## ✅ Points forts\n"
            "- (ce qui est bien fait, précis, utile)\n\n"
            "## ⚠️ Problèmes et incohérences\n"
            "- (erreurs factuelles, logique défaillante, lacunes)\n\n"
            "## 🔒 Risques de sécurité\n"
            "- (si code : injection, secrets en dur, permissions excessives)\n"
            "- (si plan : dépendances cachées, single point of failure)\n\n"
            "## 💡 Améliorations concrètes\n"
            "1. Amélioration prioritaire\n"
            "2. Amélioration secondaire\n\n"
            "## Verdict\n"
            "APPROUVÉ / APPROUVÉ_AVEC_RÉSERVES / REFUSÉ\n"
            "(justification en 1-2 phrases)\n\n"
            "RÈGLES QUALITÉ :\n"
            "- Note < 6/10 = REFUSÉ obligatoirement\n"
            "- Ne valide JAMAIS un travail insuffisant par politesse\n"
            "- Les problèmes de sécurité entraînent automatiquement REFUSÉ\n"
            "- Sois précis sur 'pourquoi' c'est un problème, pas juste 'ce n'est pas bien'"
            + INJECT_REVIEWER
        )

    def user_message(self, session: BeaSession) -> str:
        ctx  = self._ctx(session)
        know = self._knowledge_ctx(session.mission_summary)
        return (f"Mission : {session.mission_summary}\n\n"
                f"Travaux à réviser :\n{ctx or '(aucun résultat disponible)'}"
                + (f"\n\n{know}" if know else ""))


# ══════════════════════════════════════════════════════════════
# 6. VAULT MEMORY
# ══════════════════════════════════════════════════════════════

class VaultMemory(BaseAgent):
    name, role = "vault-memory", "memory"

    def __init__(self, settings):
        super().__init__(settings)
        self._recalled: str = "(non initialise)"  # instance, pas classe

    def system_prompt(self) -> str:
        return (
            "Tu es VaultMemory, agent de mémoire de BeaMax.\n"
            "À partir des souvenirs récupérés, formule un résumé du contexte utile.\n"
            "Indique aussi ce qui devrait être mémorisé après cette session."
        )

    def user_message(self, session: BeaSession) -> str:
        return f"Mission : {session.user_input}\n\nSouvenirs :\n{self._recalled}"



    async def run(self, session: BeaSession) -> str:
        try:
            from memory.store import MemoryStore
            store  = MemoryStore(self.s)
            items  = await store.search(session.user_input, k=5)
            self._recalled = (
                "\n".join(f"- {i}" for i in items) if items else "Aucun souvenir pertinent."
            )
        except Exception as e:
            log.warning("vault_recall_failed", err=str(e))
            self._recalled = "Mémoire temporairement indisponible."
        return await super().run(session)


# ══════════════════════════════════════════════════════════════
# 7. SHADOW ADVISOR V2 — validateur critique structuré
# ══════════════════════════════════════════════════════════════

class ShadowAdvisor(BaseAgent):
    name, role = "shadow-advisor", "advisor"
    # timeout_s 30s : Ollama a 30s, puis OpenAI-fast fallback (~2s).
    # advisor n'est plus LOCAL_ONLY → fallback cloud activé (R-06 SRE).
    timeout_s = 30

    _JSON_SCHEMA = """\
{
  "decision": "GO | IMPROVE | NO-GO",
  "confidence": 0.0,
  "blocking_issues": [
    {"type": "technique|logique|memoire|securite|business|test",
     "description": "...", "severity": "low|medium|high", "evidence": "..."}
  ],
  "risks": [
    {"type": "...", "description": "...", "severity": "low|medium|high",
     "probability": "low|medium|high", "impact": "low|medium|high"}
  ],
  "weak_points": ["..."],
  "inconsistencies": ["..."],
  "missing_proofs": ["..."],
  "improvements": ["..."],
  "tests_required": ["..."],
  "final_score": 0.0,
  "justification": "..."
}"""

    def system_prompt(self) -> str:
        return (
            "Tu es ShadowAdvisor V2, validateur critique structuré de BeaMax.\n\n"
            "MISSION : Analyser toute décision, plan, code ou idée soumis.\n"
            "Détecter ce qui peut échouer, ce qui manque, ce qui est incohérent.\n"
            "Tu n'approuves JAMAIS sans preuve. Tu ne valides JAMAIS par politesse.\n\n"
            "PROCESSUS OBLIGATOIRE (dans cet ordre) :\n"
            "  1. Qu'est-ce qui peut casser ?\n"
            "  2. Qu'est-ce qui est supposé sans preuve ?\n"
            "  3. Qu'est-ce qui manque pour valider ?\n"
            "  4. Quelle est la contradiction principale ?\n"
            "  5. Quelle est la pire conséquence si on se trompe ?\n"
            "  6. Quelle amélioration réduit le plus le risque ?\n\n"
            "DISTINCTIONS OBLIGATOIRES :\n"
            "  ✅ FAIT      : vérifiable, sourcé, observable\n"
            "  ⚠️ HYPOTHÈSE : raisonnable mais non prouvée\n"
            "  ❓ INCONNU   : information absente — le dire explicitement\n"
            "  ❌ HALLUC    : affirmation inventée — INTERDITE\n\n"
            "DÉCISION FINALE :\n"
            "  GO      → risques acceptables, preuves présentes, cohérent\n"
            "  IMPROVE → potentiel réel mais corrections nécessaires\n"
            "  NO-GO   → risques critiques ou incohérences majeures\n\n"
            "INTERDICTIONS ABSOLUES :\n"
            "  - réponse en texte libre\n"
            "  - 'ça semble correct' sans preuve\n"
            "  - conclusion sans raisonnement\n"
            "  - score sans justification\n\n"
            f"FORMAT DE RÉPONSE OBLIGATOIRE (JSON strict uniquement) :\n{self._JSON_SCHEMA}"
            + INJECT_ADVISOR
        )

    def user_message(self, session: BeaSession) -> str:
        # shadow-advisor reçoit la mission + contexte agents + connaissances validées
        ctx  = self._ctx(session, limit=800)
        know = self._knowledge_ctx(session.mission_summary or session.user_input)
        subject = session.mission_summary or session.user_input
        lines = [f"SUJET À ANALYSER : {subject}"]
        if ctx:
            lines.append(f"\nCONTEXTE ET SORTIES DES AGENTS :\n{ctx}")
        if know:
            lines.append(f"\n{know}")
        lines.append(
            "\nAPPLIQUE les 6 questions critiques. "
            "Réponds UNIQUEMENT en JSON strict. Aucun texte hors du JSON."
        )
        return "\n".join(lines)

    async def run(self, session: BeaSession) -> str:
        """
        Run V2 : exécute l'agent, parse la sortie JSON, score le rapport,
        stocke l'AdvisoryReport dans session.metadata, et retourne le JSON stringifié.
        """
        from agents.shadow_advisor.schema import parse_advisory, validate_advisory_structure
        from agents.shadow_advisor.scorer import AdvisoryScorer

        # ── ContextProvider injection (fail-open) ─────────────────────────────
        try:
            from core.context_provider import get_context_provider
            ctx = get_context_provider().get_context_for_shadow_advisor(
                mission_id=getattr(session, "session_id", "") or ""
            )
            context_text = ctx.to_prompt_text()
            if context_text:
                original = session.mission_summary or session.user_input or ""
                session.mission_summary = context_text + "\n\n---\n\n" + original
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
        # ─────────────────────────────────────────────────────────────────────

        raw = await super().run(session)

        # Parse
        report = parse_advisory(raw)

        # Score (recalibre décision + final_score)
        scorer = AdvisoryScorer()
        report = scorer.score(report)

        # Validation structure
        violations = validate_advisory_structure(report)
        if violations:
            log.warning(
                "shadow_advisor_structure_violations",
                count=len(violations),
                violations=violations[:3],
                sid=session.session_id,
            )

        # Stockage dans session.metadata pour propagation
        session.metadata["shadow_advisory"] = report.to_dict()
        session.metadata["shadow_score"]    = report.final_score
        session.metadata["shadow_decision"] = str(report.decision)

        # Log structuré
        log.info(
            "shadow_advisor_v2_done",
            decision=str(report.decision),
            score=report.final_score,
            issues=report.blocking_count(),
            risks=len(report.risks),
            valid_parse=report.is_valid_parse(),
            sid=session.session_id,
        )

        # Met à jour le output session avec le JSON structuré
        structured_out = report.to_prompt_feedback()
        session.set_output(self.name, structured_out, success=report.is_valid_parse())

        return structured_out


# ══════════════════════════════════════════════════════════════
# 8. PULSE OPS
# ══════════════════════════════════════════════════════════════

class PulseOps(BaseAgent):
    name, role = "pulse-ops", "ops"

    def system_prompt(self) -> str:
        return (
            "Tu es PulseOps, agent de préparation d'actions de BeaMax.\n\n"
            "À partir des résultats des agents, liste les actions concrètes.\n\n"
            "PRIORITÉ : Si forge-builder a produit des sections '### Fichier: chemin' dans sa sortie, "
            "extrait CHAQUE bloc et crée une action create_file pour chacun. "
            "Sinon, déduis les actions appropriées depuis le contexte.\n\n"
            "Types disponibles :\n"
            "create_file | write_file | replace_in_file | run_command | backup_file\n\n"
            "Réponds UNIQUEMENT en JSON :\n"
            '{"actions":[{"action_type":"create_file","target":"workspace/reports/x.md",'
            '"content":"# Contenu...","description":"Créer rapport","command":"",'
            '"old_str":"","new_str":"","reversible":true}],"summary":"..."}'
        )

    def user_message(self, session: BeaSession) -> str:
        # forge-builder output at full length — needed to find ### Fichier: blocks
        forge_out = getattr(getattr(session, "outputs", {}).get("forge-builder"), "content", "")
        ctx = self._ctx(session, limit=400)  # other agents: short summary
        msg = f"Mission : {session.mission_summary}\n\n"
        if forge_out:
            msg += f"### forge-builder (COMPLET)\n{forge_out}\n\n"
        msg += f"Autres agents :\n{ctx or '(aucun)'}"
        return msg

    async def run(self, session: BeaSession) -> str:
        out = await super().run(session)
        # Preserve forge-builder's direct actions — extend, don't overwrite.
        forge_actions = list(getattr(session, "_raw_actions", None) or [])
        try:
            raw = out.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            pulse_actions = data.get("actions", [])
            # Deduplicate by target path: forge-builder actions take priority
            forge_targets = {a.get("target") for a in forge_actions}
            new_actions = [a for a in pulse_actions if a.get("target") not in forge_targets]
            session._raw_actions = forge_actions + new_actions
        except Exception as e:
            log.error("pulse_ops_parse_failed", err=str(e))
            session._raw_actions = forge_actions  # keep forge-builder's actions on parse failure
        return out


# ══════════════════════════════════════════════════════════════
# 9. NIGHT WORKER (agent shell — délègue au NightWorkerEngine)
# ══════════════════════════════════════════════════════════════

class NightWorker(BaseAgent):
    name, role, timeout_s = "night-worker", "builder", 300

    def system_prompt(self) -> str:
        return (
            "Tu es NightWorker, agent de travail long de BeaMax.\n"
            "Tu produis du contenu concret sur des missions longues.\n"
            "Code, analyses, rapports, structures — tout est permis."
        )

    def user_message(self, session: BeaSession) -> str:
        ctx = self._ctx(session)
        return (
            f"Mission : {session.mission_summary}\n"
            f"Cycle : {session.night_cycle}\n"
            f"Productions précédentes :\n"
            + ("\n".join(session.night_productions[-2:]) or "(premier cycle)")
            + (f"\n\nContexte :\n{ctx}" if ctx else "")
        )


# ══════════════════════════════════════════════════════════════
# 10. IMAGE AGENT (HuggingFace Stable Diffusion)
# ══════════════════════════════════════════════════════════════

_IMAGE_AGENT_TRIGGER_KEYWORDS = [
    "génère une image",
    "crée une image",
    "generate image",
    "create image",
    "dessine",
    "illustre",
]


class ImageAgent(BaseAgent):
    """
    Agent de génération d'images via HuggingFace Inference API (SDXL).
    Déclenché par des mots-clés comme "génère une image", "dessine", etc.
    """
    name, role, timeout_s = "image-agent", "builder", 120

    def system_prompt(self) -> str:
        return (
            "Tu es un agent de génération d'images. "
            "Utilise generate_image() pour créer des images à partir de descriptions."
        )

    def user_message(self, session: BeaSession) -> str:
        task = self._task(session)
        return f"Mission : {session.mission_summary}\nTâche : {task}"

    async def run(self, session: BeaSession) -> str:
        task = self._task(session)
        log.info("image_agent_start", task=task[:80], mission_id=session.session_id)
        try:
            from modules.multimodal.image import generate_image_hf
            image_path = await generate_image_hf(task or session.mission_summary)
            if image_path:
                out = f"Image générée : {image_path}"
            else:
                out = "[ImageAgent] Aucune clé HUGGINGFACE_API_KEY configurée — image non générée."
            session.set_output(self.name, out, success=bool(image_path))
            try:
                from api.event_emitter import emit_agent_result
                emit_agent_result(session.session_id, self.name, out)
            except Exception as _exc:
                # Hardening M3.
                log.warning("swallowed_exception", action="emit_image_agent_result",
                            agent=self.name, exc_type=type(_exc).__name__,
                            exc_msg=str(_exc)[:200])
            return out
        except Exception as e:
            log.error("image_agent_error", err=str(e)[:120])
            out = f"[ImageAgent] Erreur : {e}"
            session.set_output(self.name, out, success=False, error=str(e))
            try:
                from api.event_emitter import emit_agent_result
                emit_agent_result(session.session_id, self.name, out)
            except Exception as _exc:
                # Hardening M3.
                log.warning("swallowed_exception", action="emit_image_agent_error",
                            agent=self.name, exc_type=type(_exc).__name__,
                            exc_msg=str(_exc)[:200])
            return out

    @staticmethod
    def matches_task(task_text: str) -> bool:
        """Returns True if the task text contains an image-generation trigger keyword."""
        lower = task_text.lower()
        return any(kw in lower for kw in _IMAGE_AGENT_TRIGGER_KEYWORDS)


# ══════════════════════════════════════════════════════════════
# VARIANTS AVEC AUTO-CRITIQUE (SelfCriticMixin activé)
# ══════════════════════════════════════════════════════════════

class ForgeBuilderWithCritic(SelfCriticMixin, ForgeBuilder):
    """
    ForgeBuilder enrichi d'un round d'auto-critique.

    Comportement :
        1. Génère le code/script normalement (round 0 via ForgeBuilder.run)
        2. SelfCriticMixin évalue la sortie (score LLM)
        3. Si score < 6.5 → une révision avec la critique injectée
        4. critic_max_rounds=1 : latence max = 2× ForgeBuilder (acceptable)

    Utilisation dans AgentCrew :
        "forge-builder" → ForgeBuilderWithCritic(settings)
        Transparence totale — même nom, même interface.
    """
    name              = "forge-builder"
    critic_max_rounds = 0        # no revision — Codex streaming takes ~180s; 2nd call would exceed timeouts
    critic_pass_score = 6.5

    async def run(self, session: BeaSession) -> str:
        out = await self.run_with_self_critic(session)
        # Extract ### Fichier: blocks directly into session._raw_actions
        # This bypasses PulseOps context truncation (context_snapshot limits to 600 chars).
        import re as _re
        parts = _re.split(r"(?m)^### Fichier:\s*(.+)$", out)
        if len(parts) > 1:
            actions = []
            for idx in range(1, len(parts), 2):
                path = parts[idx].strip()
                content = parts[idx + 1].strip() if idx + 1 < len(parts) else ""
                if content.startswith("```"):
                    content = "\n".join(content.split("\n")[1:])
                    if content.endswith("```"):
                        content = content[:-3].strip()
                if path and content:
                    actions.append({
                        "action_type": "create_file",
                        "target": path,
                        "content": content,
                        "description": f"Créé par forge-builder: {path}",
                        "command": "",
                        "old_str": "",
                        "new_str": "",
                        "reversible": True,
                    })
            if actions:
                if not getattr(session, "_raw_actions", None):
                    session._raw_actions = []
                session._raw_actions.extend(actions)
                log.info("forge_builder_actions_extracted",
                         files=[a["target"] for a in actions], count=len(actions))
        return out


class MapPlannerWithCritic(SelfCriticMixin, MapPlanner):
    """
    MapPlanner enrichi d'un round d'auto-critique.

    Le planificateur bénéficie particulièrement de la critique car
    un mauvais plan en début de session dégrade tous les agents suivants.

    critic_pass_score=6.0 : seuil standard (plans moins formels que code)
    critic_max_rounds=1   : latence maîtrisée
    """
    name              = "map-planner"
    critic_max_rounds = 1
    critic_pass_score = 6.0

    async def run(self, session: BeaSession) -> str:
        return await self.run_with_self_critic(session)


# ══════════════════════════════════════════════════════════════
# AGENT CREW — Registre et dispatcher
# ══════════════════════════════════════════════════════════════

# AgentCrew compatibility export. New code should import from agents.crew_runtime.
from agents.crew_runtime import AgentCrew as AgentCrew
# AgentSelector compatibility exports. New code should import from agents.selector.
from agents.selector import (
    AGENT_PROFILES as AGENT_PROFILES,
    DOMAIN_AGENT_PROFILES as DOMAIN_AGENT_PROFILES,
    MAX_AGENTS_PER_MISSION as MAX_AGENTS_PER_MISSION,
    MISSION_ROUTING as MISSION_ROUTING,
    AgentSelector as AgentSelector,
    get_agent_selector as get_agent_selector,
    select_agents as select_agents,
)