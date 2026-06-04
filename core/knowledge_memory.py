"""
KnowledgeMemory — mémoire légère des solutions qui ont fonctionné.
Différent du capability_registry (qui apprend quels agents sont efficaces) :
ici on apprend QUELLES SOLUTIONS fonctionnent pour quels problèmes.

Max 200 entrées, dict en mémoire, ~15 KB RAM max.
Matching keyword-based + mission_type — pas d'embeddings.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import time
import json
import logging
import os

logger = logging.getLogger(__name__)

_PERSIST_PATH = "workspace/knowledge_memory.jsonl"
_MAX_ENTRIES = 200
_MIN_CONFIDENCE_TO_STORE = 0.8
_MAX_FALLBACK_TO_STORE = 1


@dataclass
class KnowledgeEntry:
    problem_signature: str   # hash court des mots-clés du problème (ex: "python debug import error")
    mission_type: str        # ex. "debug_task"
    solution_summary: str    # résumé textuel de la solution (final_output tronqué à 500 chars)
    tools_used: List[str]    # tools utilisés (depuis decision_trace)
    agents_used: List[str]   # agents sélectionnés
    success_score: float     # confidence_score au moment du stockage
    usage_count: int = 1     # combien de fois cette entrée a été utile
    last_used: int = field(default_factory=lambda: int(time.time()))
    confidence: float = 0.5  # score de confiance en cette solution (monte avec usage)


def _make_signature(goal: str, mission_type: str) -> str:
    """
    Crée une signature légère du problème à partir des mots-clés du goal.
    Normalise en minuscules, garde les 5 mots les plus longs (> 3 chars),
    ajoute le mission_type comme préfixe.
    """
    words = goal.lower().split()
    keywords = sorted(
        [w for w in words if len(w) > 3 and w.isalpha()],
        key=len, reverse=True
    )[:5]
    return f"{mission_type}:{' '.join(sorted(keywords))}"


def _keyword_overlap(sig1: str, sig2: str) -> float:
    """
    Calcule le chevauchement de keywords entre deux signatures.
    Retourne score 0.0–1.0.
    """
    # Ignore le préfixe mission_type (avant ":")
    k1 = set(sig1.split(":", 1)[-1].split())
    k2 = set(sig2.split(":", 1)[-1].split())
    if not k1 or not k2:
        return 0.0
    intersection = k1 & k2
    union = k1 | k2
    return len(intersection) / len(union)  # Jaccard


class KnowledgeMemory:
    """
    Stocke et retrouve les solutions ayant bien fonctionné.
    Structure : dict[signature -> KnowledgeEntry] avec LRU-like éviction.
    """

    def __init__(self):
        # Dictionnaire principal signature → entry
        self._entries: Dict[str, KnowledgeEntry] = {}
        self._load_from_disk()

    def store_if_useful(
        self,
        goal: str,
        mission_type: str,
        solution_summary: str,
        tools_used: List[str],
        agents_used: List[str],
        confidence_score: float,
        fallback_level: int,
        execution_policy_decision: str,
    ) -> bool:
        """
        Stocke une solution si elle répond aux critères de qualité.
        Retourne True si stockée, False sinon.
        """
        try:
            # Conditions de stockage
            if confidence_score < _MIN_CONFIDENCE_TO_STORE:
                return False
            if fallback_level > _MAX_FALLBACK_TO_STORE:
                return False
            if execution_policy_decision == "BLOCKED":
                return False
            if not solution_summary or len(solution_summary.strip()) < 20:
                return False

            sig = _make_signature(goal, mission_type)
            summary = solution_summary[:500]  # tronque à 500 chars

            if sig in self._entries:
                # Mise à jour entrée existante
                e = self._entries[sig]
                e.usage_count += 1
                e.last_used = int(time.time())
                # Moyenne mobile du success_score
                e.success_score = round((e.success_score * (e.usage_count - 1) + confidence_score) / e.usage_count, 4)
                # Confiance monte avec l'usage (plafond 0.95)
                e.confidence = min(0.95, round(e.confidence + 0.05, 3))
                e.tools_used = list(set(e.tools_used) | set(tools_used))
            else:
                # Éviction si plein (supprime l'entrée la moins utilisée)
                if len(self._entries) >= _MAX_ENTRIES:
                    oldest_sig = min(self._entries, key=lambda s: (self._entries[s].usage_count, self._entries[s].last_used))
                    del self._entries[oldest_sig]

                self._entries[sig] = KnowledgeEntry(
                    problem_signature=sig,
                    mission_type=mission_type,
                    solution_summary=summary,
                    tools_used=list(tools_used),
                    agents_used=list(agents_used),
                    success_score=confidence_score,
                    confidence=0.5,
                )

            self._persist()
            return True

        except Exception as e:
            logger.warning(f"[KnowledgeMemory] store_if_useful error: {e}")
            return False

    def find_similar(
        self,
        goal: str,
        mission_type: str,
        threshold: float = 0.4,
    ) -> Optional[Tuple[KnowledgeEntry, float]]:
        """
        Cherche une entrée similaire par mission_type + overlap de keywords.
        Retourne (entry, score) ou None si rien de suffisamment similaire.
        threshold : score Jaccard minimum pour un match.
        """
        try:
            sig = _make_signature(goal, mission_type)
            best_entry: Optional[KnowledgeEntry] = None
            best_score = 0.0

            for stored_sig, entry in self._entries.items():
                # Filtre rapide : même mission_type obligatoire
                if entry.mission_type != mission_type:
                    continue
                overlap = _keyword_overlap(sig, stored_sig)
                # Pondère par confiance de l'entrée
                weighted = overlap * entry.confidence
                if weighted > best_score:
                    best_score = weighted
                    best_entry = entry

            if best_entry is not None and best_score >= threshold:
                return best_entry, round(best_score, 3)
            return None

        except Exception as e:
            logger.warning(f"[KnowledgeMemory] find_similar error: {e}")
            return None

    def get_recent_solutions(self, n: int = 20) -> List[dict]:
        """Retourne les n entrées les plus récentes pour l'endpoint API."""
        try:
            sorted_entries = sorted(
                self._entries.values(),
                key=lambda e: (e.usage_count, e.last_used),
                reverse=True
            )[:n]
            return [
                {
                    "problem_signature": e.problem_signature,
                    "mission_type": e.mission_type,
                    "solution_summary": e.solution_summary[:200],
                    "tools_used": e.tools_used,
                    "agents_used": e.agents_used,
                    "success_score": e.success_score,
                    "usage_count": e.usage_count,
                    "confidence": e.confidence,
                    "last_used": e.last_used,
                }
                for e in sorted_entries
            ]
        except Exception as e:
            logger.warning(f"[KnowledgeMemory] get_recent_solutions error: {e}")
            return []

    def get_stats(self) -> dict:
        """Stats globales pour l'API."""
        try:
            total = len(self._entries)
            if total == 0:
                return {"total": 0}
            avg_usage = sum(e.usage_count for e in self._entries.values()) / total
            avg_confidence = sum(e.confidence for e in self._entries.values()) / total
            by_type: Dict[str, int] = {}
            for e in self._entries.values():
                by_type[e.mission_type] = by_type.get(e.mission_type, 0) + 1
            return {
                "total": total,
                "avg_usage_count": round(avg_usage, 2),
                "avg_confidence": round(avg_confidence, 3),
                "by_mission_type": by_type,
                "ram_kb": round(total * 75 / 1024, 2),  # estimation
            }
        except Exception as e:
            return {"total": 0, "error": str(e)}

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Sauvegarde atomique en JSONL. Fail-silent."""
        try:
            os.makedirs(os.path.dirname(_PERSIST_PATH), exist_ok=True)
            lines = []
            for e in self._entries.values():
                lines.append(json.dumps({
                    "problem_signature": e.problem_signature,
                    "mission_type": e.mission_type,
                    "solution_summary": e.solution_summary,
                    "tools_used": e.tools_used,
                    "agents_used": e.agents_used,
                    "success_score": e.success_score,
                    "usage_count": e.usage_count,
                    "last_used": e.last_used,
                    "confidence": e.confidence,
                }, ensure_ascii=False))
            # Écriture atomique
            tmp = _PERSIST_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            os.replace(tmp, _PERSIST_PATH)
        except Exception as e:
            logger.warning(f"[KnowledgeMemory] _persist error: {e}")

    def _load_from_disk(self) -> None:
        """Charge depuis le fichier JSONL au démarrage. Fail-silent."""
        try:
            if not os.path.exists(_PERSIST_PATH):
                return
            with open(_PERSIST_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        e = KnowledgeEntry(**d)
                        self._entries[e.problem_signature] = e
                    except Exception:
                        logger.debug("swallowed_exception", exc_info=True)
                        continue
            logger.info(f"[KnowledgeMemory] loaded {len(self._entries)} entries from disk")
        except Exception as e:
            logger.warning(f"[KnowledgeMemory] _load_from_disk error: {e}")


# Singleton
_km: Optional[KnowledgeMemory] = None

def get_knowledge_memory() -> KnowledgeMemory:
    global _km
    if _km is None:
        _km = KnowledgeMemory()
    return _km
