"""
JARVIS MAX — AgentFactory
Création dynamique et enregistrement d'agents spécialisés.

Problème résolu :
    Le registre agents/registry.py est statique — tout nouvel agent doit
    être codé et enregistré manuellement. AgentFactory permet de :
    1. Créer des agents dynamiques via un prompt système personnalisé
    2. Les enregistrer temporairement pour une session/run
    3. Composer des agents existants (SelfCriticMixin, WebScout)
    4. Persister les définitions d'agents custom dans workspace/

Interface :
    factory = AgentFactory(settings)

    # Créer un agent dynamique (prompt custom)
    agent = factory.create_dynamic(
        name="market-analyst",
        role="research",
        system_prompt="Tu es expert en analyse de marché...",
        timeout_s=90,
    )

    # Créer un agent spécialisé existant avec critique
    agent = factory.create_with_critic("forge-builder")

    # Lister les agents disponibles (statiques + dynamiques)
    all_agents = factory.list_agents()

    # Enregistrer pour usage dans l'orchestrateur
    factory.register(agent)
    crew = factory.build_crew()
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
import structlog

log = structlog.get_logger()

_CUSTOM_AGENTS_FILE = "custom_agents.json"
_MAX_CUSTOM_AGENTS  = 20

# Lazy imports — agents.crew dépend de langchain_core qui n'est pas toujours
# installé dans l'environnement de test.
try:
    from agents.crew import BaseAgent

except ImportError:
    class BaseAgent:                   # type: ignore[no-redef]
        name = "base"; role = "default"; timeout_s = 120
        def __init__(self, settings): self.s = settings
        def system_prompt(self) -> str: return ""
        def user_message(self, session) -> str: return ""
        def _task(self, session) -> str: return getattr(session, "mission_summary", "")
        def _ctx(self, session, **kw) -> str: return ""
        async def run(self, session) -> str: return ""




# ══════════════════════════════════════════════════════════════
# DYNAMIC AGENT
# ══════════════════════════════════════════════════════════════

class DynamicAgent(BaseAgent):
    """
    Agent générique créé dynamiquement via prompt système.
    Utile pour des agents spécialisés one-shot ou pour prototypage rapide.
    """

    def __init__(
        self,
        settings,
        name:          str,
        role:          str,
        system:        str,
        timeout_s:     int = 120,
        description:   str = "",
    ):
        super().__init__(settings)
        self.name        = name
        self.role        = role
        self._system     = system
        self.timeout_s   = timeout_s
        self.description = description

    def system_prompt(self) -> str:
        return self._system

    def user_message(self, session) -> str:
        task = self._task(session)
        ctx  = self._ctx(session)
        return (
            f"Mission : {session.mission_summary}\n"
            f"Tâche : {task}"
            + (f"\n\nContexte :\n{ctx}" if ctx else "")
        )

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "role":        self.role,
            "system":      self._system,
            "timeout_s":   self.timeout_s,
            "description": self.description,
            "created_at":  time.time(),
        }


# ══════════════════════════════════════════════════════════════
# AGENT FACTORY
# ══════════════════════════════════════════════════════════════

class AgentFactory:
    """
    Fabrique d'agents JarvisMax.
    Gère un registre local (statique + dynamique).
    """

    def __init__(self, settings):
        self.s = settings
        self._dynamic:  dict[str, DynamicAgent] = {}
        self._path      = self._resolve_path()
        self._loaded    = False

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / _CUSTOM_AGENTS_FILE

    def _load_custom(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text("utf-8"))
                for d in raw:
                    agent = DynamicAgent(
                        settings=self.s,
                        name=d["name"], role=d["role"],
                        system=d["system"],
                        timeout_s=d.get("timeout_s", 120),
                        description=d.get("description", ""),
                    )
                    self._dynamic[agent.name] = agent
                log.debug("custom_agents_loaded", count=len(self._dynamic))
        except Exception as e:
            log.warning("custom_agents_load_error", err=str(e))

    def _save_custom(self) -> None:
        try:
            all_agents = list(self._dynamic.values())[-_MAX_CUSTOM_AGENTS:]
            self._path.write_text(
                json.dumps(
                    [a.to_dict() for a in all_agents],
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("custom_agents_save_error", err=str(e))

    # ── Création ──────────────────────────────────────────────

    def create_dynamic(
        self,
        name:        str,
        role:        str          = "default",
        system_prompt: str        = "",
        timeout_s:   int          = 120,
        description: str          = "",
        persist:     bool         = False,
    ) -> DynamicAgent:
        """
        Crée un agent dynamique avec un prompt système personnalisé.

        Paramètres :
            name         : identifiant unique de l'agent (ex: "market-analyst")
            role         : rôle LLM (director/research/builder/advisor/default)
            system_prompt: prompt système complet
            timeout_s    : timeout en secondes
            description  : description humaine de l'agent
            persist      : si True, sauvegarder dans custom_agents.json
        """
        if not system_prompt:
            system_prompt = (
                f"Tu es {name}, un agent spécialisé de JarvisMax.\n"
                f"Tu analyses et traites les demandes avec expertise.\n"
                f"Sois précis, structuré et actionnable."
            )

        agent = DynamicAgent(
            settings=self.s,
            name=name,
            role=role,
            system=system_prompt,
            timeout_s=timeout_s,
            description=description,
        )

        self._dynamic[name] = agent

        if persist:
            self._load_custom()
            self._save_custom()

        log.info("dynamic_agent_created", name=name, role=role, persist=persist)
        return agent

    def create_with_critic(self, agent_name: str) -> "Any | None":
        """
        Crée une version avec auto-critique d'un agent existant.
        Retourne None si l'agent est inconnu.

        Exemple :
            agent = factory.create_with_critic("forge-builder")
            # → ForgeBuilder avec SelfCriticMixin activé
        """
        from agents.registry import AGENT_CLASSES
        from agents.self_critic import SelfCriticMixin

        cls = AGENT_CLASSES.get(agent_name)
        if cls is None:
            log.warning("create_with_critic_unknown_agent", name=agent_name)
            return None

        # Créer dynamiquement une sous-classe avec le mixin
        critic_cls = type(
            f"{cls.__name__}WithCritic",
            (SelfCriticMixin, cls),
            {
                "name":              f"{agent_name}-critic",
                "critic_enabled":    True,
                "critic_max_rounds": 2,
                "run":               SelfCriticMixin.run_with_self_critic,
            },
        )
        agent = critic_cls(self.s)
        log.info("agent_with_critic_created", base=agent_name)
        return agent

    def get_or_create(
        self,
        name:        str,
        role:        str = "default",
        system_prompt: str = "",
    ) -> Any:
        """
        Retourne un agent existant (statique ou dynamique) ou en crée un nouveau.
        Utile pour accéder à un agent par nom sans gérer l'existence.
        """
        # 1. Chercher dans les agents statiques
        from agents.registry import AGENT_CLASSES
        cls = AGENT_CLASSES.get(name)
        if cls:
            return cls(self.s)

        # 2. Chercher dans les agents dynamiques
        self._load_custom()
        if name in self._dynamic:
            return self._dynamic[name]

        # 3. Créer un agent dynamique minimal
        return self.create_dynamic(name, role, system_prompt)

    def register(self, agent: Any) -> None:
        """Enregistre un agent dans le registre local de la factory."""
        if isinstance(agent, DynamicAgent):
            self._dynamic[agent.name] = agent
        else:
            # Pour les agents statiques, on les wrappe
            self._dynamic[agent.name] = agent   # type: ignore
        log.debug("agent_registered", name=agent.name)

    # ── Accès ─────────────────────────────────────────────────

    def list_agents(self) -> dict[str, str]:
        """
        Liste tous les agents disponibles (statiques + dynamiques).
        Retourne {name: description}.
        """
        from agents.registry import AGENT_CLASSES

        self._load_custom()
        result: dict[str, str] = {}

        for name, cls in AGENT_CLASSES.items():
            result[name] = cls.__doc__[:80] if cls.__doc__ else f"Agent {name}"

        for name, agent in self._dynamic.items():
            result[name] = getattr(agent, "description", f"Agent dynamique {name}")

        return result

    def build_crew(self) -> dict[str, Any]:
        """
        Construit un crew complet (registre statique + agents dynamiques).
        Retourne {name: instance}.
        """
        from agents.registry import build_registry
        self._load_custom()
        crew = build_registry(self.s)
        crew.update(self._dynamic)
        return crew

    def remove_dynamic(self, name: str) -> bool:
        """Supprime un agent dynamique. Retourne True si trouvé."""
        self._load_custom()
        if name in self._dynamic:
            del self._dynamic[name]
            self._save_custom()
            log.info("dynamic_agent_removed", name=name)
            return True
        return False

    def clear_dynamic(self) -> None:
        """Supprime tous les agents dynamiques (pour tests)."""
        self._dynamic.clear()
        self._save_custom()
