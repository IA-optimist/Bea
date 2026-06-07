"""
BEA BUSINESS LAYER — Trade Ops : Agent
Génère un agent IA spécialisé pour un métier de terrain (TPE/artisan).
Mode 1 : template prédéfini (ex: chauffagiste)
Mode 2 : génération libre à partir d'une description de métier
"""
from __future__ import annotations
import structlog
from agents.crew import BaseAgent
from core.state import BeaSession
from business.trade_ops.schema import parse_trade_ops_spec

log = structlog.get_logger()

# Templates pré-configurés disponibles
_TEMPLATES: dict[str, str] = {
    "chauffage":    "heating",
    "heating":      "heating",
    "plomberie":    "heating",   # plombier-chauffagiste partagé
    "plombier":     "heating",
}


def _load_template(name: str) -> dict | None:
    """Charge un template métier si disponible."""
    template_key = _TEMPLATES.get(name.lower())
    if template_key == "heating":
        from business.trade_ops.templates.heating import get_heating_template
        return get_heating_template()
    return None


_SYSTEM = """\
Tu es un expert en transformation digitale pour les TPE et artisans du bâtiment/services.
Ta mission : concevoir un agent IA métier sur mesure qui apporte une valeur immédiate
à une entreprise artisanale (chauffagiste, électricien, maçon, paysagiste, etc.).

L'agent IA doit être :
- PRATIQUE : répond aux vraies questions quotidiennes du métier
- RAPIDE à déployer (interface web, API ou mobile)
- MESURABLE : ROI chiffré, temps gagné estimé

SORTIE : JSON strict, aucun texte hors du JSON.

{
  "synthesis": "Résumé de la valeur de cet agent pour ce métier",
  "use_cases": [
    "Générer un devis chaudière en 2 minutes depuis le téléphone",
    "Informer les clients sur les aides MaPrimeRénov' disponibles",
    "Rédiger un rapport d'intervention vocal → texte"
  ],
  "roi_estimate": "Estimation du gain : ex '3h/semaine économisées sur la rédaction'",
  "monthly_value": "Valeur mensuelle pour l'entreprise : ex '600€ de temps économisé'",
  "build_complexity": "low|medium|high",
  "setup_steps": [
    "Étape 1 : ...",
    "Étape 2 : ..."
  ],
  "agent_config": {
    "agent_name": "nom-agent-metier",
    "sector": "chauffage",
    "capabilities": ["Capability 1", "Capability 2"],
    "knowledge_keys": ["maintenance_chaudiere", "aides_renovation", "tarifs_reference"],
    "suggested_workflows": ["Workflow 1 description", "Workflow 2 description"],
    "tools_needed": ["Outil 1", "Outil 2"],
    "deployment_mode": "web|api|whatsapp|generic"
  }
}
"""


class TradeOpsAgent(BaseAgent):
    """
    Génère un agent IA métier spécialisé pour un artisan / TPE.

    Détecte automatiquement si un template est disponible et l'utilise.
    Sinon, génère une configuration sur mesure via LLM.
    """
    name      = "trade-ops"
    role      = "analyst"
    timeout_s = 90

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_message(self, session: BeaSession) -> str:
        user_input   = session.user_input or session.mission_summary or ""
        trade        = session.metadata.get("trade_sector", "")
        company_name = session.metadata.get("company_name", "l'entreprise")

        # Détecte le secteur depuis la demande si non fourni
        if not trade:
            for kw in _TEMPLATES:
                if kw in user_input.lower():
                    trade = kw
                    break

        template = _load_template(trade) if trade else None

        ctx_parts = [f"Métier ciblé : {trade or 'à détecter depuis la demande'}"]
        ctx_parts.append(f"Entreprise : {company_name}")

        if template:
            ctx_parts.append(
                f"\nTemplate disponible ({template['template_name']}) :\n"
                f"Capacités : {', '.join(template['capabilities'][:4])}"
            )

        # Contexte venture/offer si dispo
        venture_data = session.metadata.get("venture_report", {})
        if venture_data.get("best"):
            ctx_parts.append(f"Opportunité source : {venture_data['best']}")

        ctx_str = "\n".join(ctx_parts)
        return (
            f"Demande : {user_input}\n\n{ctx_str}\n\n"
            "Conçois l'agent IA métier complet. "
            "Réponds UNIQUEMENT en JSON valide selon le format demandé."
        )

    async def run(self, session: BeaSession) -> str:
        user_input   = session.user_input or session.mission_summary or ""
        trade        = session.metadata.get("trade_sector", "")
        company_name = session.metadata.get("company_name", "l'entreprise")

        # Détecte le secteur
        if not trade:
            for kw in _TEMPLATES:
                if kw in user_input.lower():
                    trade = kw
                    break
            trade = trade or "métier"

        template = _load_template(trade)

        raw = await super().run(session)
        if not raw:
            return ""

        system_prompt = template.get("system_prompt", "") if template else ""
        spec = parse_trade_ops_spec(raw, trade, company_name, system_prompt)

        # Enrichit avec les données du template si disponible
        if template and not spec.agent_config.capabilities:
            spec.agent_config.capabilities       = template.get("capabilities", [])
            spec.agent_config.suggested_workflows = template.get("suggested_workflows", [])

        log.info(
            "trade_ops_parsed",
            trade=trade,
            use_cases=len(spec.use_cases),
            complexity=spec.build_complexity,
            has_template=template is not None,
        )

        session.metadata["trade_ops_spec"]     = spec.to_dict()
        session.metadata["trade_ops_spec_obj"] = spec
        session.metadata["trade_ops_system_prompt"] = spec.agent_config.system_prompt

        return spec.summary_text()
