"""
JARVIS MAX — Agent Crew
BaseAgent + 9 agents spécialisés + registre AgentCrew.
"""
from __future__ import annotations
import asyncio
import json
import time
import structlog
from abc import ABC, abstractmethod
from langchain_core.messages import SystemMessage, HumanMessage
from core.state import JarvisSession
from agents.self_critic import SelfCriticMixin
from core.reasoning_framework import INJECT_SCOUT, INJECT_PLANNER, INJECT_BUILDER, INJECT_REVIEWER, INJECT_ADVISOR
_silent_log = __import__("structlog").get_logger(__name__)

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
    def user_message(self, session: JarvisSession) -> str: ...

    async def run(self, session: JarvisSession) -> str:
        t0 = time.monotonic()
        log.info(f"{self.name}_start", sid=session.session_id)
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
        except Exception:
            _silent_log.debug("suppressed_exception", src='crew.py')
        try:
            from core.llm_factory import LLMFactory
            factory = LLMFactory(self.s)
            _sys = self.system_prompt()
            try:
                from core.learning_loop import get_learning_loop
                _addon = await get_learning_loop().get_agent_system_prompt_addon(self.name)
                if _addon: _sys += "\n\n" + _addon
            except Exception: pass
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
            except Exception:
                _silent_log.debug("suppressed_exception", src='crew.py')
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
            except Exception:
                _silent_log.debug("suppressed_exception", src='crew.py')
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

    def _task(self, session: JarvisSession) -> str:
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
        session: "JarvisSession",
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
        session: "JarvisSession",
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


    def _ctx(self, session: JarvisSession, skip: set | None = None, limit: int = 600) -> str:
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
        return """Tu es AtlasDirector, chef d'orchestre de JarvisMax.

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

    def user_message(self, session: JarvisSession) -> str:
        mem = session.get_output("vault-memory")
        ctx = f"\nContexte mémorisé :\n{mem}" if mem else ""
        return f"Mission : {session.user_input}{ctx}"

    async def run(self, session: JarvisSession) -> str:
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
            "Tu es ScoutResearch, agent de recherche expert de JarvisMax.\n\n"
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

    def user_message(self, session: JarvisSession) -> str:
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
            "Tu es MapPlanner, agent de planification stratégique de JarvisMax.\n\n"
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

    def user_message(self, session: JarvisSession) -> str:
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
            "Tu es ForgeBuilder, agent de génération de code production-ready de JarvisMax.\n\n"
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

    def user_message(self, session: JarvisSession) -> str:
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
            "Tu es LensReviewer, agent de contrôle qualité senior de JarvisMax.\n\n"
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

    def user_message(self, session: JarvisSession) -> str:
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
            "Tu es VaultMemory, agent de mémoire de JarvisMax.\n"
            "À partir des souvenirs récupérés, formule un résumé du contexte utile.\n"
            "Indique aussi ce qui devrait être mémorisé après cette session."
        )

    def user_message(self, session: JarvisSession) -> str:
        return f"Mission : {session.user_input}\n\nSouvenirs :\n{self._recalled}"



    async def run(self, session: JarvisSession) -> str:
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
            "Tu es ShadowAdvisor V2, validateur critique structuré de JarvisMax.\n\n"
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

    def user_message(self, session: JarvisSession) -> str:
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

    async def run(self, session: JarvisSession) -> str:
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
            pass  # fail-open: context injection is best-effort
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
            "Tu es PulseOps, agent de préparation d'actions de JarvisMax.\n\n"
            "À partir des résultats des agents, liste les actions concrètes.\n\n"
            "Types disponibles :\n"
            "create_file | write_file | replace_in_file | run_command | backup_file\n\n"
            "Réponds UNIQUEMENT en JSON :\n"
            '{"actions":[{"action_type":"create_file","target":"workspace/reports/x.md",'
            '"content":"# Contenu...","description":"Créer rapport","command":"",'
            '"old_str":"","new_str":"","reversible":true}],"summary":"..."}'
        )

    def user_message(self, session: JarvisSession) -> str:
        ctx = self._ctx(session)
        return (f"Mission : {session.mission_summary}\n\n"
                f"Résultats agents :\n{ctx or '(aucun résultat)'}")

    async def run(self, session: JarvisSession) -> str:
        out = await super().run(session)
        try:
            raw = out.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            session._raw_actions = data.get("actions", [])
        except Exception as e:
            log.error("pulse_ops_parse_failed", err=str(e))
            session._raw_actions = []
        return out


# ══════════════════════════════════════════════════════════════
# 9. NIGHT WORKER (agent shell — délègue au NightWorkerEngine)
# ══════════════════════════════════════════════════════════════

class NightWorker(BaseAgent):
    name, role, timeout_s = "night-worker", "builder", 300

    def system_prompt(self) -> str:
        return (
            "Tu es NightWorker, agent de travail long de JarvisMax.\n"
            "Tu produis du contenu concret sur des missions longues.\n"
            "Code, analyses, rapports, structures — tout est permis."
        )

    def user_message(self, session: JarvisSession) -> str:
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

    def user_message(self, session: JarvisSession) -> str:
        task = self._task(session)
        return f"Mission : {session.mission_summary}\nTâche : {task}"

    async def run(self, session: JarvisSession) -> str:
        task = self._task(session)
        log.info("image_agent_start", task=task[:80], sid=session.session_id)
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
            except Exception:
                _silent_log.debug("suppressed_exception", src='crew.py')
            return out
        except Exception as e:
            log.error("image_agent_error", err=str(e)[:120])
            out = f"[ImageAgent] Erreur : {e}"
            session.set_output(self.name, out, success=False, error=str(e))
            try:
                from api.event_emitter import emit_agent_result
                emit_agent_result(session.session_id, self.name, out)
            except Exception:
                _silent_log.debug("suppressed_exception", src='crew.py')
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
    critic_max_rounds = 1        # 1 seul round de révision (latence maîtrisée)
    critic_pass_score = 6.5      # seuil légèrement plus élevé que CRITIC_PASS_SCORE global

    async def run(self, session: JarvisSession) -> str:
        return await self.run_with_self_critic(session)


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

    async def run(self, session: JarvisSession) -> str:
        return await self.run_with_self_critic(session)


# ══════════════════════════════════════════════════════════════
# AGENT CREW — Registre et dispatcher
# ══════════════════════════════════════════════════════════════

class AgentCrew:
    def __init__(self, settings):
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
        self._register_jarvis_team(settings)

    def _register_jarvis_team(self, settings) -> None:
        """Register jarvis-team agents (meta-level codebase agents). Fail-open."""
        try:
            from agents.jarvis_team import JARVIS_TEAM_AGENTS
            for agent_name, agent_cls in JARVIS_TEAM_AGENTS.items():
                try:
                    self.registry[agent_name] = agent_cls(settings)
                    log.info("agent_registered", name=agent_name, team="jarvis")
                except Exception as e:
                    log.warning("jarvis_team_agent_failed", name=agent_name, err=str(e)[:80])
        except Exception as e:
            log.debug("jarvis_team_import_skipped", err=str(e)[:80])

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

    async def run(self, name: str, session: JarvisSession) -> str:
        agent = self.registry.get(name)
        if not agent:
            log.warning("unknown_agent", name=name)
            return ""
        return await agent.run(session)

    def add(self, agent: BaseAgent):
        """Enregistre un agent personnalisé (extensibilité)."""
        self.registry[agent.name] = agent
        log.info("agent_registered", name=agent.name)


# ── AgentSelector (V1 optimisé) ──────────────────────────────────────────────

# Profils agents par rôle
AGENT_PROFILES = {
    "scout-research": {"domains": ["research", "analysis", "business", "cyber"], "cost": 1},
    "map-planner":    {"domains": ["all"], "cost": 1},
    "shadow-advisor": {"domains": ["all"], "cost": 1},
    "forge-builder":  {"domains": ["dev", "saas", "automation", "file"], "cost": 2},
    "lens-reviewer":  {"domains": ["all"], "cost": 1},
    "vault-memory":   {"domains": ["memory", "history", "context"], "cost": 1},
    "pulse-ops":      {"domains": ["ops", "monitoring", "infra"], "cost": 2},
}

MAX_AGENTS_PER_MISSION = 5

# Mission-type-first routing table (taxonomy v2)
MISSION_ROUTING: dict[str, list[str]] = {
    "coding_task":           ["forge-builder"],
    "debug_task":            ["forge-builder", "lens-reviewer"],
    "architecture_task":     ["map-planner", "lens-reviewer"],
    "system_task":           ["pulse-ops"],
    "planning_task":         ["map-planner"],
    "business_task":         ["scout-research", "map-planner"],
    "research_task":         ["scout-research"],
    "info_query":            ["scout-research"],
    "compare_query":         ["scout-research", "lens-reviewer"],
    "evaluation_task":       ["lens-reviewer"],
    "self_improvement_task": ["shadow-advisor"],
}

# Agents préférés par domaine (Phase 5 — DomainRouter)
DOMAIN_AGENT_PROFILES: dict[str, list[str]] = {
    "software_dev":  ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
    "ai_engineer":   ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
    "cyber_security":["scout-research", "shadow-advisor", "map-planner", "lens-reviewer"],
    "automation":    ["map-planner", "forge-builder", "lens-reviewer"],
    "business":      ["scout-research", "map-planner", "shadow-advisor", "lens-reviewer"],
    "saas_builder":  ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
    "general":       ["map-planner", "lens-reviewer"],
}


class AgentSelector:
    """
    Sélectionne le minimum d'agents nécessaires pour une mission.

    Règles V1 :
    - Toujours : map-planner, lens-reviewer
    - scout-research si mots-clés research/analysis/report/context
    - shadow-advisor si MEDIUM/HIGH risk ou mots-clés risk/security/delete/modify
    - forge-builder UNIQUEMENT si mots-clés code/file/create/build/write/script
    - vault-memory UNIQUEMENT si mots-clés memory/history/past/remember
    - pulse-ops UNIQUEMENT si mots-clés monitor/infra/ops/deploy/status
    - Jamais > MAX_AGENTS_PER_MISSION (5)
    """

    _ALWAYS = ["map-planner", "lens-reviewer"]

    _RESEARCH_KW = frozenset({
        "research", "recherche", "analyse", "analyser", "analysis", "report",
        "rapport", "bilan", "context", "contexte", "inspect", "audit",
        "étude", "synthèse", "investigate", "explore",
    })
    _RISK_KW = frozenset({
        "risk", "risque", "security", "sécurité", "delete", "supprimer", "drop",
        "modify", "modifier", "remove", "dangerous", "critical", "exploit",
        "vulnerability", "pentest",
    })
    _CODE_KW = frozenset({
        "code", "créer", "crée", "create", "file", "fichier", "build", "write",
        "écrire", "script", "programme", "function", "fonction", "class", "module",
        "api", "library", "test", "debug", "bug", "implement", "développe",
    })
    _MEMORY_KW = frozenset({
        "memory", "mémoire", "history", "historique", "past", "passé",
        "remember", "souviens", "rappelle", "précédent",
    })
    _OPS_KW = frozenset({
        "monitor", "monitoring", "infra", "infrastructure", "ops", "deploy",
        "deployment", "status", "cron", "pipeline", "service", "container",
    })

    _PLANNING_KW = frozenset({
        "plan", "roadmap", "étapes", "phases", "strategy", "architecture",
    })

    def select_agents(
        self,
        goal: str,
        risk_level: str = "LOW",
        domain: str = "general",
        mission_type: str = "",
        preferred_agents: list[str] | None = None,
        complexity: str = "medium",
    ) -> list[str]:
        """
        Retourne la liste minimale des agents à activer.
        Ne dépasse jamais MAX_AGENTS_PER_MISSION.
        Piloté par complexity : low=1 agent, medium=2-3, high=logique complète.
        """
        from core.mission_system import is_capability_query
        if is_capability_query(goal):
            log.info("agent_selector_capability_query", goal=goal[:60])
            return []

        g  = goal.lower()
        rl = risk_level.upper()
        cx = complexity.lower()

        # ── PolicyMode override (fail-open) ─────────────────────────────────
        try:
            from core.policy_mode import get_policy_mode_store
            _pm = get_policy_mode_store().get().value
        except Exception:
            _pm = "BALANCED"
        # Sera utilisé plus bas pour SAFE cap et UNCENSORED boost
        # ── end PolicyMode read ──────────────────────────────────────────────

        # ── MISSION_TYPE-FIRST ROUTING ────────────────────────────────────────
        if mission_type in MISSION_ROUTING:
            base = list(MISSION_ROUTING[mission_type])
            if cx == "low":
                agents = base[:1]
            elif cx == "medium":
                agents = base[:2]
            else:  # high
                agents = list(base)
                if rl in ("MEDIUM", "HIGH") and "shadow-advisor" not in agents:
                    agents.append("shadow-advisor")

            # ── Dynamic routing overlay (fail-open) ──────────────────────
            try:
                from core.dynamic_agent_router import route_agents
                agents = route_agents(
                    goal=goal,
                    mission_type=mission_type,
                    complexity=cx,
                    risk_level=rl,
                    static_candidates=agents,
                    max_agents=MAX_AGENTS_PER_MISSION,
                )
            except Exception as _dr_err:
                log.debug("dynamic_routing_skipped", err=str(_dr_err)[:60])
            # ── end dynamic routing ──────────────────────────────────────

            # ── Multimodal routing overlay (fail-open) ───────────────────
            try:
                from core.dynamic_agent_router import detect_multimodal_type, get_multimodal_agents
                _modal = detect_multimodal_type(goal)
                if _modal:
                    _modal_agents = get_multimodal_agents(_modal)
                    for _ma in _modal_agents:
                        if _ma not in agents:
                            agents.append(_ma)
                    log.info("multimodal_routing", type=_modal, agents=agents)
            except Exception:
                _silent_log.debug("suppressed_exception", src='crew.py')
            # ── end multimodal routing ───────────────────────────────────

            # Capability registry filter (fail-open, ≥10 entries)
            try:
                from memory.capability_registry import CapabilityRegistry
                from memory.decision_memory import get_decision_memory
                _dm = get_decision_memory()
                if len(_dm._entries) >= 10:
                    _reg = CapabilityRegistry()
                    _reg.build_from_memory(_dm)
                    _f = [
                        a for a in agents
                        if _reg.score_agent_for_context(a, mission_type, cx) >= 0.3
                    ]
                    if _f:
                        agents = _f
            except Exception:
                _silent_log.debug("suppressed_exception", src='crew.py')
            log.info(
                "agent_selector_mission_routing",
                agents=agents, mission_type=mission_type,
                complexity=cx, risk=risk_level, count=len(agents),
            )
            return agents

        # ── LOW → 1 agent strict ──────────────────────────────────────────────
        if cx == "low":
            agent = "forge-builder" if "code" in g else "scout-research"
            log.info(
                "agent_selector_v1",
                agents=[agent], goal=goal[:60], risk=risk_level,
                domain=domain, count=1, complexity=cx,
            )
            return [agent]

        # ── MEDIUM → 2-3 agents ───────────────────────────────────────────────
        if cx == "medium":
            agents = ["scout-research", "lens-reviewer"]
            if rl in ("MEDIUM", "HIGH"):
                agents.append("shadow-advisor")
            log.info(
                "agent_selector_v1",
                agents=agents, goal=goal[:60], risk=risk_level,
                domain=domain, count=len(agents), complexity=cx,
            )
            return agents

        # ── HIGH → logique complète (map-planner conditionnel) ────────────────
        # Base : lens-reviewer toujours, map-planner uniquement si mots planning
        agents: list[str] = ["lens-reviewer"]
        if any(kw in g for kw in self._PLANNING_KW):
            agents.insert(0, "map-planner")

        # Si un profil de domaine est fourni, utiliser ses agents préférés comme guide
        if preferred_agents:
            domain_set = preferred_agents
        else:
            domain_set = DOMAIN_AGENT_PROFILES.get(domain, DOMAIN_AGENT_PROFILES["general"])

        # scout-research : mots-clés recherche/analyse
        if any(kw in g for kw in self._RESEARCH_KW) or "scout-research" in domain_set:
            if "scout-research" not in agents:
                agents.insert(0, "scout-research")

        # shadow-advisor : MEDIUM/HIGH risk OU mots-clés sensibles
        if rl in ("MEDIUM", "HIGH") or any(kw in g for kw in self._RISK_KW):
            if "shadow-advisor" not in agents:
                agents.append("shadow-advisor")

        # forge-builder : mots-clés code/construction (indépendant du domaine)
        if any(kw in g for kw in self._CODE_KW):
            if "forge-builder" not in agents:
                agents.append("forge-builder")

        # vault-memory : mots-clés mémoire/historique
        if any(kw in g for kw in self._MEMORY_KW):
            if "vault-memory" not in agents:
                agents.insert(0, "vault-memory")

        # pulse-ops : mots-clés ops/monitoring
        if any(kw in g for kw in self._OPS_KW):
            if "pulse-ops" not in agents:
                agents.append("pulse-ops")

        # Cap strict MAX_AGENTS_PER_MISSION
        # Priorité de conservation : map-planner, lens-reviewer, shadow-advisor, scout-research, forge-builder, vault-memory, pulse-ops
        _priority_order = [
            "map-planner", "lens-reviewer", "shadow-advisor",
            "scout-research", "forge-builder", "vault-memory", "pulse-ops",
        ]
        if len(agents) > MAX_AGENTS_PER_MISSION:
            # Garder dans l'ordre de priorité
            kept = []
            for p in _priority_order:
                if p in agents and len(kept) < MAX_AGENTS_PER_MISSION:
                    kept.append(p)
            agents = kept

        log.info(
            "agent_selector_v1",
            agents=agents,
            goal=goal[:60],
            risk=risk_level,
            domain=domain,
            count=len(agents),
        )
        try:
            from memory.decision_memory import get_decision_memory, classify_mission_type
            agents = get_decision_memory().suggest_agents(
                classify_mission_type(goal, complexity), complexity, agents,
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='crew.py')

        # ── Capability registry filter (fail-open, < 1ms) ────────────────────
        try:
            from memory.capability_registry import CapabilityRegistry
            from memory.decision_memory import get_decision_memory, classify_mission_type
            _dm = get_decision_memory()
            if len(_dm._entries) >= 10:
                _reg = CapabilityRegistry()
                _reg.build_from_memory(_dm)
                _mtype = classify_mission_type(goal, complexity)

                _filtered = [
                    a for a in agents
                    if _reg.score_agent_for_context(a, _mtype, complexity) >= 0.3
                ]
                if _filtered:
                    agents = _filtered

                if complexity != "low" and len(agents) < MAX_AGENTS_PER_MISSION:
                    _recommended = _reg.get_recommended_agents(_mtype, complexity, 1)
                    for _rec in _recommended:
                        if _rec not in agents and len(agents) < MAX_AGENTS_PER_MISSION:
                            agents.append(_rec)
        except Exception:
            _silent_log.debug("suppressed_exception", src='crew.py')

        # ── PolicyMode apply ─────────────────────────────────────────────────
        try:
            if _pm == "SAFE":
                # Force 1 agent max, jamais shadow/planner
                safe_filter = [a for a in agents if a not in ("shadow-advisor", "map-planner")]
                agents = safe_filter[:1] if safe_filter else agents[:1]
            elif _pm == "UNCENSORED" and complexity != "low":
                # Boost exploration : ajoute lens-reviewer + map-planner si pas présents et pas info_query
                from memory.decision_memory import classify_mission_type
                _mt = mission_type if mission_type else ""
                if _mt not in ("info_query", "compare_query", "planning_task"):
                    if "lens-reviewer" not in agents and len(agents) < 4:
                        agents = agents + ["lens-reviewer"]
                    if "map-planner" not in agents and len(agents) < 5 and complexity == "high":
                        agents = agents + ["map-planner"]
        except Exception:
            _silent_log.debug("suppressed_exception", src='crew.py')
        # ── end PolicyMode apply ─────────────────────────────────────────────

        return agents


_selector_instance: AgentSelector | None = None


def get_agent_selector() -> AgentSelector:
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = AgentSelector()
    return _selector_instance


def select_agents(
    goal: str,
    risk_level: str = "LOW",
    domain: str = "general",
    complexity: str = "medium",
    *,
    mission_type: str = "",
) -> list[str]:
    """Module-level convenience wrapper around AgentSelector.select_agents()."""
    return get_agent_selector().select_agents(
        goal,
        risk_level=risk_level,
        domain=domain,
        mission_type=mission_type,
        complexity=complexity,
    )
