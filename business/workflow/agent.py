"""
JARVIS BUSINESS LAYER — Workflow Architect : Agent
Conçoit des workflows business structurés, identifie les automatisations possibles
et génère des hints de blueprints n8n.
"""
from __future__ import annotations
import structlog
from agents.crew import BaseAgent
from core.state import JarvisSession
from business.workflow.schema import parse_workflow_report

log = structlog.get_logger()

_SYSTEM = """\
Tu es un expert en process design, automatisation business et intégration d'outils SaaS.
Ta mission : concevoir des workflows business précis, identifier les étapes automatisables
et recommander les outils et intégrations appropriés.

RÈGLES :
- Chaque étape doit avoir un acteur clair : human / ai / automation / system
- Identifie systématiquement ce qui peut être automatisé (Zapier, n8n, Make, Python)
- Les durées doivent être réalistes — basées sur la pratique terrain
- Le ROI doit être chiffré si possible (ex: "économise 3h/semaine par commercial")
- Minimum 1 workflow, maximum 4 par réponse

SORTIE : JSON strict, aucun texte hors du JSON.

{
  "synthesis": "Vue d'ensemble : quels workflows prioritaires et pourquoi",
  "workflows": [
    {
      "name": "Nom du workflow",
      "description": "Ce que ce workflow accomplit",
      "trigger": "Ce qui déclenche le workflow (événement, horaire, action humaine)",
      "goal": "Le résultat final attendu avec une métrique si possible",
      "steps": [
        {
          "id": "s1",
          "name": "Nom de l'étape",
          "description": "Ce qui se passe exactement",
          "actor": "human|ai|automation|system",
          "tools": ["Outil 1", "Outil 2"],
          "inputs": ["Ce dont cette étape a besoin"],
          "outputs": ["Ce que cette étape produit"],
          "duration_min": 5,
          "can_automate": true,
          "automation_tip": "Comment automatiser avec n8n/Make/Python"
        }
      ],
      "total_duration_min": 45,
      "automation_ratio": 0.7,
      "roi_estimate": "Économie estimée : ex 4h/semaine par gestionnaire",
      "tools_required": ["CRM", "n8n", "Gmail API"],
      "integrations": ["Stripe → CRM", "Formulaire → Slack"],
      "kpis": ["Temps de traitement moyen", "Taux d'erreur"],
      "n8n_blueprint_hint": "Trigger: Webhook → HTTP Request → If → Send Email"
    }
  ]
}
"""


class WorkflowArchitectAgent(BaseAgent):
    """
    Conçoit des workflows business en identifiant les automatisations possibles.
    Utilise le contexte de l'OfferReport si disponible.
    """
    name      = "workflow-architect"
    role      = "analyst"
    timeout_s = 90

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_message(self, session: JarvisSession) -> str:
        user_input = session.user_input or session.mission_summary or ""

        # Récupère l'OfferReport si disponible
        offer_data   = session.metadata.get("offer_report", {})
        venture_data = session.metadata.get("venture_report", {})

        context_parts = []

        if offer_data.get("offers"):
            best = offer_data.get("recommended") or offer_data["offers"][0].get("title", "")
            context_parts.append(f"Offre cible : {best}")
            offers_summary = "\n".join(
                f"- {o.get('title')}: {o.get('tagline', '')}"
                for o in offer_data["offers"][:2]
            )
            context_parts.append(f"Offres conçues :\n{offers_summary}")

        if venture_data.get("best"):
            context_parts.append(f"Opportunité source : {venture_data['best']}")
            sector = venture_data.get("opportunities", [{}])[0]
            if sector.get("target"):
                context_parts.append(f"Segment cible : {sector['target']}")

        ctx_str = "\n".join(context_parts)

        return (
            f"Demande : {user_input}\n\n"
            + (f"Contexte :\n{ctx_str}\n\n" if ctx_str else "")
            + "Conçois les workflows business pour cette activité. "
            "Réponds UNIQUEMENT en JSON valide selon le format demandé."
        )

    async def run(self, session: JarvisSession) -> str:
        raw = await super().run(session)
        if not raw:
            return ""

        context  = session.user_input or session.mission_summary or ""
        report   = parse_workflow_report(raw, context)
        log.info(
            "workflow_architect_parsed",
            workflows=len(report.workflows),
            auto_steps=sum(
                sum(1 for s in w.steps if s.can_automate)
                for w in report.workflows
            ),
        )

        session.metadata["workflow_report"]     = report.to_dict()
        session.metadata["workflow_report_obj"] = report

        # Execute business action: create real workflow blueprint (fail-open)
        try:
            from core.business_actions import get_business_executor
            result = get_business_executor().execute(
                "workflow.blueprint",
                report.to_dict(),
                mission_id=getattr(session, "session_id", ""),
                project_name=context[:60],
            )
            if result.get("ok"):
                session.metadata["workflow_artifacts"] = result
                log.info("workflow_artifacts_created",
                        project_dir=result.get("project_dir"),
                        files=len(result.get("files_created", [])))
        except Exception as _e:
            log.debug("workflow_artifacts_skipped", err=str(_e)[:80])

        return report.summary_text()
