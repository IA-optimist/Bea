"""
JARVIS MAX — Decision Memory
Mémoire légère FIFO (max 1000 entrées) pour apprendre des patterns décisionnels.
stdlib uniquement : json, os, time, collections, dataclasses, pathlib.
"""
from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
_silent_log = __import__("structlog").get_logger(__name__)

_WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_PERSIST_PATH  = _WORKSPACE_DIR / "decision_memory.jsonl"
_MAX_ENTRIES   = 1000
_MIN_SAMPLES   = 5   # Minimum pour que les ajustements soient fiables


# ── Classification ────────────────────────────────────────────────────────────

# Priority-ordered list of (type, keywords) — tested top to bottom.
# Priority rules: self_improvement_task first, debug_task before coding_task,
# compare_query before info_query.
_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("self_improvement_task", ["améliore-toi", "self-improve", "auto-amélioration",
                               "failure", "proposal"]),
    ("debug_task",            ["debug", "erreur", "bug", "fix", "corrige", "traceback",
                               "exception", "ne fonctionne pas", "broken"]),
    ("compare_query",         ["compare", "différence", "vs", "versus", "meilleur entre",
                               "which is better"]),
    ("coding_task",           ["code", "script", "fonction", "class", "implement", "crée un",
                               "écris", "write a", "génère"]),
    ("architecture_task",     ["architecture", "design pattern", "système", "infrastructure",
                               "microservice", "api design"]),
    ("system_task",           ["docker", "deploy", "vps", "serveur", "nginx", "git", "ssh",
                               "pipeline", "ci/cd"]),
    ("business_task",         ["stratégie", "business", "marché", "concurrence", "croissance",
                               "revenue", "pricing"]),
    ("planning_task",         ["plan", "roadmap", "étapes", "priorise", "sprint", "objectif",
                               "milestone"]),
    ("evaluation_task",       ["évalue", "teste", "valide", "vérifie", "score", "mesure",
                               "qualité", "performance"]),
    ("research_task",         ["recherche", "analyse", "trouve", "search", "find",
                               "what are the best", "quelles sont"]),
    ("info_query",            ["qu'est-ce que", "c'est quoi", "explique", "définition",
                               "how does", "what is", "tell me about"]),
]


def classify_mission_type(goal: str, complexity: str) -> str:
    """Classifie le type de mission sans stocker le goal."""
    g = goal.lower()
    for mission_type, keywords in _TYPE_RULES:
        if any(kw in g for kw in keywords):
            return mission_type
    # Fallback par complexité
    if complexity == "low":
        return "info_query"
    return "research_task"


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class DecisionOutcome:
    # Identité (compact, pas de texte long)
    ts:               int    # unix timestamp
    mission_type:     str    # "capability_query"|"simple_qa"|"analysis"|"code"|"planning"|"unknown"
    complexity:       str    # "low"|"medium"|"high"
    risk_score:       int    # 0-10

    # Décision
    confidence_score:  float      # 0.0-1.0
    selected_agents:   list       # ex: ["scout-research"]
    approval_mode:     str        # "AUTO"|"SUPERVISED"|"MANUAL"
    approval_decision: str        # "auto_approved"|"pending"

    # Résultat
    fallback_level_used: int
    latency_ms:          int
    success:             bool    # final_output non vide ET status==DONE
    user_override:       bool    # True si mode changé manuellement
    retry_count:         int     # 0 par défaut
    error_type:          str     # ""|"timeout"|"empty_output"|"agent_failure"|"exception"


# ── Classe principale ─────────────────────────────────────────────────────────

