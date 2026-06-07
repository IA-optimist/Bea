"""
BEA MAX — Agent Registry
Point d'entrée centralisé pour l'instanciation et la résolution des agents.

Utilisation :
    from agents.registry import build_registry, AGENT_CLASSES
    registry = build_registry(settings)
    agent    = registry["scout-research"]

Le registre est indépendant de BeaOrchestrator :
il peut être utilisé directement par tout composant du pipeline.
"""
from __future__ import annotations

from agents.crew import (
    AtlasDirector,
    ScoutResearch,
    LensReviewer,
    VaultMemory,
    ShadowAdvisor,
    PulseOps,
    NightWorker,
    # Variants avec auto-critique activée (SelfCriticMixin, 1 round de révision)
    ForgeBuilderWithCritic,
    MapPlannerWithCritic,
)
from agents.web_scout import WebScoutResearch

# ── Business Layer agents ──────────────────────────────────────
from business.venture.agent  import VentureBuilderAgent
from business.offer.agent    import OfferDesignerAgent
from business.workflow.agent import WorkflowArchitectAgent
from business.saas.agent     import SaasBuilderAgent
from business.trade_ops.agent import TradeOpsAgent
from business.meta_builder.agent import MetaBuilderAgent
from agents.openhands_agent import OpenHandsAgent

# ── Catalogue complet des agents disponibles ──────────────────
# Les variants WithCritic remplacent les agents de base pour map-planner et forge-builder.
# Même nom, même interface — transparence totale pour l'orchestrateur.
AGENT_CLASSES: dict[str, type] = {
    # ── Core agents ───────────────────────────────────────────
    "atlas-director": AtlasDirector,          # directeur multi-cycles (cloud préféré)
    "scout-research": ScoutResearch,          # recherche et synthèse (LLM-only)
    "web-scout":      WebScoutResearch,       # recherche web réelle via Playwright
    "map-planner":    MapPlannerWithCritic,   # planification + auto-critique (1 round)
    "forge-builder":  ForgeBuilderWithCritic, # génération de code + auto-critique (1 round)
    "lens-reviewer":  LensReviewer,           # contrôle qualité
    "vault-memory":   VaultMemory,            # rappel mémoire long-terme
    "shadow-advisor": ShadowAdvisor,          # angles alternatifs (local Ollama)
    "pulse-ops":      PulseOps,               # préparation d'actions
    "night-worker":   NightWorker,            # travail long multi-cycles
    # ── Business Layer ────────────────────────────────────────
    "venture-builder":  VentureBuilderAgent,    # analyse d'opportunités business
    "offer-designer":   OfferDesignerAgent,     # design d'offre commerciale
    "workflow-architect": WorkflowArchitectAgent, # architecture de workflows
    "saas-builder":     SaasBuilderAgent,       # blueprint MVP SaaS
    "trade-ops":        TradeOpsAgent,          # agent IA métier (chauffagiste, etc.)
    "meta-builder":     MetaBuilderAgent,       # clonage de systèmes multi-agents
    "openhands":        OpenHandsAgent,         # Délégation de code complexe au backend OpenHands
}


def build_registry(settings) -> dict:
    """
    Instancie tous les agents avec les settings fournis.
    Retourne un dict {nom: instance}.

    Chaque agent reçoit settings pour accéder à get_llm(), bea_root, etc.
    Aucun LLM n'est instancié ici — les agents le font en lazy à la première invocation.
    """
    return {name: cls(settings) for name, cls in AGENT_CLASSES.items()}


def get_agent(name: str, settings) -> object | None:
    """
    Retourne une instance de l'agent demandé, ou None si inconnu.
    Utile pour un accès ponctuel sans instancier tout le registre.
    """
    cls = AGENT_CLASSES.get(name)
    if cls is None:
        return None
    return cls(settings)
