"""
BEA BUSINESS LAYER — SaaS Builder : Agent
Transforme une idée ou opportunité en spécification MVP SaaS complète.
"""
from __future__ import annotations
import structlog
from agents.crew import BaseAgent
from core.state import BeaSession
from business.saas.schema import parse_saas_report

log = structlog.get_logger()

_SYSTEM = """\
Tu es un expert en product management, architecture SaaS et développement indie.
Ta mission : transformer une idée ou opportunité en spécification MVP SaaS complète,
buildable par un solo développeur en 4-8 semaines.

RÈGLES CRITIQUES :
- Le MVP doit être MINIMALISTE — inclure UNIQUEMENT ce qui est nécessaire pour valider
- Les features MUST sont celles sans lesquelles le produit ne peut pas être vendu
- La stack technique doit être choisie pour la vitesse de développement (pas la scalabilité)
- user_story format : "En tant que [persona], je veux [action] pour [bénéfice]"
- Priorités : must / should / could / wont (MoSCoW)
- Effort : xs (< 1h) / s (1-4h) / m (4h-1j) / l (1-3j) / xl (> 3j)

SORTIE : JSON strict, aucun texte hors du JSON.

{
  "synthesis": "Résumé : pourquoi ce produit, quel est l'angle différenciant",
  "blueprints": [
    {
      "product_name": "Nom du produit",
      "tagline": "1 phrase (max 10 mots)",
      "problem": "Le problème résolu",
      "solution": "Comment le produit le résout",
      "target_user": "Persona précis",
      "mvp_scope": "Ce qui EST dans le MVP et ce qui est exclu volontairement",
      "features": [
        {
          "id": "f1",
          "name": "Nom de la feature",
          "description": "Ce que ça fait",
          "priority": "must|should|could|wont",
          "effort": "xs|s|m|l|xl",
          "user_story": "En tant que X, je veux Y pour Z"
        }
      ],
      "pages": [
        {
          "name": "Dashboard",
          "route": "/dashboard",
          "description": "Vue principale après connexion",
          "components": ["StatsCard", "RecentActivity", "QuickActions"],
          "auth_required": true
        }
      ],
      "tech_stack": {
        "frontend": "Next.js 14 + Tailwind + shadcn/ui",
        "backend": "FastAPI Python ou Next.js API routes",
        "database": "PostgreSQL + Prisma",
        "auth": "Clerk ou NextAuth.js",
        "hosting": "Vercel + Supabase",
        "payments": "Stripe",
        "extras": ["Resend (emails)", "Sentry (monitoring)"]
      },
      "data_model_hint": "User(id, email, plan) → Project(id, user_id, name) → ...",
      "api_endpoints": [
        "POST /api/auth/register",
        "GET /api/projects",
        "POST /api/projects",
        "DELETE /api/projects/:id"
      ],
      "auth_strategy": "JWT + refresh token, OAuth Google optionnel",
      "monetization": "Freemium : 3 projets gratuits, Pro 29€/m illimité",
      "launch_plan": [
        "Semaine 1-2 : Auth + CRUD de base",
        "Semaine 3-4 : Feature core + UI",
        "Semaine 5 : Stripe + onboarding",
        "Semaine 6 : Beta fermée 20 users",
        "Semaine 7-8 : Corrections + launch ProductHunt"
      ],
      "build_time_weeks": 6,
      "solo_buildable": true
    }
  ]
}
"""


class SaasBuilderAgent(BaseAgent):
    """
    Génère un blueprint MVP SaaS complet et actionnable.
    Chaîne naturelle après VentureBuilder + OfferDesigner.
    """
    name      = "saas-builder"
    role      = "analyst"
    timeout_s = 120

    def system_prompt(self) -> str:
        return _SYSTEM

    def user_message(self, session: BeaSession) -> str:
        user_input = session.user_input or session.mission_summary or ""

        # Récupère le contexte des modules précédents
        offer_data   = session.metadata.get("offer_report", {})
        venture_data = session.metadata.get("venture_report", {})

        context_parts = []

        if venture_data.get("best"):
            opps = venture_data.get("opportunities", [])
            for o in opps:
                if o.get("title") == venture_data["best"]:
                    context_parts.append(
                        f"Opportunité : {o.get('title')}\n"
                        f"Problème : {o.get('problem', '')}\n"
                        f"Cible : {o.get('target', '')}\n"
                        f"Offre : {o.get('offer_idea', '')}"
                    )
                    break

        if offer_data.get("offers"):
            best_title = offer_data.get("recommended", "")
            for o in offer_data["offers"]:
                if o.get("title") == best_title or not best_title:
                    context_parts.append(
                        f"Offre commerciale : {o.get('title')}\n"
                        f"Tagline : {o.get('tagline', '')}\n"
                        f"Persona : {o.get('target_persona', '')}\n"
                        f"Monétisation : {o.get('monetization_model', '')}"
                    )
                    break

        ctx_str = "\n\n".join(context_parts)

        return (
            f"Demande : {user_input}\n\n"
            + (f"Contexte business :\n{ctx_str}\n\n" if ctx_str else "")
            + "Génère le blueprint MVP SaaS complet. "
            "Réponds UNIQUEMENT en JSON valide selon le format demandé."
        )

    async def run(self, session: BeaSession) -> str:
        raw = await super().run(session)
        if not raw:
            return ""

        source = session.user_input or session.mission_summary or ""
        report = parse_saas_report(raw, source)
        log.info(
            "saas_builder_parsed",
            blueprints=len(report.blueprints),
            total_features=sum(len(b.features) for b in report.blueprints),
        )

        session.metadata["saas_report"]     = report.to_dict()
        session.metadata["saas_report_obj"] = report

        # Execute business action: create real MVP spec package (fail-open)
        try:
            from core.business_actions import get_business_executor
            result = get_business_executor().execute(
                "saas.mvp_spec",
                report.to_dict(),
                mission_id=getattr(session, "session_id", ""),
                project_name=report.blueprints[0].product_name if report.blueprints else "saas-mvp",
            )
            if result.get("ok"):
                session.metadata["saas_artifacts"] = result
                log.info("saas_artifacts_created",
                        project_dir=result.get("project_dir"),
                        files=len(result.get("files_created", [])))
        except Exception as _e:
            log.debug("saas_artifacts_skipped", err=str(_e)[:80])

        return report.summary_text()
