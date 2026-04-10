"""
JARVIS MAX — Knowledge Memory v1
Mémoire de connaissances validées.

Stocke UNIQUEMENT :
  - patterns techniques validés
  - anti-patterns confirmés
  - pratiques business utiles
  - erreurs récurrentes
  - solutions validées
  - critères de décision utiles

Format de stockage :
{
  "id": "uuid",
  "type": "best_practice | anti_pattern | fix | heuristic | business_pattern",
  "topic": "python async",
  "problem": "Que résout cette connaissance ?",
  "solution": "La connaissance elle-même",
  "why_it_works": "Pourquoi ça marche",
  "proof": "Source ou expérience",
  "reusable": true,
  "agent_targets": ["scout-research", "forge-builder"],
  "utility_score": 0.85,
  "reuse_score": 0.90,
  "use_count": 0,
  "created_at": 1710000000.0,
  "last_used": null,
  "ttl_days": null,
}

Persistance : JSON dans workspace/knowledge_memory.json
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import structlog

log = structlog.get_logger()

_STORAGE_PATH = Path("workspace/knowledge_memory.json")
_MAX_ENTRIES  = 1000
_MIN_UTILITY  = 0.35   # seuil minimal pour accepter une entrée

# Types de connaissances valides
KNOWLEDGE_TYPES = frozenset({
    "best_practice", "anti_pattern", "fix", "heuristic",
    "business_pattern", "architecture_pattern", "prompt_pattern",
})

# Agents pouvant bénéficier des connaissances
VALID_AGENT_TARGETS = frozenset({
    "scout-research", "map-planner", "forge-builder",
    "lens-reviewer", "shadow-advisor", "vault-memory",
    "pulse-ops", "night-worker",
})


# ── Entrée de connaissance ────────────────────────────────────────────────────

@dataclass
class KnowledgeEntry:
    type: str
    topic: str
    solution: str
    problem: str = ""
    why_it_works: str = ""
    proof: str = ""
    reusable: bool = True
    agent_targets: list[str] = field(default_factory=list)
    utility_score: float = 0.70
    reuse_score: float = 0.70
    use_count: int = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    last_used: float | None = None
    ttl_days: int | None = None   # None = pas d'expiration

    def __post_init__(self):
        # Normalisation
        self.type = self.type if self.type in KNOWLEDGE_TYPES else "best_practice"
        self.agent_targets = [
            a for a in self.agent_targets if a in VALID_AGENT_TARGETS
        ]
        self.utility_score  = max(0.0, min(1.0, self.utility_score))
        self.reuse_score    = max(0.0, min(1.0, self.reuse_score))

    @property
    def fingerprint(self) -> str:
        """Hash court pour déduplication."""
        text = f"{self.type}:{self.topic}:{self.solution[:100]}"
        return hashlib.md5(text.encode()).hexdigest()[:12]

    def is_expired(self) -> bool:
        if self.ttl_days is None:
            return False
        age_days = (time.time() - self.created_at) / 86400
        return age_days > self.ttl_days

    def relevance_score(self, query: str) -> float:
        """Score de pertinence simple pour une requête."""
        query_lower = query.lower()
        text = f"{self.topic} {self.solution} {self.problem}".lower()
        words = set(query_lower.split())
        hits  = sum(1 for w in words if len(w) > 3 and w in text)
        base  = hits / max(len(words), 1)
        return base * self.utility_score * (1 + self.use_count * 0.05)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt_snippet(self) -> str:
        """Format compact injectable dans un prompt."""
        lines = [f"[{self.type.upper()}] {self.solution}"]
        if self.problem:
            lines.append(f"Problème : {self.problem}")
        if self.why_it_works:
            lines.append(f"Pourquoi : {self.why_it_works}")
        return "\n".join(lines)


# ── Mémoire de connaissances ──────────────────────────────────────────────────

class KnowledgeMemory:
    """
    Mémoire de connaissances validées persistée en JSON.

    Usage :
        km = KnowledgeMemory()
        entry = km.store(
            type="best_practice",
            topic="python async",
            solution="Toujours utiliser asyncio.wait_for() avec timeout",
            utility_score=0.85,
            agent_targets=["forge-builder"],
        )
        results = km.get_for_agent("forge-builder", query="async timeout")
        km.avoid_duplicate("asyncio.wait_for")  # → True si déjà connu
    """

    def __init__(self, storage_path: Path | str = _STORAGE_PATH):
        self._path = Path(storage_path)
        self._entries: dict[str, KnowledgeEntry] = {}
        self._fingerprints: set[str] = set()
        self._load()

    # ── API publique ──────────────────────────────────────────────────────────

    def store(
        self,
        type: str,
        topic: str,
        solution: str,
        problem: str = "",
        why_it_works: str = "",
        proof: str = "",
        reusable: bool = True,
        agent_targets: list[str] | None = None,
        utility_score: float = 0.70,
        reuse_score: float = 0.70,
        ttl_days: int | None = None,
    ) -> KnowledgeEntry | None:
        """
        Stocke une nouvelle connaissance validée.
        Retourne None si dupliquée ou score insuffisant.
        """
        if utility_score < _MIN_UTILITY:
            log.debug("knowledge_rejected_low_utility", score=utility_score, topic=topic)
            return None

        entry = KnowledgeEntry(
            type=type,
            topic=topic,
            solution=solution,
            problem=problem,
            why_it_works=why_it_works,
            proof=proof,
            reusable=reusable,
            agent_targets=agent_targets or [],
            utility_score=utility_score,
            reuse_score=reuse_score,
            ttl_days=ttl_days,
        )

        # Déduplication
        if entry.fingerprint in self._fingerprints:
            log.debug("knowledge_duplicate_skipped", topic=topic, fp=entry.fingerprint)
            return None

        self._entries[entry.id] = entry
        self._fingerprints.add(entry.fingerprint)

        # Rotation FIFO si dépassement
        if len(self._entries) > _MAX_ENTRIES:
            oldest = sorted(self._entries.values(), key=lambda e: e.created_at)
            for old in oldest[:10]:
                del self._entries[old.id]
                self._fingerprints.discard(old.fingerprint)

        self._save()
        log.info("knowledge_stored", id=entry.id, type=type, topic=topic[:40])
        return entry

    def store_from_dict(self, data: dict) -> KnowledgeEntry | None:
        """Stocke depuis un dict (ex: output LLM ou LearningReport)."""
        return self.store(
            type=data.get("type", "best_practice"),
            topic=data.get("topic", ""),
            solution=data.get("solution", data.get("content", "")),
            problem=data.get("problem", ""),
            why_it_works=data.get("why_it_works", ""),
            proof=data.get("proof", ""),
            reusable=data.get("reusable", True),
            agent_targets=data.get("agent_targets", []),
            utility_score=data.get("utility_score", 0.70),
            reuse_score=data.get("reuse_score", 0.70),
        )

    def get_for_agent(
        self,
        agent_name: str,
        query: str = "",
        max_results: int = 5,
        min_utility: float = 0.50,
    ) -> list[KnowledgeEntry]:
        """
        Retourne les connaissances les plus pertinentes pour un agent donné.
        Triées par pertinence (query) × utilité × fréquence d'usage.
        """
        candidates = [
            e for e in self._entries.values()
            if not e.is_expired()
            and e.utility_score >= min_utility
            and (not e.agent_targets or agent_name in e.agent_targets)
        ]

        if query:
            candidates.sort(key=lambda e: e.relevance_score(query), reverse=True)
        else:
            candidates.sort(key=lambda e: e.utility_score, reverse=True)

        return candidates[:max_results]

    def get_by_topic(self, topic: str, max_results: int = 10) -> list[KnowledgeEntry]:
        """Récupère les connaissances par sujet."""
        topic_lower = topic.lower()
        results = [
            e for e in self._entries.values()
            if topic_lower in e.topic.lower() and not e.is_expired()
        ]
        return sorted(results, key=lambda e: e.utility_score, reverse=True)[:max_results]

    def get_by_type(self, knowledge_type: str, max_results: int = 10) -> list[KnowledgeEntry]:
        """Récupère les connaissances par type."""
        return [
            e for e in sorted(
                self._entries.values(),
                key=lambda e: e.utility_score, reverse=True
            )
            if e.type == knowledge_type and not e.is_expired()
        ][:max_results]

    def avoid_duplicate_ideas(self, idea: str) -> bool:
        """
        Vérifie si une idée est déjà connue (Jaccard similarity).
        Retourne True si déjà connue → éviter de la refaire.
        """
        idea_words = set(idea.lower().split())
        if len(idea_words) < 3:
            return False

        for entry in self._entries.values():
            entry_words = set(f"{entry.topic} {entry.solution}".lower().split())
            intersection = idea_words & entry_words
            union = idea_words | entry_words
            if union and len(intersection) / len(union) > 0.65:
                return True

        return False

    def mark_used(self, entry_id: str) -> None:
        """Incrémente le compteur d'usage d'une entrée."""
        if entry_id in self._entries:
            self._entries[entry_id].use_count += 1
            self._entries[entry_id].last_used = time.time()
            self._save()

    def get_context_for_prompt(
        self,
        agent_name: str,
        query: str,
        max_items: int = 3,
    ) -> str:
        """
        Retourne un bloc texte injectable directement dans un prompt agent.
        Format : "## Connaissances validées\n[BP] ...\n[AP] ..."
        """
        entries = self.get_for_agent(agent_name, query=query, max_results=max_items)
        if not entries:
            return ""

        lines = ["## Connaissances validées (mémoire Jarvis)"]
        for e in entries:
            lines.append(e.to_prompt_snippet())
            self.mark_used(e.id)

        return "\n".join(lines)

    def stats(self) -> dict:
        active = [e for e in self._entries.values() if not e.is_expired()]
        by_type: dict[str, int] = {}
        for e in active:
            by_type[e.type] = by_type.get(e.type, 0) + 1

        return {
            "total": len(active),
            "by_type": by_type,
            "avg_utility": round(
                sum(e.utility_score for e in active) / max(len(active), 1), 3
            ),
            "total_uses": sum(e.use_count for e in active),
        }

    def prune_expired(self) -> int:
        """Supprime les entrées expirées. Retourne le nombre supprimé."""
        expired = [k for k, e in self._entries.items() if e.is_expired()]
        for k in expired:
            fp = self._entries[k].fingerprint
            del self._entries[k]
            self._fingerprints.discard(fp)
        if expired:
            self._save()
            log.info("knowledge_pruned", count=len(expired))
        return len(expired)

    # ── Persistance ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text("utf-8"))
            for item in data.get("entries", []):
                try:
                    entry = KnowledgeEntry(**item)
                    self._entries[entry.id] = entry
                    self._fingerprints.add(entry.fingerprint)
                except Exception:
                    pass
            log.debug("knowledge_memory_loaded", count=len(self._entries))
        except Exception as e:
            log.warning("knowledge_memory_load_failed", err=str(e))

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "saved_at": time.time(),
                "entries": [e.to_dict() for e in self._entries.values()],
            }
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        except Exception as e:
            log.warning("knowledge_memory_save_failed", err=str(e))


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: KnowledgeMemory | None = None


def get_knowledge_memory() -> KnowledgeMemory:
    global _instance
    if _instance is None:
        _instance = KnowledgeMemory()
    return _instance
