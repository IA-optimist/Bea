"""
BEA BUSINESS LAYER — Orchestrateur
Point d'entrée unique pour tous les modules business.

Rôle : instancier, chaîner et router les agents business selon la demande.
Ne remplace PAS le Core Orchestrator — s'y branche comme une extension.

Utilisation directe :
    from business.layer import BusinessLayer
    bl = BusinessLayer(settings)
    result = await bl.run("venture", session)

Via Core (recommandé) :
    Le TaskRouter détecte "venture|offre|saas|workflow|métier" et route ici.

R9 (Pass 17b): business layer never bypasses kernel.policy().
    Sensitive modules (finance, payment) are gated through security.layer
    before execution. The check is fail-open to preserve backward compat.
"""
from __future__ import annotations
import structlog
from core.state import BeaSession

log = structlog.get_logger()

# Modules that require a security gate before execution (R9)
_SENSITIVE_MODULES = {"finance"}  # extend as payment/deployment modules are added

# Mapping mot-clé → module
_INTENT_MAP: dict[str, str] = {
    # Venture Builder
    "venture":    "venture",
    "opportunit": "venture",
    "niche":      "venture",
    "secteur":    "venture",
    "marché":     "venture",
    "business":   "venture",
    # Offer Designer
    "offre":      "offer",
    "offer":      "offer",
    "pricing":    "offer",
    "prix":       "offer",
    "tarif":      "offer",
    "vente":      "offer",
    # Workflow Architect
    "workflow":   "workflow",
    "process":    "workflow",
    "automatisa": "workflow",
    "procédure":  "workflow",
    "étapes":     "workflow",
    # SaaS Builder
    "saas":       "saas",
    "mvp":        "saas",
    "applicat":   "saas",
    "logiciel":   "saas",
    "plateforme": "saas",
    # Trade Ops
    "artisan":    "trade_ops",
    "métier":     "trade_ops",
    "chauffag":   "trade_ops",
    "plombier":   "trade_ops",
    "électricien":"trade_ops",
    "terrain":    "trade_ops",
    "tpe":        "trade_ops",
    # Meta Builder
    "clone":      "meta_builder",
    "dupliqu":    "meta_builder",
    "répliqu":    "meta_builder",
    "adapter":    "meta_builder",
    # Strategy (Pass 17b)
    "stratégi":   "strategy",
    "strategy":   "strategy",
    "roadmap":    "strategy",
    "vision":     "strategy",
    "positionnement": "strategy",
    "okr":        "strategy",
    # Finance (Pass 17b)
    "finance":    "finance",
    "budget":     "finance",
    "prévision":  "finance",
    "p&l":        "finance",
    "trésorerie": "finance",
    "break-even": "finance",
    "ltv":        "finance",
    "cac":        "finance",
}

# Ordre de chaîne recommandé pour un pipeline complet
_FULL_PIPELINE: list[str] = [
    "venture", "offer", "workflow", "saas"
]


