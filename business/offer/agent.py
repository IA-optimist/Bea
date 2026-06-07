"""
BEA BUSINESS LAYER — Offer Designer : Agent
Transforme une opportunité business en offre commerciale structurée et vendable.
Peut travailler depuis le VentureReport d'un cycle précédent ou d'une demande directe.
"""
from __future__ import annotations
import structlog
from agents.crew import BaseAgent
from core.state import BeaSession
from business.offer.schema import parse_offer_report

log = structlog.get_logger()

_SYSTEM = """\
Tu es un expert en conception d'offres commerciales B2B et B2C, copywriting de vente,
et pricing strategy. Ta mission : transformer une opportunité brute en une offre
commerciale complète, vendable et différenciée.

RÈGLES CRITIQUES :
- L'offre doit être CONCRÈTE — pas de flou, le client doit comprendre exactement ce qu'il achète
- Le pricing doit être JUSTIFIÉ — reflète la valeur perçue, pas les coûts
- Le persona doit être PRÉCIS — un prénom, un poste, un contexte de vie
- Les objections doivent être des VRAIES objections de marché (prix, confiance, priorité)
- Minimum 1 offre, maximum 3 variantes (ex: Starter / Pro / Enterprise)

SORTIE : JSON strict, aucun texte hors du JSON.

{
  "synthesis": "Résumé stratégique : pourquoi cette offre, quel positionnement",
  "recommended": "Titre de l'offre principale recommandée",
  "offers": [
    {
      "title": "Nom de l'offre",
      "tagline": "1 phrase de vente accrocheuse (max 12 mots)",
      "problem_statement": "Le problème reformulé dans les mots du client",
      "value_proposition": "Ce que le client gagne concrètement (résultats mesurables)",
      "target_persona": "Ex: Marc, 45 ans, gérant de plomberie, 8 techniciens, débordé par l'admin",
      "offer_type": "saas|service|productized|hybrid",
      "delivery_mode": "Comment l'offre est délivrée (plateforme web, appli mobile, service géré...)",
      "key_features": ["Feature 1", "Feature 2", "Feature 3"],
      "differentiators": ["Différenciateur vs concurrents"],
      "objection_answers": {
        "C'est trop cher": "Réponse directe et convaincante",
        "On n'a pas le temps de changer": "Réponse directe et convaincante"
      },
      "pricing_tiers": [
        {
          "name": "Pro",
          "price_month": 149,
          "price_year": 1490,
          "description": "Ce qui est inclus dans ce tier",
          "ideal_for": "Pour qui ce tier est fait"
        }
      ],
      "monetization_model": "Description narrative : abonnement mensuel, freemium, etc.",
      "upsell_path": "Comment passer d'un tier à l'autre naturellement",
      "landing_headline": "Titre H1 de la landing page (max 10 mots impactants)",
      "cta": "Bouton call-to-action principal",
      "sales_script_opener": "Première phrase pour ouvrir une conversation de vente"
    }
  ]
}
"""


class OfferDesignerAgent(BaseAgent):
    """
    Conçoit une ou plusieurs offres commerciales structurées à partir d'une
    opportunité identifiée par VentureBuilderAgent ou d'une demande directe.
    """
    name      = "offer-designer"
    role      = "analyst"
    timeout_s = 90

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_message(self, session: BeaSession) -> str:
        user_input = session.user_input or session.mission_summary or ""

        # Récupère le VentureReport du cycle précédent si disponible
        venture_data = session.metadata.get("venture_report", {})
        best_opp     = None
        if venture_data.get("best"):
            opps = venture_data.get("opportunities", [])
            for o in opps:
                if o.get("title") == venture_data["best"]:
                    best_opp = o
                    break
            if not best_opp and opps:
                best_opp = opps[0]

        if best_opp:
            import json as _json
            opp_json = _json.dumps(best_opp, ensure_ascii=False, indent=2)
            best_opp.get("title", "opportunité")
            return (
                f"Opportunité à transformer en offre commerciale :\n\n{opp_json}\n\n"
                "Conçois 1 à 3 offres commerciales pour cette opportunité. "
                "Réponds UNIQUEMENT en JSON valide selon le format demandé."
            )

        # Mode direct — sans VentureReport
        return (
            f"Demande : {user_input}\n\n"
            "Conçois une ou plusieurs offres commerciales pour cette demande. "
            "Réponds UNIQUEMENT en JSON valide selon le format demandé."
        )

    async def run(self, session: BeaSession) -> str:
        raw = await super().run(session)
        if not raw:
            return ""

        venture_data = session.metadata.get("venture_report", {})
        source       = venture_data.get("best") or session.user_input or "demande"
        report       = parse_offer_report(raw, source)
        log.info(
            "offer_designer_parsed",
            offers=len(report.offers),
            recommended=report.recommended,
        )

        session.metadata["offer_report"]     = report.to_dict()
        session.metadata["offer_report_obj"] = report

        # Execute business action: create real offer package (fail-open)
        try:
            from core.business_actions import get_business_executor
            result = get_business_executor().execute(
                "offer.package",
                report.to_dict(),
                mission_id=getattr(session, "session_id", ""),
                project_name=report.recommended or "offer",
            )
            if result.get("ok"):
                session.metadata["offer_artifacts"] = result
                log.info("offer_artifacts_created",
                        project_dir=result.get("project_dir"),
                        files=len(result.get("files_created", [])))
        except Exception as _e:
            log.debug("offer_artifacts_skipped", err=str(_e)[:80])

        return report.summary_text()
