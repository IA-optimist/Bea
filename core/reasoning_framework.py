"""
BEA MAX — Reasoning Framework v1
Framework de raisonnement commun pour tous les agents.

Objectif : éviter les réponses vagues, les conclusions non prouvées,
et les raisonnements faibles.

Patterns disponibles :
  1. Observation → Hypothèse → Vérification → Conclusion
  2. Décomposition en sous-problèmes
  3. Comparaison de solutions
  4. Analyse de risque
  5. Validation par preuve
  6. Distinction faits / hypothèses / inconnues
  7. Anti-hallucination

Usage :
    from core.reasoning_framework import ReasoningFramework, REASONING_BLOCK
    prompt = base_prompt + ReasoningFramework.inject(patterns=["ohvc", "fact_check"])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Patterns de raisonnement ──────────────────────────────────────────────────

class ReasoningPattern(str, Enum):
    OHVC          = "ohvc"           # Observation → Hypothèse → Vérification → Conclusion
    DECOMPOSE     = "decompose"      # Décomposition en sous-problèmes
    COMPARE       = "compare"        # Comparaison de solutions
    RISK          = "risk"           # Analyse de risque
    PROOF         = "proof"          # Validation par preuve
    FACT_CHECK    = "fact_check"     # Distinction faits / hypothèses / inconnues
    ANTI_HALLUC   = "anti_halluc"    # Anti-hallucination


_PATTERN_BLOCKS: dict[str, str] = {

    ReasoningPattern.OHVC: """\
RAISONNEMENT STRUCTURÉ (OHVC) :
  1. OBSERVATION : Que sait-on avec certitude ?
  2. HYPOTHÈSE   : Que suppose-t-on ? (marquer [HYPOTHÈSE])
  3. VÉRIFICATION: Qu'est-ce qui prouverait ou infirmerait l'hypothèse ?
  4. CONCLUSION  : Que peut-on affirmer avec les preuves disponibles ?
→ Ne jamais sauter directement à la conclusion sans O→H→V.""",

    ReasoningPattern.DECOMPOSE: """\
DÉCOMPOSITION :
  - Identifier les sous-problèmes indépendants
  - Résoudre chaque sous-problème séparément
  - Recomposer en vérifiant les interactions
  - Nommer explicitement ce qui reste non-résolu""",

    ReasoningPattern.COMPARE: """\
COMPARAISON DE SOLUTIONS :
  Pour chaque option identifiée :
  - Avantages concrets (pas génériques)
  - Inconvénients réels (pas théoriques)
  - Conditions d'applicabilité
  - Recommandation motivée avec critère de choix explicite""",

    ReasoningPattern.RISK: """\
ANALYSE DE RISQUE :
  - Risques techniques (probabilité × impact)
  - Risques métier (dépendances, délais, coûts cachés)
  - Risques d'hypothèses fausses
  - Mitigation concrète pour chaque risque ≥ moyen
  - Signaux d'alerte précoces à surveiller""",

    ReasoningPattern.PROOF: """\
VALIDATION PAR PREUVE :
  - Chaque affirmation doit être sourcée ou marquée [NON PROUVÉ]
  - Les chiffres doivent avoir une origine
  - Les estimations doivent avoir une marge d'erreur
  - "Probable" ≠ "Certain" : distinguer toujours les deux""",

    ReasoningPattern.FACT_CHECK: """\
DISTINCTION FAITS / HYPOTHÈSES / INCONNUES :
  ✅ FAIT      : vérifiable, sourcé, observable
  ⚠️ HYPOTHÈSE : raisonnable mais non prouvée — marquer explicitement
  ❓ INCONNU   : information manquante — dire "je ne sais pas"
  ❌ HALLUC    : affirmation inventée — INTERDITE
→ Si une information n'est pas disponible, dire "information manquante".""",

    ReasoningPattern.ANTI_HALLUC: """\
RÈGLE ANTI-HALLUCINATION (ABSOLUE) :
  - Ne jamais inventer des faits, chiffres, noms, dates, URLs
  - Ne jamais présenter une hypothèse comme un fait établi
  - Si incertain : "D'après les informations disponibles..." ou "Je suppose que..."
  - Si non disponible : "Je n'ai pas accès à cette information"
  - Préférer une réponse incomplète vraie à une réponse complète fausse""",
}

# Bloc complet injectable (tous les patterns)
REASONING_BLOCK_FULL: str = "\n\n".join(_PATTERN_BLOCKS.values())

# Bloc léger (OHVC + fact_check + anti_halluc) — pour agents à contexte court
REASONING_BLOCK_LIGHT: str = "\n\n".join([
    _PATTERN_BLOCKS[ReasoningPattern.OHVC],
    _PATTERN_BLOCKS[ReasoningPattern.FACT_CHECK],
    _PATTERN_BLOCKS[ReasoningPattern.ANTI_HALLUC],
])


# ── Résultat de raisonnement structuré ───────────────────────────────────────

