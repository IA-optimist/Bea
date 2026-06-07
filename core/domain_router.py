"""
BEA MAX — Domain Router V1
Détecte le domaine d'une mission et retourne le profil agents + contexte associé.
Ne crée pas de nouveaux agents — réutilise les agents existants avec un contexte domaine.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger()

DOMAIN_PROFILES: dict[str, dict] = {
    "software_dev": {
        "preferred_agents": ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
        "context_prefix": "Tu agis en tant qu'ingénieur logiciel senior.",
        "max_agents": 5,
    },
    "ai_engineer": {
        "preferred_agents": ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
        "context_prefix": "Tu agis en tant qu'ingénieur IA spécialisé en LLM et agents.",
        "max_agents": 5,
    },
    "cyber_security": {
        "preferred_agents": ["scout-research", "shadow-advisor", "map-planner", "lens-reviewer"],
        "context_prefix": "Tu agis en tant qu'analyste cybersécurité.",
        "max_agents": 4,
    },
    "automation": {
        "preferred_agents": ["map-planner", "forge-builder", "lens-reviewer"],
        "context_prefix": "Tu agis en tant qu'agent d'automatisation.",
        "max_agents": 3,
    },
    "business": {
        "preferred_agents": ["scout-research", "map-planner", "shadow-advisor", "lens-reviewer"],
        "context_prefix": "Tu agis en tant qu'analyste business.",
        "max_agents": 4,
    },
    "saas_builder": {
        "preferred_agents": ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
        "context_prefix": "Tu agis en tant qu'architecte SaaS.",
        "max_agents": 5,
    },
    "general": {
        "preferred_agents": ["map-planner", "lens-reviewer"],
        "context_prefix": "",
        "max_agents": 5,
    },
}

# Mots-clés par domaine (ordre de détection = ordre de priorité)
_DOMAIN_KEYWORDS: list[tuple[str, frozenset[str]]] = [
    ("cyber_security", frozenset({
        "security", "sécurité", "vulnerability", "vulnérabilité", "audit",
        "pentest", "scan", "exploit", "cve", "threat", "malware", "firewall",
        "injection", "xss", "sqli",
    })),
    ("ai_engineer", frozenset({
        "model", "llm", "embedding", "agent", "prompt", "fine-tune",
        "transformer", "rag", "vector", "inference", "training", "dataset",
        "neural", "gpt", "claude", "mistral",
    })),
    ("software_dev", frozenset({
        "code", "api", "function", "fonction", "class", "module", "library",
        "bug", "test", "debug", "refactor", "script", "database", "backend",
        "frontend", "endpoint", "repo", "git", "python", "javascript", "typescript",
    })),
    ("automation", frozenset({
        "automatise", "automatiser", "automate", "workflow", "trigger", "cron",
        "pipeline", "bot", "scheduler", "tâche automatique", "webhook",
    })),
    ("saas_builder", frozenset({
        "saas", "startup", "product", "landing", "stripe", "monetize",
        "subscription", "pricing", "onboarding", "dashboard", "mvp",
    })),
    ("business", frozenset({
        "business", "market", "revenue", "strategy", "analyse", "rapport",
        "kpi", "metric", "roi", "client", "prospect", "vente", "sales",
        "compétiteur", "competitor",
    })),
]


def detect_domain(goal: str) -> str:
    """
    Détection de domaine par mots-clés. Retourne le nom du domaine ou 'general'.
    Priorité dans l'ordre : cyber_security > ai_engineer > software_dev >
    automation > saas_builder > business > general.
    """
    g = goal.lower()
    for domain, keywords in _DOMAIN_KEYWORDS:
        if any(kw in g for kw in keywords):
            return domain
    return "general"


class DomainRouter:
    """Route une mission vers le profil d'agents et le contexte appropriés."""

    def route(self, goal: str) -> dict:
        """
        Retourne :
          { domain, context_prefix, preferred_agents, max_agents }
        """
        domain = detect_domain(goal)
        profile = DOMAIN_PROFILES.get(domain, DOMAIN_PROFILES["general"])
        result = {
            "domain":           domain,
            "context_prefix":   profile["context_prefix"],
            "preferred_agents": list(profile["preferred_agents"]),
            "max_agents":       profile["max_agents"],
        }
        log.info("domain_router", domain=domain, goal=goal[:60])
        return result

    def get_all_domains(self) -> list[str]:
        """Retourne la liste de tous les domaines supportés."""
        return list(DOMAIN_PROFILES.keys())


# Singleton
_router_instance: DomainRouter | None = None


def get_domain_router() -> DomainRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = DomainRouter()
    return _router_instance
