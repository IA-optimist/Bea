"""Mission intent, risk, complexity, and approval analysis helpers."""
from __future__ import annotations

from enum import Enum

import structlog

log = structlog.get_logger()
# ── Capability Demo ───────────────────────────────────────────────────────────

CAPABILITY_DEMO = """Voici ce que je peux exécuter concrètement :

🔧 Développement
- Générer une API REST complète avec FastAPI + Docker
- Analyser un codebase et proposer une refactorisation
- Détecter des bugs et corriger le code source

🔍 Analyse & Recherche
- Analyser l'architecture d'un SaaS et identifier les risques
- Comparer des solutions techniques (ex: FastAPI vs Flask)
- Faire un audit de sécurité sur du code Python

📋 Planification
- Créer un plan business structuré pour un projet SaaS
- Générer une roadmap technique par phases
- Définir une architecture microservices

⚙️ Automatisation
- Concevoir un workflow n8n pour automatiser des tâches
- Créer des scripts de déploiement Docker/CI-CD
- Intégrer des APIs tierces

Donne-moi une mission concrète pour commencer."""

_CAPABILITY_PATTERNS = (
    "ce que tu peux faire", "tes capacités", "présente toi", "présente-toi",
    "what can you do", "capabilities", "que sais-tu faire", "tu sais faire quoi",
    "explique ce que tu sais", "comment tu peux m'aider", "tu peux faire quoi",
)


def is_capability_query(goal: str) -> bool:
    """Retourne True si le goal est une requête de présentation des capacités."""
    g = goal.lower()
    return any(p in g for p in _CAPABILITY_PATTERNS)


# ── Intention de la mission ───────────────────────────────────────────────────

class MissionIntent(str, Enum):
    ANALYZE  = "ANALYZE"   # analyser, inspecter, comprendre
    CREATE   = "CREATE"    # créer, générer, construire
    IMPROVE  = "IMPROVE"   # améliorer, optimiser, refactorer
    MONITOR  = "MONITOR"   # surveiller, vérifier, monitorer
    REVIEW   = "REVIEW"    # revoir, valider, critiquer
    PLAN     = "PLAN"      # planifier, organiser
    SEARCH   = "SEARCH"    # chercher, trouver, explorer
    OTHER    = "OTHER"     # autre / indéterminé


# Mots-clés d'intention
_INTENT_KEYWORDS: dict[MissionIntent, list[str]] = {
    MissionIntent.ANALYZE:  ["analys", "inspect", "comprend", "debug", "diagnos",
                              "audit", "examine", "check", "vérifie"],
    MissionIntent.CREATE:   ["crée", "génère", "construis", "build", "generate",
                              "écris", "write", "make", "new", "nouveau", "ajoute"],
    MissionIntent.IMPROVE:  ["améliore", "optimis", "refactor", "fix", "corrige",
                              "upgrade", "enhance", "mieux", "better", "accélère"],
    MissionIntent.MONITOR:  ["surveille", "monit", "watch", "observe", "suivi",
                              "track", "log", "alert"],
    MissionIntent.REVIEW:   ["revois", "review", "valide", "critique", "évalue",
                              "assess", "juge", "quality"],
    MissionIntent.PLAN:     ["planifie", "plan", "organise", "stratégie", "roadmap",
                              "design", "architecture", "structure"],
    MissionIntent.SEARCH:   ["cherche", "search", "trouve", "find", "explore",
                              "research", "discover"],
}


def detect_intent(text: str) -> MissionIntent:
    """Détecte l'intention principale à partir du texte."""
    t = text.lower()
    best       = MissionIntent.OTHER
    best_count = 0
    for intent, keywords in _INTENT_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in t)
        if count > best_count:
            best_count = count
            best       = intent
    return best


# ── Classification d'action basée sur le texte du goal ───────────────────────

# Mots-clés indiquant une action d'écriture / modification fichier
_WRITE_KEYWORDS = frozenset({
    "write", "create", "update", "delete", "save", "mkdir", "remove",
    "edit", "fichier", "file", "workspace", "crée", "créer", "supprimer",
    "écrire", "modifier", "touch", "ajoute", "genere", "génère", "build",
    "nouveau", "new",
})

_RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def classify_action(goal: str) -> tuple[str, str]:
    """
    Classifie action_type et risk_level depuis le texte du goal.

    Toute action dont le goal contient des mots-clés d'écriture (write, create,
    update, delete, save, mkdir, remove, edit, fichier, file, workspace…)
    est classée action_type='write' et risk_level='MEDIUM' minimum.

    Retourne : (action_type, risk_level)
    """
    t = goal.lower()
    if any(kw in t for kw in _WRITE_KEYWORDS):
        return ("write", "MEDIUM")
    return ("analyze", "LOW")


# ── Risk Scoring numérique 0-10 (Phase 4) ────────────────────────────────────

_RISK_KW_DESTRUCTIVE = frozenset({
    "delete", "remove", "drop", "rm", "format", "supprim", "efface", "wipe", "purge", "destroy",
})
_RISK_KW_WRITE = frozenset({
    "create", "write", "update", "save", "mkdir", "edit", "fichier", "file",
    "crée", "créer", "écrire", "modifier", "genere", "génère", "build", "new", "nouveau",
})
_RISK_KW_SYSTEM = frozenset({
    "docker", "container", "restart", "deploy", "systemctl", "daemon",
})
_RISK_KW_NETWORK = frozenset({
    "api", "http", "request", "send", "post", "webhook", "endpoint", "curl",
})


