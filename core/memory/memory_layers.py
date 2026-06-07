"""
core/memory/memory_layers.py — AI OS Memory Layer Structure.

Defines 6 structured memory types with metadata, relevance scoring,
bounded retention, and safe pruning. Sits on top of MemoryStore.

Does NOT replace memory_schema.py — extends it.
"""
from __future__ import annotations
import time
import structlog
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

log = structlog.get_logger("bea.memory_layers")


# ── Memory Types ─────────────────────────────────────────────────────────────

MemoryType = Literal[
    "short_term_context",    # Current session/mission context — TTL ~1h
    "mission_memory",        # Per-mission results and decisions — TTL ~7d
    "long_term_knowledge",   # Validated facts and patterns — TTL ~90d
    "user_preferences",      # User-specific settings and preferences — no TTL
    "project_memory",        # Project-level context and decisions — TTL ~30d
    "validated_learnings",   # Confirmed learnings from self-improvement — no TTL
]

MEMORY_TYPE_CONFIG: dict[str, dict] = {
    "short_term_context":  {"tier": "SHORT_TERM", "ttl_hours": 1,     "max_entries": 50},
    "mission_memory":      {"tier": "EPISODIC",   "ttl_hours": 168,   "max_entries": 500},
    "long_term_knowledge": {"tier": "LONG_TERM",  "ttl_hours": 2160,  "max_entries": 1000},
    "user_preferences":    {"tier": "LONG_TERM",  "ttl_hours": None,  "max_entries": 100},
    "project_memory":      {"tier": "EPISODIC",   "ttl_hours": 720,   "max_entries": 300},
    "validated_learnings": {"tier": "LONG_TERM",  "ttl_hours": None,  "max_entries": 200},
}


@dataclass
class MemoryMetadata:
    """Structured metadata for every memory entry."""
    source: str = "system"              # agent name, user, system, self_improvement
    confidence: float = 0.5             # 0.0 to 1.0
    scope: str = "global"               # global, mission:{id}, project:{name}
    relevance_score: float = 0.5        # 0.0 to 1.0 — decays over time
    validation_status: str = "unvalidated"  # unvalidated, validated, disputed, deprecated
    tags: list[str] = field(default_factory=list)
    related_missions: list[str] = field(default_factory=list)
    access_count: int = 0
    last_accessed: float = 0.0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> "MemoryMetadata":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Memory Layer API ─────────────────────────────────────────────────────────

