"""
BEA BUSINESS LAYER — Venture Builder : Agent
Analyse un secteur ou une idée et retourne des opportunités business scorées.
"""
from __future__ import annotations
import structlog
from agents.crew import BaseAgent
from core.state import BeaSession
from business.venture.schema import parse_venture_report

log = structlog.get_logger()

_SYSTEM = """\
Tu es un expert en business development, venture capital et création d'entreprise.
Ta mission : analyser un secteur ou une demande et identifier les MEILLEURES opportunités
business exploitables maintenant — en priorité des modèles récurrents (SaaS, abonnement,
service IA automatisé).

RÈGLES CRITIQUES :
- Chaque opportunité doit être RÉELLE, concrète, exploitable dans 3-6 mois
- Pas de généralités — des niches précises, des clients identifiables
- Privilégie les douleurs fortes + fréquence haute + potentiel SaaS/IA
- Minimum 3 opportunités, maximum 7 par analyse
- Le scoring doit être HONNÊTE — une opportunité risquée doit le refléter

SORTIE : JSON strict, aucun texte hors du JSON.

{
  "sector": "Nom du secteur analysé",
  "synthesis": "2-3 phrases résumant les tendances clés et la meilleure piste",
  "opportunities": [
    {
      "title": "Nom court de l'opportunité",
      "problem": "Le problème exact que ça résout (1-2 phrases)",
      "target": "Segment client précis (ex: PME BTP 10-50 salariés, France)",
      "offer_idea": "L'offre concrète proposée (1-2 phrases)",
      "difficulty": "low|medium|high",
      "short_term": "Ce qu'on peut faire en < 3 mois (revenus, validation)",
      "long_term": "Potentiel à > 6 mois (scale, exit, partenariats)",
      "mvp_recommendation": "LE premier truc à builder — précis, actionnable",
      "monetization": "Modèle : abonnement mensuel X€, commission Y%, etc.",
      "competitors": ["Concurrent 1", "Concurrent 2"],
      "risks": ["Risque 1", "Risque 2"],
      "first_steps": ["Action 1 cette semaine", "Action 2 semaine prochaine", "Action 3 mois 1"],
      "scores": {
        "pain": 8.5,
        "frequency": 7.0,
        "ease_sale": 6.0,
        "retention": 8.0,
        "automation": 7.5,
        "saas": 9.0,
        "ai_fit": 8.0
      }
    }
  ]
}

Chaque score est entre 1.0 et 10.0 (décimale autorisée).
pain = intensité de la douleur client
frequency = fréquence du besoin (quotidien=10, annuel=2)
ease_sale = facilité à vendre (cycle court, peu de décideurs = 10)
retention = rétention naturelle / stickiness
automation = peut-on automatiser ≥ 70% avec du code/IA ?
saas = peut-on facturer en récurrent ?
ai_fit = l'IA apporte-t-elle un avantage décisif sur ce marché ?
"""


class VentureBuilderAgent(BaseAgent):
    """
    Identifie et score des opportunités business dans un secteur donné.
    Retourne un VentureReport complet avec parsing robuste du JSON LLM.
    """
    name     = "venture-builder"
    role     = "analyst"
    timeout_s = 90

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_message(self, session: BeaSession) -> str:
        user_input = session.user_input or session.mission_summary or ""
        context_parts = []

        # Récupère les sorties des agents précédents si disponibles
        ctx = session.context_snapshot(600)
        for k, v in ctx.items():
            if k not in {"venture-builder"} and v:
                context_parts.append(f"[{k}]\n{v[:300]}")

        base = (
            f"Demande utilisateur : {user_input}\n\n"
            "Analyse ce secteur/cette demande et identifie les meilleures opportunités business. "
            "Réponds UNIQUEMENT en JSON valide selon le format demandé."
        )
        if context_parts:
            base += "\n\nContexte additionnel :\n" + "\n\n".join(context_parts)
        return base

    async def run(self, session: BeaSession) -> str:
        """Override pour retourner aussi le VentureReport parsé dans session."""
        raw = await super().run(session)
        if not raw:
            return ""

        query  = session.user_input or session.mission_summary or ""
        report = parse_venture_report(raw, query)
        log.info(
            "venture_builder_parsed",
            opportunities=len(report.opportunities),
            tier_a=len(report.tier_a),
            best=report.best.title if report.best else None,
        )

        # Stocke le rapport structuré dans la session pour les modules suivants
        session.metadata["venture_report"] = report.to_dict()
        session.metadata["venture_report_obj"] = report  # objet Python (non sérialisable)

        # Execute business action: create real workspace artifacts (fail-open)
        try:
            from core.business_actions import get_business_executor
            result = get_business_executor().execute(
                "venture.research_workspace",
                report.to_dict(),
                mission_id=getattr(session, "session_id", ""),
                project_name=report.sector,
            )
            if result.get("ok"):
                session.metadata["venture_artifacts"] = result
                log.info("venture_artifacts_created",
                        project_dir=result.get("project_dir"),
                        files=len(result.get("files_created", [])))
        except Exception as _e:
            log.debug("venture_artifacts_skipped", err=str(_e)[:80])

        return report.summary_text()