def compute_risk_score(goal: str, plan_steps: list | None = None) -> int:
    """
    Calcule un score de risque numérique 0–10.

    Points :
      - Destructif (delete, remove, drop…) → +4
      - Écriture  (create, write, update…) → +2
      - Système   (docker, restart…)       → +3
      - Réseau    (api, http, post…)       → +1
      - Plan long (> 5 étapes)             → +1

    Mapping :
      0-3  → LOW
      4-6  → MEDIUM
      7-10 → HIGH
    """
    t     = goal.lower()
    score = 0

    if any(kw in t for kw in _RISK_KW_DESTRUCTIVE):
        score += 4
    if any(kw in t for kw in _RISK_KW_WRITE):
        score += 2
    if any(kw in t for kw in _RISK_KW_SYSTEM):
        score += 3
    if any(kw in t for kw in _RISK_KW_NETWORK):
        score += 1

    if plan_steps and len(plan_steps) > 5:
        score += 1

    return min(score, 10)


def risk_score_to_level(score: int) -> str:
    """Convertit un score numérique en niveau textuel."""
    if score <= 3:
        return "LOW"
    if score <= 6:
        return "MEDIUM"
    return "HIGH"


# ── Complexity Score (mission_complexity_score) ───────────────────────────────

_COMPLEXITY_LOW_KW = frozenset({
    "c'est quoi", "explique", "résume", "qu'est-ce que", "définition",
    "what is", "explain", "summary", "define", "simple question",
})
_COMPLEXITY_HIGH_KW = frozenset({
    "code", "créé", "développe", "architecture", "audit", "sécurité",
    "système complet", "déploie", "build", "implement", "create", "generate",
})


def compute_complexity(goal: str, risk_score: int) -> str:
    """
    Calcule la complexité d'une mission : "low", "medium", ou "high".

    HIGH  : mots-clés code/build/architecture, risk >= 4, ou goal > 200 chars
    LOW   : mots-clés question simple, goal < 80 chars, risk 0-3
    MEDIUM: tout le reste (défaut)
    """
    g = goal.lower()

    # HIGH → priorité absolue
    if (
        any(kw in g for kw in _COMPLEXITY_HIGH_KW)
        or risk_score >= 4
        or len(goal) > 200
    ):
        return "high"

    # LOW → question courte à faible risque
    if risk_score <= 3 and (
        any(kw in g for kw in _COMPLEXITY_LOW_KW)
        or len(goal) < 80
    ):
        return "low"

    return "medium"


# ── Decision Quality v2 ───────────────────────────────────────────────────────

def evaluate_approval(risk_score: int, complexity: str, mode: str) -> dict:
    """Source de vérité unique pour toutes les décisions d'approbation."""
    if mode == "MANUAL":
        return {
            "decision": "pending",
            "reason": f"Mode MANUAL — validation humaine requise (risk={risk_score})",
            "auto_approved": False,
        }

    if mode == "SUPERVISED":
        if risk_score <= 3 and complexity == "low":
            return {
                "decision": "auto_approved",
                "reason": f"Mode SUPERVISED, complexité LOW, risk={risk_score} ≤ 3 — auto-approuvé",
                "auto_approved": True,
            }
        return {
            "decision": "pending",
            "reason": f"Mode SUPERVISED, risk={risk_score}, complexity={complexity} — validation requise",
            "auto_approved": False,
        }

    # AUTO (défaut)
    if risk_score <= 5:
        return {
            "decision": "auto_approved",
            "reason": f"Mode AUTO, risk={risk_score} ≤ 5 — auto-approuvé",
            "auto_approved": True,
        }
    return {
        "decision": "pending",
        "reason": f"Mode AUTO, risk={risk_score} > 5 — garde-fou déclenché",
        "auto_approved": False,
    }


def compute_confidence_score(
    fallback_level: int,
    agent_outputs: dict,
    complexity: str,
    skipped_agents: list,
    agents_selected: list | None = None,
    goal: str = "",
) -> float:
    """Score de confiance déterministe 0.0-1.0.
    agents_selected et goal sont optionnels — utilisés par le capability registry."""
    score = 1.0

    if fallback_level > 0:
        score -= 0.2 * fallback_level

    if not agent_outputs or all(not v for v in agent_outputs.values()):
        score -= 0.3

    if complexity == "high" and "shadow-advisor" in skipped_agents:
        score -= 0.15

    if agent_outputs and "lens-reviewer" in agent_outputs:
        score += 0.1

    # ── Capability registry adjustment (fail-open) ────────────────────────────
    try:
        from memory.capability_registry import CapabilityRegistry
        from memory.decision_memory import get_decision_memory, classify_mission_type
        _dm = get_decision_memory()
        if agents_selected and len(_dm._entries) >= 5:
            _reg = CapabilityRegistry()
            _reg.build_from_memory(_dm)
            _mtype = classify_mission_type(goal, complexity)
            _agent_scores = [
                _reg.score_agent_for_context(a, _mtype, complexity)
                for a in agents_selected
            ]
            if _agent_scores:
                _avg = sum(_agent_scores) / len(_agent_scores)
                if _avg > 0.7:
                    score = min(1.0, score + 0.05)
                elif _avg < 0.4:
                    score = max(0.0, score - 0.1)
    except Exception as _exc:
        log.debug("silent_exception_caught", err=str(_exc)[:120], location="mission_system:331")

    return max(0.0, min(1.0, round(score, 2)))
