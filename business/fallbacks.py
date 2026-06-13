"""
BEA BUSINESS LAYER — Fallbacks déterministes pour les agents analytiques.

Ces helpers prennent le relais quand le LLM local renvoie vide ou invalide.
Ils privilégient une sortie exploitable plutôt qu'un échec silencieux.
"""
from __future__ import annotations

from business.offer.schema import OfferDesign, OfferReport, PricingTier
from business.saas.schema import SaasBlueprint, SaasFeature, SaasPage, SaasReport, TechStack
from business.trade_ops.schema import TradeAgentConfig, TradeOpsSpec
from business.venture.schema import VentureOpportunity, VentureReport, VentureScore
from business.workflow.schema import BusinessWorkflow, WorkflowReport, WorkflowStep


def _topic(session, default: str = "opportunité") -> str:
    text = (session.user_input or session.mission_summary or default).strip()
    return text[:80] if text else default


def _context_hint(session, limit: int = 220) -> str:
    ctx = session.context_snapshot(limit)
    for key in ("offer-designer", "venture-builder", "workflow-architect", "saas-builder", "trade-ops"):
        if key in ctx and ctx[key].strip():
            return ctx[key].replace("\n", " ")[:limit]
    return ""


def build_venture_fallback_report(session) -> VentureReport:
    topic = _topic(session)
    sector = (session.metadata.get("trade_sector") or topic).split("\n", 1)[0][:60]
    hint = _context_hint(session)
    opportunities = [
        VentureOpportunity(
            title="Automatisation des relances",
            problem=f"Les équipes perdent du temps sur les relances liées à {topic.lower()}",
            target=f"PME et indépendants concernés par {sector}",
            offer_idea="Un service SaaS léger qui détecte les relances à faire et automatise les suivis.",
            difficulty="medium",
            short_term="Validation rapide sur un petit portefeuille de clients en 2 à 6 semaines.",
            long_term="Peut devenir une base de rétention mensuelle et de services additionnels.",
            mvp_recommendation="Inbox simple + règles de relance + export client + rappels.",
            monetization="Abonnement mensuel avec paliers selon le volume de dossiers.",
            competitors=["HubSpot", "Pipedrive"],
            risks=["Marché déjà outillé", "Nécessite une intégration propre au métier"],
            first_steps=["Interviewer 3 utilisateurs", "Lister 10 relances récurrentes", "Prototyper l'automatisation"],
            scores=VentureScore(pain=7.5, frequency=7.0, ease_sale=6.0, retention=7.5, automation=8.0, saas=8.5, ai_fit=7.0),
        ),
        VentureOpportunity(
            title="Réduction des erreurs manuelles",
            problem=f"Les erreurs de saisie ou d'oubli coûtent cher sur {topic.lower()}",
            target=f"Structures petites à moyennes sur {sector}",
            offer_idea="Un assistant de contrôle qui vérifie les informations critiques avant envoi.",
            difficulty="low",
            short_term="Peut être vendu comme audit + outil de contrôle dès le premier mois.",
            long_term="Extension naturelle vers un assistant métier complet.",
            mvp_recommendation="Checklist guidée + alertes + validation humaine.",
            monetization="Forfait de mise en place puis abonnement support.",
            competitors=["Tableaux Excel", "Contrôle manuel"],
            risks=["Adoption variable", "Dépendance aux processus du client"],
            first_steps=["Cartographier les erreurs fréquentes", "Définir les validations critiques", "Créer un flux de vérification"],
            scores=VentureScore(pain=8.0, frequency=6.0, ease_sale=7.0, retention=6.0, automation=7.0, saas=6.5, ai_fit=6.5),
        ),
        VentureOpportunity(
            title="Offre récurrente d'assistance",
            problem=f"Les clients ont besoin d'un point d'entrée simple autour de {topic.lower()}",
            target=f"Petites entreprises du secteur {sector}",
            offer_idea="Une offre d'assistance récurrente combinant réponse, triage et suivi.",
            difficulty="medium",
            short_term="Démarrable en service productisé avant passage SaaS.",
            long_term="Peut évoluer vers une plateforme multi-clients.",
            mvp_recommendation="Portail simple + réponses assistées + statut des demandes.",
            monetization="Abonnement mensuel + options premium.",
            competitors=["Support mail", "Standard téléphonique"],
            risks=["Promesse trop large", "Besoin d'un cadrage métier fort"],
            first_steps=["Définir la promesse", "Choisir un segment précis", "Écrire la première version de l'offre"],
            scores=VentureScore(pain=7.0, frequency=6.5, ease_sale=6.5, retention=7.0, automation=6.5, saas=7.5, ai_fit=7.0),
        ),
    ]
    return VentureReport(
        query=topic,
        sector=sector,
        opportunities=opportunities,
        synthesis=f"Fallback déterministe basé sur la demande et le contexte disponible. {hint}".strip(),
        raw_llm="",
    )


