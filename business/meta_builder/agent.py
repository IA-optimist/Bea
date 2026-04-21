"""
JARVIS BUSINESS LAYER — Meta Builder : Agent
Clone et adapte un système multi-agents pour un nouveau contexte métier.
Permet de dupliquer tout ou partie de la Business Layer vers un nouveau secteur.
"""
from __future__ import annotations
import structlog
from agents.crew import BaseAgent
from core.state import JarvisSession
from business.meta_builder.schema import parse_meta_build_plan

log = structlog.get_logger()

# Agents disponibles dans la Business Layer (source du clonage)
_AVAILABLE_AGENTS = [
    "venture-builder",
    "offer-designer",
    "workflow-architect",
    "saas-builder",
    "trade-ops",
]

_SYSTEM = """\
Tu es un architecte de systèmes multi-agents IA spécialisé dans le clonage et
l'adaptation de configurations d'agents pour de nouveaux contextes métier.

Ta mission : prendre un système d'agents existant et produire un plan de duplication
complet pour l'adapter à un nouveau secteur ou contexte business.

RÈGLES :
- Identifie quels agents existants sont réutilisables tels quels (schema identique)
- Identifie quels agents nécessitent un nouveau prompt système (prompt_delta)
- Propose les nouveaux templates métier à créer
- Les étapes de déploiement doivent être ordonnées et actionnables

Agents disponibles dans la Business Layer :
- venture-builder : analyse d'opportunités dans un secteur
- offer-designer : design d'offre commerciale
- workflow-architect : architecture de workflows
- saas-builder : blueprint MVP SaaS
- trade-ops : agent IA métier spécialisé

SORTIE : JSON strict, aucun texte hors du JSON.

{
  "synthesis": "Résumé : faisabilité, ce qui réutilise vs ce qui est nouveau",
  "target_name": "Nom du nouveau système cloné",
  "estimated_effort": "ex: 4-6h de configuration + tests",
  "agents_to_clone": [
    {
      "original_agent": "venture-builder",
      "cloned_name": "immo-opportunity-finder",
      "new_sector": "immobilier",
      "prompt_delta": "Ce qui change dans le prompt : focus sur marché locatif, rendement, etc."
    }
  ],
  "shared_schemas": ["VentureScore", "OfferDesign", "BusinessWorkflow"],
  "new_templates": [
    "business/trade_ops/templates/real_estate.py — template agent immobilier"
  ],
  "deploy_steps": [
    "1. Copier les schemas (aucune modification nécessaire)",
    "2. Créer les nouveaux prompts système pour chaque agent cloné",
    "3. Créer le template métier pour le nouveau secteur",
    "4. Enregistrer les agents dans registry.py",
    "5. Tester avec une demande de validation"
  ]
}
"""


class MetaBuilderAgent(BaseAgent):
    """
    Clone et adapte un système multi-agents pour un nouveau contexte.
    Produit un plan d'action complet pour dupliquer la Business Layer.
    """
    name      = "meta-builder"
    role      = "analyst"
    timeout_s = 90

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_message(self, session: JarvisSession) -> str:
        user_input   = session.user_input or session.mission_summary or ""
        source       = session.metadata.get("meta_source", "jarvis-business-layer")
        target       = session.metadata.get("meta_target", "nouveau secteur")

        agents_list  = "\n".join(f"- {a}" for a in _AVAILABLE_AGENTS)

        return (
            f"Demande : {user_input}\n\n"
            f"Système source : {source}\n"
            f"Contexte cible : {target}\n\n"
            f"Agents disponibles à cloner :\n{agents_list}\n\n"
            "Génère le plan de clonage et adaptation. "
            "Réponds UNIQUEMENT en JSON valide selon le format demandé."
        )

    async def run(self, session: JarvisSession) -> str:
        raw = await super().run(session)
        if not raw:
            return ""

        source = session.metadata.get("meta_source", "jarvis-business-layer")
        target = session.metadata.get("meta_target",
                                       session.user_input or session.mission_summary or "")
        plan   = parse_meta_build_plan(raw, source, target)
        log.info(
            "meta_builder_parsed",
            agents_to_clone=len(plan.agents_to_clone),
            new_templates=len(plan.new_templates),
        )

        session.metadata["meta_build_plan"]     = plan.to_dict()
        session.metadata["meta_build_plan_obj"] = plan

        return plan.summary_text()