@dataclass
class ReasoningStep:
    label: str           # "observation" | "hypothesis" | "verification" | "conclusion"
    content: str
    confidence: float    # 0.0 → 1.0
    is_fact: bool = True # False = hypothèse, None = inconnu


@dataclass
class ReasoningResult:
    pattern: str
    steps: list[ReasoningStep] = field(default_factory=list)
    conclusion: str = ""
    confidence: float = 0.0
    facts: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"[{self.pattern.upper()}] Conclusion: {self.conclusion}"]
        if self.hypotheses:
            parts.append(f"[HYPOTHÈSES] {'; '.join(self.hypotheses)}")
        if self.unknowns:
            parts.append(f"[INCONNUS] {'; '.join(self.unknowns)}")
        if self.risks:
            parts.append(f"[RISQUES] {len(self.risks)} identifiés")
        parts.append(f"[CONFIANCE] {self.confidence:.0%}")
        return "\n".join(parts)

    def is_solid(self, min_confidence: float = 0.6) -> bool:
        """True si le raisonnement est suffisamment solide pour agir."""
        return self.confidence >= min_confidence and bool(self.conclusion)


# ── API principale ────────────────────────────────────────────────────────────

class ReasoningFramework:
    """
    Framework injectable dans les system prompts des agents.

    Usage :
        # Dans system_prompt() d'un agent :
        base = "Tu es ScoutResearch..."
        return base + ReasoningFramework.inject(["ohvc", "fact_check"])

    Usage programmatique :
        result = ReasoningFramework.apply_ohvc(
            observation="Les logs montrent 3 erreurs 500 en 1h",
            hypothesis="Le service X est surchargé",
            verification="Vérifier CPU/mémoire service X",
            conclusion="Probable surcharge — requiert monitoring",
            confidence=0.7,
        )
    """

    @staticmethod
    def inject(patterns: list[str] | None = None, mode: str = "light") -> str:
        """
        Retourne un bloc de raisonnement injectable dans un system prompt.

        Args:
            patterns : liste de ReasoningPattern (str). Si None → mode
            mode     : "light" (3 patterns) | "full" (7 patterns) | "custom"
        """
        if patterns:
            blocks = []
            for p in patterns:
                block = _PATTERN_BLOCKS.get(p)
                if block:
                    blocks.append(block)
            return "\n\n" + "\n\n".join(blocks) if blocks else ""

        if mode == "full":
            return "\n\n" + REASONING_BLOCK_FULL
        return "\n\n" + REASONING_BLOCK_LIGHT  # default: light

    @staticmethod
    def apply_ohvc(
        observation: str,
        hypothesis: str,
        verification: str,
        conclusion: str,
        confidence: float = 0.5,
    ) -> ReasoningResult:
        return ReasoningResult(
            pattern="ohvc",
            steps=[
                ReasoningStep("observation",   observation,  1.0,  True),
                ReasoningStep("hypothesis",    hypothesis,   confidence, False),
                ReasoningStep("verification",  verification, confidence, False),
                ReasoningStep("conclusion",    conclusion,   confidence, True),
            ],
            conclusion=conclusion,
            confidence=confidence,
        )

    @staticmethod
    def apply_risk(
        risks: list[dict[str, Any]],
    ) -> ReasoningResult:
        """
        risks = [{"name": "...", "probability": 0.3, "impact": 0.8, "mitigation": "..."}]
        """
        scored = []
        for r in risks:
            score = r.get("probability", 0.5) * r.get("impact", 0.5)
            scored.append({**r, "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return ReasoningResult(
            pattern="risk",
            risks=scored,
            conclusion=f"{len(risks)} risques identifiés, top={scored[0]['name'] if scored else 'none'}",
            confidence=0.8,
        )

    @staticmethod
    def classify_statement(statement: str, is_verified: bool, source: str = "") -> str:
        """Classe une affirmation : FAIT / HYPOTHÈSE / INCONNU."""
        if not statement.strip():
            return "❓ INCONNU — affirmation vide"
        if is_verified and source:
            return f"✅ FAIT — {statement} [source: {source}]"
        if is_verified:
            return f"✅ FAIT — {statement}"
        if source:
            return f"⚠️ HYPOTHÈSE — {statement} [source: {source}]"
        return f"⚠️ HYPOTHÈSE — {statement} [NON PROUVÉ]"


# ── Shortcuts pour injection dans les prompts ─────────────────────────────────

# Blocs prêts à l'emploi pour les agents
INJECT_SCOUT   = ReasoningFramework.inject(["ohvc", "fact_check", "anti_halluc"])
INJECT_PLANNER = ReasoningFramework.inject(["decompose", "risk", "proof"])
INJECT_BUILDER = ReasoningFramework.inject(["fact_check", "anti_halluc", "proof"])
INJECT_REVIEWER= ReasoningFramework.inject(["proof", "fact_check", "risk"])
INJECT_ADVISOR = ReasoningFramework.inject(["compare", "risk", "anti_halluc"])