def build_offer_fallback_report(session) -> OfferReport:
    venture = session.metadata.get("venture_report", {})
    source = venture.get("best") or session.user_input or session.mission_summary or "demande"
    topic = _topic(session)
    context = _context_hint(session)
    title = source[:60] if source else "Offre"
    offer = OfferDesign(
        title=title,
        tagline="Une solution simple qui réduit le travail manuel.",
        problem_statement=f"Le client perd du temps et de l'argent sur {topic.lower()}.",
        value_proposition="Vous gagnez du temps, réduisez les erreurs et créez une base récurrente.",
        target_persona="Responsable opérationnel débordé dans une PME de taille moyenne",
        offer_type="hybrid",
        delivery_mode="Plateforme web avec accompagnement initial.",
        key_features=["Triage guidé", "Suivi automatisé", "Tableau de bord clair"],
        differentiators=["Positionnement métier précis", "Mise en route rapide", "Peu de friction à l'adoption"],
        objection_answers={
            "C'est trop cher": "Le coût est inférieur au temps perdu chaque mois.",
            "On n'a pas le temps de changer": "La mise en place est progressive et guidée.",
        },
        pricing_tiers=[
            PricingTier(
                name="Pro",
                price_month=149,
                price_year=1490,
                description="Accès complet avec accompagnement léger.",
                ideal_for="PME qui veulent aller vite sans équipe interne.",
            )
        ],
        monetization_model="Abonnement mensuel avec onboarding payé au démarrage.",
        upsell_path="Passage du plan Pro au plan équipe via volume et support additionnel.",
        landing_headline="Réduisez vos erreurs dès ce mois-ci",
        cta="Demander une démo",
        sales_script_opener="Je vous montre comment réduire le temps perdu sur ce process.",
    )
    return OfferReport(
        source_opportunity=title,
        offers=[offer],
        recommended=offer.title,
        synthesis=f"Fallback produit à partir du contexte business disponible. {context}".strip(),
        raw_llm="",
    )


def build_workflow_fallback_report(session) -> WorkflowReport:
    offer = session.metadata.get("offer_report", {})
    venture = session.metadata.get("venture_report", {})
    context = offer.get("recommended") or venture.get("best") or _topic(session)
    workflow = BusinessWorkflow(
        name="Onboarding et suivi automatisé",
        description=f"Workflow minimal pour traiter {context.lower()} sans friction.",
        trigger="Nouvelle demande ou nouveau client",
        goal="Réduire les délais de réponse et standardiser les relances",
        steps=[
            WorkflowStep(
                id="s1",
                name="Collecte",
                description="Collecter les informations de base et les classer.",
                actor="human",
                tools=["Formulaire", "CRM"],
                inputs=["Demande client"],
                outputs=["Dossier structuré"],
                duration_min=10,
                can_automate=False,
                automation_tip="Pré-remplir le formulaire à partir du CRM.",
            ),
            WorkflowStep(
                id="s2",
                name="Qualification",
                description="Qualifier la demande et proposer la bonne suite.",
                actor="ai",
                tools=["LLM", "Règles métier"],
                inputs=["Dossier structuré"],
                outputs=["Proposition de réponse"],
                duration_min=8,
                can_automate=True,
                automation_tip="Utiliser un prompt court et des règles de priorisation.",
            ),
            WorkflowStep(
                id="s3",
                name="Relance",
                description="Programmer et envoyer les suivis.",
                actor="automation",
                tools=["Email", "n8n"],
                inputs=["Statut du dossier"],
                outputs=["Relance envoyée"],
                duration_min=5,
                can_automate=True,
                automation_tip="Déclencher sur statut sans réponse après 48h.",
            ),
        ],
        total_duration_min=23,
        automation_ratio=0.67,
        roi_estimate="Économie estimée : 2 à 4h/semaine sur le suivi.",
        tools_required=["CRM", "n8n", "Email"],
        integrations=["Formulaire → CRM", "CRM → Email"],
        kpis=["Temps de première réponse", "Taux de relance envoyée"],
        n8n_blueprint_hint="Webhook → IF → AI → Email",
    )
    return WorkflowReport(
        context=context,
        workflows=[workflow],
        synthesis="Fallback local déterministe pour garder le pipeline opérationnel.",
        raw_llm="",
    )


