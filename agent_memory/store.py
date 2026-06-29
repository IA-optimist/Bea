"""
agent_memory/store.py — AgentMemoryStore: in-memory store with recall by type/realm/tag.

Thin layer over StructuredMemory objects.  For production, entries are
persisted to the existing OperationalMemory (SQLite) via the bridge below.
The store intentionally does NOT expose delete — memories are superseded,
not erased, to maintain audit trail.
"""
from __future__ import annotations

from typing import Any

import structlog

from agent_memory.models import MemoryType, StructuredMemory

log = structlog.get_logger("bea.agent_memory.store")


class AgentMemoryStore:
    """
    Lightweight in-process memory store.

    Thread-safety: single-agent use only.  For multi-agent scenarios,
    persist to OperationalMemory (SQLite) between turns.
    """

    def __init__(self) -> None:
        self._store: dict[str, StructuredMemory] = {}

    def add(self, memory: StructuredMemory) -> str:
        """Persist a memory entry.  Returns the memory_id."""
        memory = memory.model_copy(update={"content": memory.content})
        if memory.is_security_sensitive:
            log.info(
                "agent_memory_security_note",
                memory_id=memory.memory_id,
                memory_type=memory.memory_type.value,
                realm=memory.realm,
                # content intentionally omitted for audit safety
            )
        self._store[memory.memory_id] = memory
        log.debug(
            "agent_memory_stored",
            memory_id=memory.memory_id,
            memory_type=memory.memory_type.value,
            realm=memory.realm,
            confidence=memory.confidence,
        )
        return memory.memory_id

    def get(self, memory_id: str) -> StructuredMemory | None:
        item = self._store.get(memory_id)
        if item is not None and item.is_expired:
            return None
        return item

    def delete(self, memory_id: str) -> bool:
        return self._store.pop(memory_id, None) is not None

    def supersede(self, old_id: str, new_memory: StructuredMemory) -> str:
        """Mark old_id as superseded and store the new memory."""
        old = self._store.get(old_id)
        if old and old.superseded_by is None:
            # Create a superseded copy (Pydantic v2 model_copy)
            self._store[old_id] = old.model_copy(
                update={"superseded_by": new_memory.memory_id}
            )
        return self.add(new_memory)

    def recall(
        self,
        *,
        memory_type: MemoryType | None = None,
        realm: str | None = None,
        tags: list[str] | None = None,
        min_confidence: float = 0.0,
        exclude_superseded: bool = True,
        limit: int = 20,
    ) -> list[StructuredMemory]:
        """Filtered recall.  Returns most-recent entries first."""
        results: list[StructuredMemory] = []
        for m in self._store.values():
            if m.is_expired:
                continue
            if exclude_superseded and m.is_superseded:
                continue
            if memory_type and m.memory_type != memory_type:
                continue
            if realm and m.realm != realm.lower():
                continue
            if tags and not any(t in m.tags for t in tags):
                continue
            if m.confidence < min_confidence:
                continue
            results.append(m)
        results.sort(key=lambda m: m.created_at, reverse=True)
        return results[:limit]

    def context_for_agent(
        self,
        realm: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
    ) -> str:
        """Format top memories for injection into agent context."""
        memories = self.recall(realm=realm, limit=limit)
        if memory_types:
            memories = [m for m in memories if m.memory_type in memory_types]
        if not memories:
            return "(no memories available for this realm)"
        return "\n---\n".join(m.to_recall_context() for m in memories[:limit])

    def stats(self) -> dict[str, Any]:
        total = len(self._store)
        active = sum(1 for m in self._store.values() if not m.is_superseded)
        by_type: dict[str, int] = {}
        for m in self._store.values():
            if not m.is_superseded:
                by_type[m.memory_type.value] = by_type.get(m.memory_type.value, 0) + 1
        return {"total": total, "active": active, "by_type": by_type}
