"""
JARVIS MAX — Business Knowledge Base v1
Base de connaissances business contrôlée.

Jarvis apprend progressivement :
- ce qui rend une idée vendable
- ce qui rend un business récurrent
- ce qui rend un SaaS simple à lancer
- ce qui rend une IA métier rentable
- ce qui rend un workflow métier utile

Catégories de scoring :
  pain_severity, frequency, willingness_to_pay, automation_potential,
  saas_potential, retention_potential, local_service_fit, b2b_fit,
  time_to_mvp, complexity_penalty

Usage :
    from business.business_knowledge import BusinessKnowledge, BusinessSignal
    bk = BusinessKnowledge()
    signals = bk.get_signals("saas")
    score   = bk.score_idea("SaaS gestion chauffagiste", context={...})
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ── Signal business ───────────────────────────────────────────────────────────

@dataclass
class BusinessSignal:
    category: str          # une des 10 catégories
    description: str       # la connaissance actionnable
    score_impact: float    # +/- impact sur le score final (−1.0 → +1.0)
    examples: list[str]    # exemples concrets
    applies_to: list[str]  # ["saas", "local", "b2b", "ia_metier", "all"]
    confidence: float = 0.80

    def is_positive(self) -> bool:
        return self.score_impact > 0

    def short(self) -> str:
        return f"[{self.category}] {self.description[:80]}"


# ── Catégories ────────────────────────────────────────────────────────────────

BUSINESS_CATEGORIES = {
    "pain_severity":         "Intensité de la douleur du client",
    "frequency":             "Fréquence du problème",
    "willingness_to_pay":    "Volonté à payer",
    "automation_potential":  "Potentiel d'automatisation",
    "saas_potential":        "Potentiel SaaS (récurrence)",
    "retention_potential":   "Rétention client probable",
    "local_service_fit":     "Adéquation service local",
    "b2b_fit":               "Adéquation B2B",
    "time_to_mvp":           "Rapidité à lancer un MVP",
    "complexity_penalty":    "Pénalité de complexité",
}


# ── Base de connaissances seeding ─────────────────────────────────────────────

_SEED_SIGNALS: list[dict] = [

    # ── PAIN SEVERITY ──────────────────────────────────────────────────────
    {
        "category": "pain_severity",
        "description": "Un problème qui coûte de l'argent directement (perte de chiffre, amendes, litiges) est plus vendable qu'un problème de confort.",
        "score_impact": 0.20,
        "examples": ["gestion devis sans logiciel = CA perdu", "non-conformité = amende"],
        "applies_to": ["all"],
        "confidence": 0.90,
    },
    {
        "category": "pain_severity",
        "description": "Les problèmes de conformité réglementaire créent une urgence d'achat non négociable.",
        "score_impact": 0.25,
        "examples": ["RGPD", "normes sécurité chauffage", "facturation obligatoire"],
        "applies_to": ["b2b", "local", "saas"],
        "confidence": 0.95,
    },
    {
        "category": "pain_severity",
        "description": "Un problème que le client résout par une solution manuelle coûteuse est prêt à être automatisé.",
        "score_impact": 0.15,
        "examples": ["fichier Excel partagé en équipe", "WhatsApp pour planning"],
        "applies_to": ["all"],
        "confidence": 0.85,
    },

    # ── FREQUENCY ──────────────────────────────────────────────────────────
    {
        "category": "frequency",
        "description": "Un problème quotidien > hebdomadaire > mensuel en termes de valeur perçue et rétention.",
        "score_impact": 0.20,
        "examples": ["planning quotidien vs rapport mensuel"],
        "applies_to": ["all"],
        "confidence": 0.90,
    },
    {
        "category": "frequency",
        "description": "Les tâches répétitives avec faible valeur ajoutée sont les premières candidates à l'IA.",
        "score_impact": 0.18,
        "examples": ["rédaction devis standard", "tri emails fournisseurs", "saisie commandes"],
        "applies_to": ["ia_metier", "saas"],
        "confidence": 0.88,
    },

    # ── WILLINGNESS TO PAY ─────────────────────────────────────────────────
    {
        "category": "willingness_to_pay",
        "description": "Les artisans et PME paient facilement 50-200€/mois si le ROI est visible en moins de 3 mois.",
        "score_impact": 0.20,
        "examples": ["Planify 89€/mois", "Obat 69€/mois", "Dolibarr 0€ mais services payants"],
        "applies_to": ["local", "b2b"],
        "confidence": 0.82,
    },
    {
        "category": "willingness_to_pay",
        "description": "Un SaaS remplaçant un employé (même partiel) justifie un prix 5-10× supérieur à un outil de productivité.",
        "score_impact": 0.25,
        "examples": ["assistant IA vs secrétaire mi-temps"],
        "applies_to": ["saas", "ia_metier"],
        "confidence": 0.85,
    },
    {
        "category": "willingness_to_pay",
        "description": "Les marchés B2B avec décideurs achètent sur la valeur, les marchés grand public sur le prix.",
        "score_impact": 0.15,
        "examples": ["logiciel RH enterprise vs app fitness"],
        "applies_to": ["b2b"],
        "confidence": 0.90,
    },

    # ── AUTOMATION POTENTIAL ───────────────────────────────────────────────
    {
        "category": "automation_potential",
        "description": "Un workflow avec des règles métier claires et des données structurées s'automatise en <4 semaines.",
        "score_impact": 0.20,
        "examples": ["génération devis depuis template", "relance factures impayées"],
        "applies_to": ["saas", "ia_metier"],
        "confidence": 0.85,
    },
    {
        "category": "automation_potential",
        "description": "Les tâches nécessitant du jugement humain complexe s'automatisent à 70-80% max — viser l'assistance, pas le remplacement.",
        "score_impact": -0.10,
        "examples": ["diagnostic médical", "conseil juridique complexe"],
        "applies_to": ["ia_metier"],
        "confidence": 0.88,
    },
    {
        "category": "automation_potential",
        "description": "L'IA génère le plus de valeur sur les tâches à haute fréquence ET faible complexité décisionnelle.",
        "score_impact": 0.22,
        "examples": ["tri et réponse emails standards", "génération rapports périodiques"],
        "applies_to": ["ia_metier", "saas"],
        "confidence": 0.90,
    },

    # ── SAAS POTENTIAL ─────────────────────────────────────────────────────
    {
        "category": "saas_potential",
        "description": "Un SaaS viable nécessite un marché adressable ≥ 10 000 cibles avec budget tech existant.",
        "score_impact": 0.20,
        "examples": ["chauffagistes France: ~50 000 entreprises"],
        "applies_to": ["saas"],
        "confidence": 0.80,
    },
    {
        "category": "saas_potential",
        "description": "Le SaaS vertical (secteur précis) bat le SaaS horizontal sur la rétention et l'ARPU.",
        "score_impact": 0.18,
        "examples": ["SaaS chauffagiste > SaaS artisan générique"],
        "applies_to": ["saas"],
        "confidence": 0.85,
    },
    {
        "category": "saas_potential",
        "description": "Un SaaS MVP sans vente commerciale = mort lente. Valider la vente avant de coder.",
        "score_impact": 0.0,
        "examples": ["landing page + 10 prospects contactés = validation minimale"],
        "applies_to": ["saas"],
        "confidence": 0.95,
    },

    # ── RETENTION POTENTIAL ─────────────────────────────────────────────────
    {
        "category": "retention_potential",
        "description": "Un outil qui stocke des données du client (historique, contacts, projets) crée un switching cost naturel.",
        "score_impact": 0.22,
        "examples": ["CRM", "ERP", "historique interventions"],
        "applies_to": ["saas", "b2b"],
        "confidence": 0.90,
    },
    {
        "category": "retention_potential",
        "description": "Les intégrations avec outils existants (compta, banque, ERP) augmentent la rétention de 2-3×.",
        "score_impact": 0.18,
        "examples": ["sync QuickBooks", "import CEGID", "API bancaire"],
        "applies_to": ["saas", "b2b"],
        "confidence": 0.85,
    },

    # ── LOCAL SERVICE FIT ──────────────────────────────────────────────────
    {
        "category": "local_service_fit",
        "description": "Les artisans locaux ont 3 pain points universels : planning/agenda, devis/facturation, relation client.",
        "score_impact": 0.20,
        "examples": ["plombier, électricien, chauffagiste, carreleur"],
        "applies_to": ["local"],
        "confidence": 0.90,
    },
    {
        "category": "local_service_fit",
        "description": "L'artisan local paie rarement plus de 100€/mois sans démonstration terrain.",
        "score_impact": -0.05,
        "examples": ["Planify, Obat, Facture.net"],
        "applies_to": ["local"],
        "confidence": 0.85,
    },
    {
        "category": "local_service_fit",
        "description": "Un assistant IA répondant aux appels clients (horaires, tarifs, disponibilités) a un ROI immédiat pour l'artisan.",
        "score_impact": 0.25,
        "examples": ["bot WhatsApp pour prise de RDV", "réponse automatique mails clients"],
        "applies_to": ["local", "ia_metier"],
        "confidence": 0.82,
    },

    # ── B2B FIT ─────────────────────────────────────────────────────────────
    {
        "category": "b2b_fit",
        "description": "B2B : le cycle de vente est long (2-6 mois) mais la rétention est haute (2-5 ans).",
        "score_impact": 0.10,
        "examples": ["ERP, SIRH, logiciel métier"],
        "applies_to": ["b2b"],
        "confidence": 0.90,
    },
    {
        "category": "b2b_fit",
        "description": "Un produit B2B sans ROI mesurable en 6 mois ne passe pas le renouvellement annuel.",
        "score_impact": -0.15,
        "examples": ["outil de veille sans rapport automatique"],
        "applies_to": ["b2b"],
        "confidence": 0.88,
    },

    # ── TIME TO MVP ─────────────────────────────────────────────────────────
    {
        "category": "time_to_mvp",
        "description": "Un MVP fonctionnel (pas parfait) en 4-6 semaines est préférable à un produit complet en 6 mois.",
        "score_impact": 0.20,
        "examples": ["landing + formulaire + Notion = MVP CRM", "n8n + Airtable = MVP workflow"],
        "applies_to": ["saas", "ia_metier"],
        "confidence": 0.90,
    },
    {
        "category": "time_to_mvp",
        "description": "Utiliser des no-code/low-code pour valider avant de coder : économise 80% du temps initial.",
        "score_impact": 0.15,
        "examples": ["Make.com, n8n, Retool, Bubble"],
        "applies_to": ["saas", "ia_metier", "local"],
        "confidence": 0.85,
    },

    # ── COMPLEXITY PENALTY ─────────────────────────────────────────────────
    {
        "category": "complexity_penalty",
        "description": "Chaque intégration externe (API tierce) = +2 semaines de délai et +1 point de risque.",
        "score_impact": -0.12,
        "examples": ["Stripe + compta + ERP = 3 intégrations = +6 semaines"],
        "applies_to": ["saas", "b2b"],
        "confidence": 0.85,
    },
    {
        "category": "complexity_penalty",
        "description": "Une IA qui nécessite de la donnée propre et structurée pour fonctionner a un coût d'onboarding caché élevé.",
        "score_impact": -0.18,
        "examples": ["IA de recommandation sans historique client = inutilisable J1"],
        "applies_to": ["ia_metier", "saas"],
        "confidence": 0.88,
    },
    {
        "category": "complexity_penalty",
        "description": "Un marché réglementé (santé, finance, juridique) multiplie par 3-5× le coût de conformité.",
        "score_impact": -0.25,
        "examples": ["LegalTech, MedTech = conformité RGPD/HDS/DSP2"],
        "applies_to": ["saas", "b2b"],
        "confidence": 0.92,
    },
]


# ── Base de connaissances ─────────────────────────────────────────────────────

class BusinessKnowledge:
    """
    Base de connaissances business filtrées et structurées.

    Usage :
        bk = BusinessKnowledge()
        signals = bk.get_signals("saas")           # par catégorie
        score   = bk.score_idea("SaaS chauffagiste", ["saas", "local"])
        block   = bk.to_prompt_block(["saas", "local"])  # injectable
    """

    def __init__(self):
        self._signals: list[BusinessSignal] = [
            BusinessSignal(**s) for s in _SEED_SIGNALS
        ]

    def get_signals(
        self,
        category: str | None = None,
        applies_to: str | None = None,
        positive_only: bool = False,
    ) -> list[BusinessSignal]:
        """Récupère les signaux filtrés."""
        results = self._signals

        if category:
            results = [s for s in results if s.category == category]

        if applies_to:
            results = [
                s for s in results
                if applies_to in s.applies_to or "all" in s.applies_to
            ]

        if positive_only:
            results = [s for s in results if s.score_impact > 0]

        return sorted(results, key=lambda s: abs(s.score_impact), reverse=True)

    def score_idea(
        self,
        description: str,
        context_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Score une idée business sur 10 dimensions.
        context_types : ex ["saas", "local", "ia_metier"]

        Retourne un dict avec score par catégorie et score global.
        """
        desc_lower = description.lower()
        context = set(context_types or ["all"])
        context.add("all")

        scores_by_cat: dict[str, float] = {cat: 0.50 for cat in BUSINESS_CATEGORIES}
        matched_signals: list[str] = []

        for signal in self._signals:
            # Vérifie si le signal s'applique au contexte
            if not any(t in context for t in signal.applies_to):
                continue

            # Heuristique : le signal s'applique si des mots-clés matchent
            signal_words = set(signal.description.lower().split() + sum(
                [e.lower().split() for e in signal.examples], []
            ))
            desc_words = set(desc_lower.split())
            overlap = desc_words & signal_words

            if len(overlap) >= 2 or any(
                kw in desc_lower for kw in ["chauffag", "artisan", "saas", "ia", "devis", "planif"]
            ):
                cat = signal.category
                scores_by_cat[cat] = max(
                    0.0, min(1.0, scores_by_cat[cat] + signal.score_impact)
                )
                matched_signals.append(signal.short())

        # Score global (moyenne pondérée)
        weights = {
            "pain_severity": 0.20, "frequency": 0.15, "willingness_to_pay": 0.15,
            "automation_potential": 0.10, "saas_potential": 0.10,
            "retention_potential": 0.08, "local_service_fit": 0.08,
            "b2b_fit": 0.05, "time_to_mvp": 0.05, "complexity_penalty": 0.04,
        }
        global_score = sum(
            scores_by_cat[cat] * w for cat, w in weights.items()
        )
        global_10 = round(global_score * 10, 1)

        return {
            "description": description,
            "global_score_10": global_10,
            "scores_by_category": {k: round(v, 2) for k, v in scores_by_cat.items()},
            "matched_signals": matched_signals[:8],
            "recommendation": self._recommend(global_10),
        }

    def _recommend(self, score_10: float) -> str:
        if score_10 >= 7.5:
            return "🟢 FORT POTENTIEL — Lancer validation commerciale immédiatement"
        if score_10 >= 6.0:
            return "🟡 POTENTIEL MOYEN — Tester avec 5 prospects avant de coder"
        if score_10 >= 4.5:
            return "🟠 POTENTIEL FAIBLE — Affiner le positionnement ou pivoter"
        return "🔴 RISQUÉ — Valider des hypothèses fondamentales avant tout investissement"

    def to_prompt_block(self, context_types: list[str] | None = None) -> str:
        """
        Retourne un bloc de connaissances injectable dans un prompt agent business.
        """
        context = context_types or ["all"]
        signals = self.get_signals(applies_to=context[0] if context else None)[:8]

        if not signals:
            return ""

        lines = ["## Connaissances business validées (JarvisMax)"]
        for s in signals:
            icon = "✅" if s.is_positive() else "⚠️"
            lines.append(f"{icon} [{s.category}] {s.description}")
            if s.examples:
                lines.append(f"   Ex: {', '.join(s.examples[:2])}")

        return "\n".join(lines)

    def add_signal(self, signal: BusinessSignal) -> None:
        """Ajoute un signal validé depuis le web learning."""
        self._signals.append(signal)

    def stats(self) -> dict:
        by_cat: dict[str, int] = {}
        for s in self._signals:
            by_cat[s.category] = by_cat.get(s.category, 0) + 1
        return {
            "total_signals": len(self._signals),
            "by_category": by_cat,
            "positive_signals": sum(1 for s in self._signals if s.is_positive()),
            "negative_signals": sum(1 for s in self._signals if not s.is_positive()),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: BusinessKnowledge | None = None


def get_business_knowledge() -> BusinessKnowledge:
    global _instance
    if _instance is None:
        _instance = BusinessKnowledge()
    return _instance