def build_saas_fallback_report(session) -> SaasReport:
    venture = session.metadata.get("venture_report", {})
    offer = session.metadata.get("offer_report", {})
    source = offer.get("recommended") or venture.get("best") or _topic(session)
    product_name = source[:40] if source else "MVP"
    blueprint = SaasBlueprint(
        product_name=product_name,
        tagline="Un MVP simple à livrer vite.",
        problem=f"Le client a besoin d'une solution fiable pour {source.lower() if source else 'ce besoin'}.",
        solution="Un produit SaaS léger avec le strict nécessaire pour valider le marché.",
        target_user="PME ou indépendant avec un problème récurrent clair",
        mvp_scope="Login, tableau de bord, saisie principale, paiement et support minimal.",
        features=[
            SaasFeature(id="f1", name="Onboarding", description="Créer un compte et démarrer vite.", priority="must", effort="s", user_story="En tant qu'utilisateur, je veux créer mon compte pour commencer."),
            SaasFeature(id="f2", name="Flux principal", description="Réaliser la tâche métier principale.", priority="must", effort="m", user_story="En tant qu'utilisateur, je veux traiter mon besoin central pour obtenir de la valeur."),
            SaasFeature(id="f3", name="Paiement", description="Activer l'abonnement.", priority="should", effort="s", user_story="En tant qu'administrateur, je veux facturer pour monétiser le produit."),
        ],
        pages=[
            SaasPage(name="Dashboard", route="/dashboard", description="Vue principale", components=["StatsCard", "QuickActions"], auth_required=True),
            SaasPage(name="Settings", route="/settings", description="Paramètres du compte", components=["PlanCard"], auth_required=True),
        ],
        tech_stack=TechStack(
            frontend="Next.js + Tailwind",
            backend="FastAPI ou Next.js API routes",
            database="PostgreSQL",
            auth="Clerk ou NextAuth.js",
            hosting="Vercel",
            payments="Stripe",
            extras=["Resend", "Sentry"],
        ),
        data_model_hint="User → Account → Workspace → Record",
        api_endpoints=["GET /api/me", "POST /api/items", "GET /api/items"],
        auth_strategy="JWT + session web",
        monetization="Abonnement mensuel avec essai gratuit",
        launch_plan=["Semaine 1 : auth et structure", "Semaine 2 : flux principal", "Semaine 3 : paiement et beta"],
        build_time_weeks=3,
        solo_buildable=True,
    )
    return SaasReport(
        source=source,
        blueprints=[blueprint],
        synthesis="Fallback local déterministe pour garantir un blueprint exploitable.",
        raw_llm="",
    )


def build_trade_ops_fallback_spec(session) -> TradeOpsSpec:
    trade = (session.metadata.get("trade_sector") or _topic(session, "métier")).strip()[:40]
    company_name = session.metadata.get("company_name", "l'entreprise")
    agent_name = f"agent-{trade.lower().replace(' ', '-')}"
    config = TradeAgentConfig(
        agent_name=agent_name,
        sector=trade,
        company_name=company_name,
        system_prompt=f"Agent métier pour {trade}.",
        capabilities=["Répondre aux questions client", "Pré-qualifier une demande", "Proposer un suivi"],
        knowledge_keys=[f"{trade.lower()}_faq", f"{trade.lower()}_process"],
        suggested_workflows=["Qualification initiale", "Réponse assistée", "Relance"],
        tools_needed=["CRM", "Email", "Base de connaissances"],
        deployment_mode="web",
    )
    return TradeOpsSpec(
        trade=trade,
        company_name=company_name,
        agent_config=config,
        use_cases=[
            f"Répondre rapidement aux questions fréquentes sur {trade.lower()}",
            "Réduire le temps de traitement des demandes entrantes",
            "Standardiser les réponses et les relances",
        ],
        roi_estimate="3 à 5h/semaine économisées sur les échanges répétés.",
        setup_steps=["Définir les questions fréquentes", "Charger la base métier", "Brancher le canal de support"],
        monthly_value="Valeur mensuelle estimée : gain de temps + meilleure conversion",
        build_complexity="low",
        synthesis="Fallback local déterministe pour garder un livrable métier utilisable.",
        raw_llm="",
    )