class BusinessLayer:
    """
    Orchestre les 6 modules business de la Business Layer.
    Compatible avec le BaseAgent interface — peut être appelé depuis l'orchestrateur Core.
    """

    def __init__(self, settings):
        self.s = settings
        self._agents: dict[str, object] = {}

    def _security_gate(self, module: str, session: BeaSession) -> bool:
        """
        R9: Check security layer before executing sensitive business modules.
        Fail-open: if security layer is unavailable, allow execution.
        Returns True if execution may proceed.
        """
        if module not in _SENSITIVE_MODULES:
            return True
        try:
            from security import get_security_layer
            mission_id = getattr(session, "session_id", "") or ""
            result = get_security_layer().check_action(
                action_type=f"business_{module}",
                mission_id=mission_id,
                mode="auto",
                risk_level="medium",
            )
            if not result.allowed:
                log.warning(
                    "business_security_gate_blocked",
                    module=module,
                    reason=result.reason[:80],
                    escalated=result.escalated,
                )
                return False
            return True
        except Exception as _e:
            log.debug("business_security_gate_skipped", module=module, err=str(_e)[:60])
            return True  # fail-open

    def _get_agent(self, module: str):
        """Lazy-init : instancie l'agent seulement à la première utilisation."""
        if module not in self._agents:
            if module == "venture":
                from business.venture.agent import VentureBuilderAgent
                self._agents[module] = VentureBuilderAgent(self.s)
            elif module == "offer":
                from business.offer.agent import OfferDesignerAgent
                self._agents[module] = OfferDesignerAgent(self.s)
            elif module == "workflow":
                from business.workflow.agent import WorkflowArchitectAgent
                self._agents[module] = WorkflowArchitectAgent(self.s)
            elif module == "saas":
                from business.saas.agent import SaasBuilderAgent
                self._agents[module] = SaasBuilderAgent(self.s)
            elif module == "trade_ops":
                from business.trade_ops.agent import TradeOpsAgent
                self._agents[module] = TradeOpsAgent(self.s)
            elif module == "meta_builder":
                from business.meta_builder.agent import MetaBuilderAgent
                self._agents[module] = MetaBuilderAgent(self.s)
            elif module == "strategy":                          # Pass 17b
                from business.strategy.agent import StrategyAgent
                self._agents[module] = StrategyAgent(self.s)
            elif module == "finance":                           # Pass 17b
                from business.finance.agent import FinanceAgent
                self._agents[module] = FinanceAgent(self.s)
        return self._agents.get(module)

    def detect_intent(self, text: str) -> str:
        """Détecte le module cible depuis le texte de la demande."""
        text_lower = text.lower()
        # Cherche le premier mot-clé dans le texte
        for kw, module in _INTENT_MAP.items():
            if kw in text_lower:
                return module
        return "venture"   # défaut : analyse d'opportunités

    async def run(self, module: str, session: BeaSession) -> str:
        """
        Exécute un module business spécifique.
        module : "venture"|"offer"|"workflow"|"saas"|"trade_ops"|"meta_builder"|"auto"
        """
        if module == "auto":
            module = self.detect_intent(
                session.user_input or session.mission_summary or ""
            )
            log.info("business_layer_auto_detect", module=module)

        agent = self._get_agent(module)
        if agent is None:
            log.error("business_layer_unknown_module", module=module)
            return f"Module business inconnu : {module}"

        # R9: gate sensitive modules through security layer (Pass 17b)
        if not self._security_gate(module, session):
            return f"[SECURITY] Module '{module}' bloqué par la politique de sécurité."

        log.info("business_layer_run", module=module, sid=session.session_id)
        result = await agent.run(session)
        log.info("business_layer_done", module=module, chars=len(result or ""))
        return result or ""

    async def run_pipeline(
        self,
        session: BeaSession,
        modules: list[str] | None = None,
    ) -> dict[str, str]:
        """
        Exécute une chaîne de modules en séquence (pipeline complet).
        Chaque module reçoit la session enrichie par le précédent.

        modules : liste ordonnée, ex ["venture", "offer", "saas"]
                  None → pipeline complet par défaut
        """
        pipeline = modules or _FULL_PIPELINE
        results: dict[str, str] = {}

        for module in pipeline:
            log.info("business_pipeline_step", module=module)
            result = await self.run(module, session)
            results[module] = result
            # Continue même si un module échoue (résultat vide)
            if not result:
                log.warning("business_pipeline_empty_result", module=module)

        return results

    def summary_pipeline(self, results: dict[str, str]) -> str:
        """Combine les résultats de tous les modules en un seul texte."""
        parts = []
        labels = {
            "venture":      "🎯 VENTURE ANALYSIS",
            "offer":        "💼 OFFER DESIGN",
            "workflow":     "⚙️ WORKFLOW ARCHITECTURE",
            "saas":         "🛠 SAAS BLUEPRINT",
            "trade_ops":    "🏗️ TRADE OPS",
            "meta_builder": "🔄 META BUILDER",
        }
        for module, result in results.items():
            if result:
                label = labels.get(module, module.upper())
                parts.append(f"{'='*50}\n{label}\n{'='*50}\n{result}")
        return "\n\n".join(parts)


def get_business_layer(settings) -> BusinessLayer:
    """Factory singleton-like (une instance par appel mais stateless)."""
    return BusinessLayer(settings)
