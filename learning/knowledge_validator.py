"""
BEA MAX — Knowledge Validator v1
Couche de validation avant stockage en mémoire.

Avant de persister une connaissance, Bea répond à 7 questions :
  1. Est-ce crédible ?
  2. Est-ce utile à Bea ?
  3. Est-ce réutilisable ?
  4. Est-ce compatible avec l'architecture actuelle ?
  5. Est-ce déjà connu ? (déduplication)
  6. Est-ce testable ?
  7. Est-ce dangereux ?

Verdict : KEEP | DISCARD | NEEDS_TEST
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Verdict ───────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    KEEP        = "KEEP"        # Stocker immédiatement
    DISCARD     = "DISCARD"     # Rejeter — bruit ou dangereux
    NEEDS_TEST  = "NEEDS_TEST"  # Potentiellement utile mais à vérifier


# ── Résultat de validation ────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    verdict: str                       # KEEP | DISCARD | NEEDS_TEST
    knowledge_type: str                # best_practice | anti_pattern | fix | heuristic | ...
    credibility_score: float           # 0.0 → 1.0
    utility_score: float               # 0.0 → 1.0
    reusability_score: float           # 0.0 → 1.0
    is_duplicate: bool = False
    is_dangerous: bool = False
    is_testable: bool = True
    is_compatible: bool = True
    reasons: list[str] = field(default_factory=list)
    global_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "knowledge_type": self.knowledge_type,
            "credibility_score": round(self.credibility_score, 3),
            "utility_score": round(self.utility_score, 3),
            "reusability_score": round(self.reusability_score, 3),
            "is_duplicate": self.is_duplicate,
            "is_dangerous": self.is_dangerous,
            "is_testable": self.is_testable,
            "is_compatible": self.is_compatible,
            "reasons": self.reasons,
            "global_score": round(self.global_score, 3),
        }

    def should_store(self) -> bool:
        return self.verdict == Verdict.KEEP

    def needs_testing(self) -> bool:
        return self.verdict == Verdict.NEEDS_TEST


# ── Connaissances spécifiques à Bea ───────────────────────────────────────

# Patterns architecturaux connus — utiles pour l'analyse de compatibilité
_BEA_PATTERNS = frozenset({
    "BaseAgent", "LLMFactory", "safe_invoke", "MemoryStore",
    "ExecutionGuard", "BeaSession", "orchestrator", "task_router",
    "business_layer", "knowledge_memory", "agent_memory", "vector_memory",
    "patch_builder", "self_improve", "circuit_breaker",
})

# Sujets pertinents pour Bea
_RELEVANT_TOPICS = frozenset({
    "python", "async", "asyncio", "fastapi", "docker", "postgresql",
    "qdrant", "langchain", "openai", "anthropic", "ollama",
    "multi-agent", "agent", "llm", "prompt", "memory", "embedding",
    "retry", "timeout", "fallback", "circuit breaker", "monitoring",
    "saas", "business", "workflow", "automation", "api", "json",
    "structured output", "validation", "testing", "logging",
})

# Patterns dangereux — à rejeter systématiquement
_DANGEROUS_PATTERNS = re.compile(
    r"(exec\(|eval\(|os\.system\(|subprocess\.call\(shell=True|"
    r"rm\s+-rf|drop\s+table|delete\s+from|truncate\s+table|"
    r"chmod\s+777|curl.*\|\s*bash|wget.*\|\s*sh|"
    r"hardcode.*password|store.*secret.*plain)",
    re.IGNORECASE,
)


# ── Validateur principal ──────────────────────────────────────────────────────

class KnowledgeValidator:
    """
    Valide une connaissance avant stockage.

    Usage :
        validator = KnowledgeValidator()
        result = validator.validate(
            content="Always use asyncio.wait_for() with timeouts",
            topic="python async",
            source_trust=0.90,
            existing_knowledge=["use asyncio.gather for parallel tasks"],
        )
        if result.should_store():
            # persister
    """

    # Seuils
    MIN_CREDIBILITY  = 0.40
    MIN_UTILITY      = 0.35
    MIN_REUSABILITY  = 0.30
    KEEP_THRESHOLD   = 0.55
    NEEDS_TEST_MIN   = 0.40

    def validate(
        self,
        content: str,
        topic: str = "",
        source_trust: float = 0.50,
        existing_knowledge: list[str] | None = None,
        knowledge_type: str = "best_practice",
    ) -> ValidationResult:
        """
        Valide une connaissance.

        Args:
            content          : la connaissance à valider
            topic            : le sujet (pour scoring utilité)
            source_trust     : score de confiance de la source (KnowledgeFilter)
            existing_knowledge: liste des connaissances déjà stockées (dédup)
            knowledge_type   : type présumé (best_practice/anti_pattern/fix/...)
        """
        reasons: list[str] = []

        # 1. Dangerosité (veto absolu)
        is_dangerous = bool(_DANGEROUS_PATTERNS.search(content))
        if is_dangerous:
            reasons.append("Contenu dangereux détecté — rejeté")
            return ValidationResult(
                verdict=Verdict.DISCARD,
                knowledge_type=knowledge_type,
                credibility_score=0.0,
                utility_score=0.0,
                reusability_score=0.0,
                is_dangerous=True,
                reasons=reasons,
                global_score=0.0,
            )

        # 2. Crédibilité (basée sur source_trust + heuristiques contenu)
        credibility = self._credibility(content, source_trust)
        if credibility < self.MIN_CREDIBILITY:
            reasons.append(f"Crédibilité insuffisante ({credibility:.2f})")

        # 3. Utilité pour Bea
        utility = self._utility(content, topic)
        if utility < self.MIN_UTILITY:
            reasons.append(f"Faible utilité pour Bea ({utility:.2f})")

        # 4. Réutilisabilité
        reusability = self._reusability(content)
        if reusability < self.MIN_REUSABILITY:
            reasons.append(f"Faible réutilisabilité ({reusability:.2f})")

        # 5. Compatibilité architecture
        is_compatible = self._is_compatible(content)
        if not is_compatible:
            reasons.append("Incompatible avec l'architecture Bea (pattern conflictuel)")

        # 6. Déduplication
        is_duplicate = self._is_duplicate(content, existing_knowledge or [])
        if is_duplicate:
            reasons.append("Connaissance déjà présente en mémoire")
            return ValidationResult(
                verdict=Verdict.DISCARD,
                knowledge_type=knowledge_type,
                credibility_score=credibility,
                utility_score=utility,
                reusability_score=reusability,
                is_duplicate=True,
                reasons=reasons,
                global_score=0.0,
            )

        # 7. Testabilité
        is_testable = self._is_testable(content)
        if not is_testable:
            reasons.append("Difficilement testable — vérification manuelle recommandée")

        # Score global
        global_score = (
            credibility  * 0.40
            + utility    * 0.35
            + reusability* 0.25
        )
        if not is_compatible:
            global_score *= 0.7
        if not is_testable:
            global_score *= 0.9

        # Verdict
        verdict = self._decide(global_score, credibility, utility, reusability, is_testable)

        if verdict == Verdict.KEEP and not reasons:
            reasons.append(f"Score global {global_score:.2f} ≥ {self.KEEP_THRESHOLD} — accepté")
        elif verdict == Verdict.NEEDS_TEST:
            reasons.append(f"Score intermédiaire ({global_score:.2f}) — test requis avant stockage")
        elif verdict == Verdict.DISCARD and not reasons:
            reasons.append(f"Score insuffisant ({global_score:.2f})")

        return ValidationResult(
            verdict=verdict,
            knowledge_type=knowledge_type,
            credibility_score=credibility,
            utility_score=utility,
            reusability_score=reusability,
            is_duplicate=is_duplicate,
            is_dangerous=is_dangerous,
            is_testable=is_testable,
            is_compatible=is_compatible,
            reasons=reasons,
            global_score=round(global_score, 4),
        )

    def validate_batch(
        self,
        items: list[dict[str, Any]],
        existing_knowledge: list[str] | None = None,
    ) -> list[tuple[dict, ValidationResult]]:
        """
        Valide un batch de connaissances.
        items = [{"content": "...", "topic": "...", "source_trust": 0.8, "type": "..."}]
        Retourne [(item, result), ...] triés : KEEP → NEEDS_TEST → DISCARD
        """
        existing = existing_knowledge or []
        results = []
        accumulated = list(existing)

        for item in items:
            result = self.validate(
                content=item.get("content", ""),
                topic=item.get("topic", ""),
                source_trust=item.get("source_trust", 0.50),
                existing_knowledge=accumulated,
                knowledge_type=item.get("type", "best_practice"),
            )
            results.append((item, result))
            if result.verdict == Verdict.KEEP:
                accumulated.append(item.get("content", ""))

        # Tri : KEEP > NEEDS_TEST > DISCARD
        order = {Verdict.KEEP: 0, Verdict.NEEDS_TEST: 1, Verdict.DISCARD: 2}
        results.sort(key=lambda x: order.get(x[1].verdict, 3))
        return results

    # ── Méthodes privées ──────────────────────────────────────────────────────

    def _credibility(self, content: str, source_trust: float) -> float:
        score = source_trust * 0.70  # base = confiance source

        content_lower = content.lower()

        # Boost si la connaissance cite des éléments vérifiables
        if re.search(r"\b(version \d+|python \d+\.\d+|pep \d+|rfc \d+)", content_lower):
            score += 0.10
        # Boost si code présent (plus concrète)
        if re.search(r"(```|def |class |import |async def )", content):
            score += 0.08
        # Malus si très vague
        vague = len(re.findall(
            r"\b(might|could|perhaps|maybe|sometimes|generally)\b", content_lower
        ))
        score -= vague * 0.03

        return min(max(score, 0.0), 1.0)

    def _utility(self, content: str, topic: str) -> float:
        score = 0.30  # base

        content_lower = (content + " " + topic).lower()

        # Bonus si sujet pertinent pour Bea
        matched_topics = sum(
            1 for t in _RELEVANT_TOPICS if t in content_lower
        )
        score += min(matched_topics * 0.08, 0.40)

        # Bonus si pattern Bea mentionné
        matched_patterns = sum(
            1 for p in _BEA_PATTERNS if p.lower() in content_lower
        )
        score += min(matched_patterns * 0.05, 0.20)

        # Bonus si actionnable
        if re.search(r"(use |prefer |always |never |avoid |do not )", content_lower):
            score += 0.08

        return min(score, 1.0)

    def _reusability(self, content: str) -> float:
        score = 0.40  # base

        # Indicateurs de réutilisabilité
        if len(content) < 30:
            return 0.20  # trop court

        # Code réutilisable
        if re.search(r"(def |class |pattern|template|snippet)", content):
            score += 0.25
        # Règle générale (pas cas spécifique)
        if re.search(r"\b(always|never|prefer|avoid|use .+ when)\b", content.lower()):
            score += 0.15
        # Trop spécifique → pénalité
        if re.search(r"(my project|this specific|in our case|for us)", content.lower()):
            score -= 0.20

        return min(max(score, 0.0), 1.0)

    def _is_compatible(self, content: str) -> bool:
        """
        Vérifie la compatibilité avec l'architecture Bea.
        Rejette les patterns qui contrediraient le design actuel.
        """
        content_lower = content.lower()

        # Conflits avec le design Bea
        incompatible_patterns = [
            # Bea utilise asyncio — pas de sync blocking
            r"time\.sleep\(\s*[^)]{1,10}\)",  # sleep bloquant
            # Bea utilise structlog — pas print
            r"\bprint\(.*error\b",
        ]
        for pattern in incompatible_patterns:
            if re.search(pattern, content_lower):
                return False

        return True

    def _is_duplicate(self, content: str, existing: list[str]) -> bool:
        """Déduplication simple par similarité textuelle (Jaccard)."""
        if not existing:
            return False

        words_new = set(re.findall(r"\b\w{4,}\b", content.lower()))
        if not words_new:
            return False

        for existing_content in existing:
            words_ex = set(re.findall(r"\b\w{4,}\b", existing_content.lower()))
            if not words_ex:
                continue
            intersection = words_new & words_ex
            union = words_new | words_ex
            jaccard = len(intersection) / len(union)
            if jaccard > 0.60:  # 60% de similarité = doublon
                return True

        return False

    def _is_testable(self, content: str) -> bool:
        """Une connaissance est testable si elle est suffisamment concrète."""
        # Trop court → pas testable
        if len(content.strip()) < 20:
            return False
        # Contient du code → testable
        if re.search(r"(def |class |import |```)", content):
            return True
        # Règle actionnable → testable
        if re.search(r"\b(always|never|use|avoid|prefer)\b", content.lower()):
            return True
        # Très vague → difficilement testable
        vague_ratio = len(re.findall(
            r"\b(things|stuff|etc|various|several|some|many)\b", content.lower()
        )) / max(len(content.split()), 1)
        return vague_ratio < 0.10

    def _decide(
        self,
        global_score: float,
        credibility: float,
        utility: float,
        reusability: float,
        is_testable: bool,
    ) -> str:
        if global_score >= self.KEEP_THRESHOLD and credibility >= self.MIN_CREDIBILITY:
            return Verdict.KEEP
        if global_score >= self.NEEDS_TEST_MIN:
            return Verdict.NEEDS_TEST
        return Verdict.DISCARD