class DecisionMemory:
    MAX_ENTRIES  = _MAX_ENTRIES
    PERSIST_PATH = _PERSIST_PATH

    def __init__(self) -> None:
        self._entries: deque = deque(maxlen=self.MAX_ENTRIES)
        self._load()

    # ── API publique ──────────────────────────────────────────────────────────

    def record(self, outcome: DecisionOutcome) -> None:
        """Enregistre un outcome et persiste (atomic write)."""
        self._entries.append(asdict(outcome))
        self._persist()

    def get_pattern_stats(
        self,
        mission_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> dict:
        """Agrège les stats par pattern. O(n) sur max 1000 entrées."""
        entries = self._filter(mission_type, complexity)
        if not entries:
            return {
                "count": 0, "success_rate": 0.0, "avg_confidence": 0.0,
                "avg_latency_ms": 0, "fallback_rate": 0.0,
                "common_agents": [], "override_rate": 0.0,
            }
        n = len(entries)
        success_count  = sum(1 for e in entries if e.get("success", False))
        fallback_count = sum(1 for e in entries if e.get("fallback_level_used", 0) > 0)
        override_count = sum(1 for e in entries if e.get("user_override", False))
        avg_conf       = sum(e.get("confidence_score", 0.0) for e in entries) / n
        avg_lat        = int(sum(e.get("latency_ms", 0) for e in entries) / n)

        agent_counts: dict[str, int] = {}
        for e in entries:
            for a in e.get("selected_agents", []):
                agent_counts[a] = agent_counts.get(a, 0) + 1
        common_agents = sorted(agent_counts, key=lambda a: -agent_counts[a])[:3]

        return {
            "count":          n,
            "success_rate":   round(success_count / n, 3),
            "avg_confidence": round(avg_conf, 3),
            "avg_latency_ms": avg_lat,
            "fallback_rate":  round(fallback_count / n, 3),
            "common_agents":  common_agents,
            "override_rate":  round(override_count / n, 3),
        }

    def suggest_agents(
        self,
        mission_type: str,
        complexity: str,
        current_selection: list,
    ) -> list:
        """Suggère des ajustements basés sur les patterns historiques.
        - success_rate < 0.5 → log warning, pas de changement brusque
        - override_rate > 0.3 → suggérer +shadow-advisor si absent
        Retourne la sélection ajustée (légère modification)."""
        stats = self.get_pattern_stats(mission_type, complexity)
        if stats["count"] < _MIN_SAMPLES:
            return current_selection

        agents = list(current_selection)

        if stats["success_rate"] < 0.5:
            try:
                import structlog
                structlog.get_logger().warning(
                    "decision_memory_low_success",
                    mission_type=mission_type,
                    complexity=complexity,
                    success_rate=stats["success_rate"],
                    count=stats["count"],
                )
            except Exception:
                _silent_log.debug("suppressed_exception", src='decision_memory.py')

        if stats["override_rate"] > 0.3 and "shadow-advisor" not in agents:
            agents = agents + ["shadow-advisor"]
            try:
                import structlog
                structlog.get_logger().info(
                    "decision_memory_suggest_advisor",
                    mission_type=mission_type,
                    override_rate=stats["override_rate"],
                )
            except Exception:
                _silent_log.debug("suppressed_exception", src='decision_memory.py')

        return agents

    def compute_adjusted_confidence(
        self,
        base_confidence: float,
        mission_type: str,
        complexity: str,
    ) -> float:
        """Ajuste la confidence de base selon l'historique.
        - success_rate < 0.6 → malus -0.1
        - success_rate > 0.8 → bonus +0.05
        - Pas de modifier si < 5 entrées (trop peu de données)"""
        stats = self.get_pattern_stats(mission_type, complexity)
        if stats["count"] < _MIN_SAMPLES:
            return base_confidence

        sr = stats["success_rate"]
        if sr < 0.6:
            adjusted = base_confidence - 0.1
        elif sr > 0.8:
            adjusted = base_confidence + 0.05
        else:
            return base_confidence

        return max(0.0, min(1.0, round(adjusted, 2)))

    def detect_failure_patterns(self) -> list[dict]:
        """Détecte les patterns problématiques (≥ 3 occurrences, success_rate < 0.4)."""
        groups: dict[str, list] = {}
        for e in self._entries:
            key = f"{e.get('mission_type', '?')}:{e.get('complexity', '?')}"
            groups.setdefault(key, []).append(e)

        patterns = []
        for key, entries in groups.items():
            n = len(entries)
            if n < 3:
                continue
            sr = sum(1 for e in entries if e.get("success", False)) / n
            if sr < 0.4:
                mission_type, complexity = key.split(":", 1)
                patterns.append({
                    "pattern":      key,
                    "count":        n,
                    "success_rate": round(sr, 3),
                    "suggestion":   f"Revoir la sélection d'agents pour {mission_type}/{complexity}",
                })
        return patterns

    def ram_kb(self) -> float:
        """Estimation RAM consommée (250 bytes/entrée)."""
        return round(len(self._entries) * 250 / 1024, 1)

    # ── Interne ───────────────────────────────────────────────────────────────

    def _filter(self, mission_type: Optional[str], complexity: Optional[str]) -> list[dict]:
        result = list(self._entries)
        if mission_type:
            result = [e for e in result if e.get("mission_type") == mission_type]
        if complexity:
            result = [e for e in result if e.get("complexity") == complexity]
        return result

    def _load(self) -> None:
        """Charge depuis JSONL. Silencieux si fichier absent ou corrompu."""
        try:
            if not self.PERSIST_PATH.exists():
                return
            lines = self.PERSIST_PATH.read_text("utf-8").strip().splitlines()
            for line in lines:
                try:
                    self._entries.append(json.loads(line))
                except Exception:
                    _silent_log.debug("suppressed_exception", src='decision_memory.py')
        except Exception:
            _silent_log.debug("suppressed_exception", src='decision_memory.py')

    def _persist(self) -> None:
        """Écrit JSONL. FIFO géré par deque(maxlen=1000). Atomic write (tmp → rename)."""
        try:
            self.PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps(e, ensure_ascii=False) for e in self._entries]
            tmp = self.PERSIST_PATH.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", "utf-8")
            tmp.replace(self.PERSIST_PATH)
        except Exception:
            _silent_log.debug("suppressed_exception", src='decision_memory.py')


# ── Singleton module-level ────────────────────────────────────────────────────

_instance: Optional[DecisionMemory] = None


def get_decision_memory() -> DecisionMemory:
    global _instance
    if _instance is None:
        _instance = DecisionMemory()
    return _instance
