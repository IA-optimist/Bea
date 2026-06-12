"""
BEA MAX — Knowledge Quality Filter v1
Filtre qualité pour toute connaissance externe.

But : ne jamais laisser Bea apprendre du bruit.

Score de confiance composite :
  source_type      → trust_score   (0.0 → 1.0)
  fraîcheur URL    → freshness_score
  actionabilité    → actionability_score
  score global     → accepted si >= ACCEPT_THRESHOLD

Utilisation :
    from core.learning.knowledge_filter import KnowledgeFilter, SourceType
    kf = KnowledgeFilter()
    result = kf.evaluate(url="https://docs.python.org/3/...", content="...")
    if result.accepted:
        # utiliser result
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum


# ── Types de sources ──────────────────────────────────────────────────────────

class SourceType(str, Enum):
    OFFICIAL_DOC    = "official_doc"       # docs.python.org, docs.django.com...
    GITHUB_REPO     = "github_repo"        # github.com actif
    STACKOVERFLOW   = "stackoverflow"      # stackoverflow.com, answer votée
    TECH_ARTICLE    = "tech_article"       # medium, dev.to, blog reconnu
    ARXIV_PAPER     = "arxiv_paper"        # arxiv.org
    PYPI_README     = "pypi_readme"        # pypi.org
    NEWS_TECH       = "news_tech"          # techcrunch, hn, infoq
    FORUM_GENERAL   = "forum_general"      # reddit, discord (bas score)
    MARKETING       = "marketing"          # pages commerciales, landing pages
    UNKNOWN         = "unknown"            # source non identifiée


# ── Scores de confiance par type ──────────────────────────────────────────────

_TRUST_BY_TYPE: dict[str, float] = {
    SourceType.OFFICIAL_DOC:   0.95,
    SourceType.ARXIV_PAPER:    0.90,
    SourceType.GITHUB_REPO:    0.80,
    SourceType.STACKOVERFLOW:  0.75,
    SourceType.PYPI_README:    0.70,
    SourceType.TECH_ARTICLE:   0.55,
    SourceType.NEWS_TECH:      0.50,
    SourceType.FORUM_GENERAL:  0.30,
    SourceType.MARKETING:      0.15,
    SourceType.UNKNOWN:        0.20,
}

# Seuil minimal pour accepter une source
ACCEPT_THRESHOLD = 0.55

# Domaines officiels reconnus (trust++ automatique)
_OFFICIAL_DOMAINS: frozenset[str] = frozenset({
    "docs.python.org", "docs.djangoproject.com", "fastapi.tiangolo.com",
    "docs.sqlalchemy.org", "pydantic-docs.helpmanual.io", "docs.pydantic.dev",
    "docs.docker.com", "kubernetes.io", "docs.aws.amazon.com",
    "cloud.google.com", "learn.microsoft.com", "developer.mozilla.org",
    "docs.github.com", "git-scm.com", "redis.io", "postgresql.org",
    "nginx.org", "docs.anthropic.com", "platform.openai.com",
    "langchain-ai.github.io", "docs.langchain.com",
    "arxiv.org", "pypi.org", "packaging.python.org",
})

# Domaines marketing / à bannir
_BANNED_DOMAINS: frozenset[str] = frozenset({
    "quora.com", "yahoo.com", "answers.com", "ehow.com",
    "wikihow.com",  # trop généraliste pour du technique
})

# Patterns d'URLs marketing
_MARKETING_PATTERNS = re.compile(
    r"(pricing|buy-now|get-started-free|sign-up|checkout|landing|promo|affiliate)",
    re.IGNORECASE,
)


# ── Résultat du filtre ────────────────────────────────────────────────────────

@dataclass
class FilterResult:
    url: str
    source_type: str
    trust_score: float
    freshness_score: float
    actionability_score: float
    global_score: float
    accepted: bool
    rejection_reason: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "source_type": self.source_type,
            "trust_score": round(self.trust_score, 3),
            "freshness_score": round(self.freshness_score, 3),
            "actionability_score": round(self.actionability_score, 3),
            "global_score": round(self.global_score, 3),
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "tags": self.tags,
        }


# ── Filtre principal ──────────────────────────────────────────────────────────

class KnowledgeFilter:
    """
    Filtre qualité pour toutes les connaissances entrantes.

    Flux :
        1. Déterminer le type de source (URL → SourceType)
        2. Calculer trust_score (par type + domain boost)
        3. Calculer freshness_score (heuristique sur le contenu)
        4. Calculer actionability_score (contenu actionnable ?)
        5. Score global = moyenne pondérée
        6. Accepter si score ≥ ACCEPT_THRESHOLD
    """

    def evaluate(
        self,
        url: str,
        content: str = "",
        published_year: int | None = None,
    ) -> FilterResult:
        source_type = self._detect_type(url)
        trust       = self._trust_score(url, source_type)
        freshness   = self._freshness_score(content, published_year)
        action      = self._actionability_score(content)
        global_     = self._global_score(trust, freshness, action)
        accepted    = global_ >= ACCEPT_THRESHOLD
        reason      = "" if accepted else self._rejection_reason(trust, freshness, action, url)
        tags        = self._extract_tags(source_type, global_)

        return FilterResult(
            url=url,
            source_type=source_type,
            trust_score=trust,
            freshness_score=freshness,
            actionability_score=action,
            global_score=global_,
            accepted=accepted,
            rejection_reason=reason,
            tags=tags,
        )

    def batch_evaluate(self, sources: list[dict]) -> list[FilterResult]:
        """
        Évalue plusieurs sources.
        sources = [{"url": "...", "content": "...", "published_year": 2023}]
        Retourne triées par global_score DESC.
        """
        results = [
            self.evaluate(
                url=s.get("url", ""),
                content=s.get("content", ""),
                published_year=s.get("published_year"),
            )
            for s in sources
        ]
        return sorted(results, key=lambda r: r.global_score, reverse=True)

    def filter_accepted(self, sources: list[dict]) -> list[FilterResult]:
        """Retourne uniquement les sources acceptées, triées par score."""
        return [r for r in self.batch_evaluate(sources) if r.accepted]

    # ── Détection type de source ──────────────────────────────────────────────

    def _detect_type(self, url: str) -> str:
        url_lower = url.lower()

        # Bannis explicitement
        domain = self._extract_domain(url_lower)
        if domain in _BANNED_DOMAINS:
            return SourceType.MARKETING

        # Marketing patterns
        if _MARKETING_PATTERNS.search(url_lower):
            return SourceType.MARKETING

        # Types spécifiques — avant official_doc (certains sont dans _OFFICIAL_DOMAINS)
        # GitHub
        if "github.com" in url_lower:
            return SourceType.GITHUB_REPO

        # StackOverflow / Stack Exchange
        if "stackoverflow.com" in url_lower or "stackexchange.com" in url_lower:
            return SourceType.STACKOVERFLOW

        # ArXiv — vérifié avant official_doc car arxiv.org est aussi dans _OFFICIAL_DOMAINS
        if "arxiv.org" in url_lower:
            return SourceType.ARXIV_PAPER

        # PyPI
        if "pypi.org" in url_lower:
            return SourceType.PYPI_README

        # Officiel (autres)
        if domain in _OFFICIAL_DOMAINS or any(
            url_lower.startswith(f"https://{d}") or url_lower.startswith(f"http://{d}")
            for d in _OFFICIAL_DOMAINS
        ):
            return SourceType.OFFICIAL_DOC

        # Tech news
        if any(d in url_lower for d in [
            "news.ycombinator.com", "infoq.com", "techcrunch.com",
            "thenewstack.io", "devops.com",
        ]):
            return SourceType.NEWS_TECH

        # Articles tech (medium, dev.to, hashnode, substack)
        if any(d in url_lower for d in [
            "medium.com", "dev.to", "hashnode.dev", "substack.com",
            "towardsdatascience.com", "betterprogramming.pub",
        ]):
            return SourceType.TECH_ARTICLE

        # Forums (reddit, discord, quora)
        if any(d in url_lower for d in ["reddit.com", "discord.com", "quora.com"]):
            return SourceType.FORUM_GENERAL

        return SourceType.UNKNOWN

    def _extract_domain(self, url: str) -> str:
        m = re.search(r"https?://([^/]+)", url)
        return m.group(1) if m else ""

    # ── Calcul des scores ─────────────────────────────────────────────────────

    def _trust_score(self, url: str, source_type: str) -> float:
        base = _TRUST_BY_TYPE.get(source_type, 0.20)
        domain = self._extract_domain(url.lower())
        # Boost si domaine officiel explicitement reconnu
        if domain in _OFFICIAL_DOMAINS:
            base = max(base, 0.90)
        return min(base, 1.0)

    def _freshness_score(self, content: str, published_year: int | None) -> float:
        current_year = time.localtime().tm_year

        if published_year:
            age = current_year - published_year
            if age <= 1:
                return 0.95
            if age <= 2:
                return 0.85
            if age <= 3:
                return 0.70
            if age <= 5:
                return 0.55
            return max(0.20, 0.55 - (age - 5) * 0.05)

        # Heuristique contenu : cherche des années récentes
        years_found = re.findall(r"\b(202[0-9])\b", content)
        if years_found:
            latest = max(int(y) for y in years_found)
            age = current_year - latest
            if age <= 1:
                return 0.80
            if age <= 3:
                return 0.65
            return 0.45

        return 0.60  # neutre si aucune date trouvée

    def _actionability_score(self, content: str) -> float:
        if not content:
            return 0.50  # neutre si pas de contenu

        content_lower = content.lower()
        score = 0.40  # base

        # Indicateurs positifs (contenu actionnable)
        positive_signals = [
            (r"\bdef\s+\w+\s*\(", 0.15),          # code Python
            (r"```\w*\n", 0.10),                   # blocs de code
            (r"\bexample[s]?\b", 0.05),            # exemples
            (r"\bhow to\b|\bhow-to\b", 0.05),      # tutoriels
            (r"\bbest practice[s]?\b", 0.08),      # best practices
            (r"\bstep \d|\d\.\s+\w", 0.05),        # étapes numérotées
            (r"\bimport\s+\w+", 0.08),             # imports Python
            (r"\bpip install\b", 0.05),            # dépendances
            (r"\bwarning[s]?\b|\bcaution\b", 0.04),# avertissements (utiles)
            (r"\bdo not\b|\bavoid\b|\bdon't\b", 0.04), # anti-patterns
        ]
        for pattern, bonus in positive_signals:
            if re.search(pattern, content_lower):
                score += bonus

        # Indicateurs négatifs (contenu vague / marketing)
        negative_signals = [
            (r"\bunlock\s+your\s+potential\b", -0.15),
            (r"\bgame.?changer\b", -0.10),
            (r"\brevolutionary\b|\bdisruptive\b", -0.08),
            (r"\bfree trial\b|\bsign up now\b", -0.20),
            (r"\bboost\s+your\s+(productivity|revenue)\b", -0.10),
        ]
        for pattern, penalty in negative_signals:
            if re.search(pattern, content_lower):
                score += penalty

        return max(0.0, min(1.0, score))

    def _global_score(self, trust: float, freshness: float, action: float) -> float:
        # Pondération : confiance > fraîcheur > actionabilité
        return round(trust * 0.50 + freshness * 0.30 + action * 0.20, 4)

    def _rejection_reason(
        self, trust: float, freshness: float, action: float, url: str
    ) -> str:
        reasons = []
        if trust < 0.40:
            reasons.append(f"trust trop bas ({trust:.2f}) — source douteuse ou marketing")
        if freshness < 0.40:
            reasons.append(f"contenu trop vieux ou indaté ({freshness:.2f})")
        if action < 0.30:
            reasons.append(f"contenu non actionnable ({action:.2f})")
        if _MARKETING_PATTERNS.search(url):
            reasons.append("URL contient des patterns marketing")
        return "; ".join(reasons) if reasons else "score global insuffisant"

    def _extract_tags(self, source_type: str, global_score: float) -> list[str]:
        tags = [source_type]
        if global_score >= 0.85:
            tags.append("high_quality")
        elif global_score >= 0.65:
            tags.append("good_quality")
        elif global_score >= ACCEPT_THRESHOLD:
            tags.append("acceptable")
        else:
            tags.append("rejected")
        return tags