class MemoryLayer:
    """
    AI OS memory layer wrapping MemoryStore with structured types and relevance.

    STATUS — NOT WIRED INTO AGENT RUNTIME (2026-04-03).

    This abstraction is fully implemented but agents currently write to Qdrant
    (vector memory) directly rather than routing through MemoryLayer.
    Two memory paths coexist: Qdrant direct (active) vs MemoryLayer (inactive).

    Activation requires: plugging MemoryLayer into ParallelExecutor/AgentCrew
    as the canonical write path, then migrating Qdrant writes to use it.
    Until that is done, this class is available but not exercised at runtime.
    """
    
    def __init__(self, store=None):
        """Initialize with existing MemoryStore or create one."""
        if store is None:
            from core.memory.memory_schema import MemoryStore
            store = MemoryStore()
        self._store = store
    
    def store(self, content: str, memory_type: MemoryType, *,
              metadata: MemoryMetadata | None = None,
              mission_id: str = "", importance: float = 0.5) -> str:
        """Store a memory entry with full AI OS metadata."""
        from core.memory.memory_schema import MemoryEntry
        
        config = MEMORY_TYPE_CONFIG.get(memory_type, MEMORY_TYPE_CONFIG["mission_memory"])
        meta = metadata or MemoryMetadata()
        
        ttl = config["ttl_hours"] * 3600 if config["ttl_hours"] else None
        
        entry = MemoryEntry(
            content=content,
            tier=config["tier"],
            memory_type=memory_type,
            mission_id=mission_id,
            importance=importance,
            ttl_seconds=ttl,
            metadata=meta.to_dict(),
        )
        
        self._store.store(entry)
        log.debug("memory_stored", type=memory_type, tier=config["tier"],
                  importance=importance, scope=meta.scope)
        return entry.entry_id
    
    def search(self, memory_type: str = "", scope: str = "",
               min_confidence: float = 0.0, limit: int = 10) -> list[dict]:
        """Search memories with relevance scoring and filtering."""
        results = self._store.search(memory_type=memory_type, limit=limit * 2)
        
        # Filter by scope and confidence
        filtered = []
        for entry in results:
            meta = entry.metadata or {}
            conf = meta.get("confidence", 0.5)
            entry_scope = meta.get("scope", "global")
            
            if conf < min_confidence:
                continue
            if scope and entry_scope != "global" and entry_scope != scope:
                continue
            
            # Compute relevance with time decay
            age_hours = (time.time() - entry.timestamp) / 3600
            time_decay = max(0.1, 1.0 - (age_hours / 720))  # Decay over 30 days
            access_boost = min(0.2, entry.access_count * 0.02) if entry.access_count else 0
            relevance = (entry.importance * 0.4 + conf * 0.3 + time_decay * 0.2 + access_boost * 0.1)
            
            filtered.append({
                "entry_id": entry.entry_id,
                "content": entry.content,
                "memory_type": entry.memory_type,
                "importance": entry.importance,
                "relevance": round(relevance, 3),
                "confidence": conf,
                "scope": entry_scope,
                "age_hours": round(age_hours, 1),
                "metadata": meta,
            })
        
        # Sort by relevance
        filtered.sort(key=lambda x: -x["relevance"])
        return filtered[:limit]
    
    def prune(self, memory_type: str = "", max_age_hours: float = 0) -> int:
        """Safely prune old/low-relevance entries. Returns count pruned."""
        config = MEMORY_TYPE_CONFIG.get(memory_type)
        if not config and not max_age_hours:
            return 0
        
        all_entries = self._store.search(memory_type=memory_type, limit=10000)
        pruned = 0
        now = time.time()
        
        for entry in all_entries:
            age_hours = (now - entry.timestamp) / 3600
            ttl_hours = (config or {}).get("ttl_hours")
            
            should_prune = False
            if max_age_hours and age_hours > max_age_hours:
                should_prune = True
            elif ttl_hours and age_hours > ttl_hours:
                should_prune = True
            elif entry.importance < 0.1 and age_hours > 24:
                should_prune = True
            
            # Never prune validated learnings or user preferences
            meta = entry.metadata or {}
            if meta.get("validation_status") == "validated":
                should_prune = False
            
            if should_prune:
                # SQLite doesn't have delete by ID in our store — mark as pruned
                entry.importance = 0.0
                entry.metadata = {**(entry.metadata or {}), "pruned": True}
                pruned += 1
        
        if pruned:
            log.info("memory_pruned", type=memory_type, count=pruned)
        return pruned
    
    def summarize(self, memory_type: str = "", limit: int = 5) -> dict:
        """Summarize memory state for a given type."""
        entries = self._store.search(memory_type=memory_type, limit=1000)
        if not entries:
            return {"type": memory_type, "count": 0, "summary": "No entries"}
        
        ages = [(time.time() - e.timestamp) / 3600 for e in entries]
        importances = [e.importance for e in entries]
        
        return {
            "type": memory_type,
            "count": len(entries),
            "oldest_hours": round(max(ages), 1) if ages else 0,
            "newest_hours": round(min(ages), 1) if ages else 0,
            "avg_importance": round(sum(importances) / len(importances), 3) if importances else 0,
            "top_entries": [
                {"content": e.content[:100], "importance": e.importance}
                for e in sorted(entries, key=lambda x: -x.importance)[:limit]
            ],
        }
    
    def stats(self) -> dict:
        """Overall memory layer statistics."""
        store_stats = self._store.stats()
        type_stats = {}
        for mt in MEMORY_TYPE_CONFIG:
            entries = self._store.search(memory_type=mt, limit=10000)
            type_stats[mt] = len(entries)
        return {
            "store": store_stats,
            "by_type": type_stats,
            "types_defined": len(MEMORY_TYPE_CONFIG),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_layer: Optional[MemoryLayer] = None

def get_memory_layer() -> MemoryLayer:
    global _layer
    if _layer is None:
        _layer = MemoryLayer()
    return _layer
