"""
agent_memory/learning.py — Lesson extraction and memory learning.

Bridges the existing core/self_improvement/lesson_memory.py with
the new StructuredMemory format, converting legacy LessonMemory
entries into typed LESSON memories with provenance.
"""
from __future__ import annotations

import structlog

from agent_memory.models import MemoryType, StructuredMemory
from agent_memory.store import AgentMemoryStore

log = structlog.get_logger("bea.agent_memory.learning")


def learn_from_failure(
    store: AgentMemoryStore,
    *,
    agent_id: str,
    mission_id: str,
    what_failed: str,
    why_it_failed: str,
    how_to_avoid: str,
    confidence: float = 0.7,
    realm: str = "code",
) -> str:
    """
    Create a LESSON memory from a failure event.
    Returns the memory_id.
    """
    content = (
        f"What failed: {what_failed}\n"
        f"Why: {why_it_failed}\n"
        f"Avoidance: {how_to_avoid}"
    )
    memory = StructuredMemory(
        memory_type=MemoryType.LESSON,
        realm=realm,
        source=f"agent:{agent_id}:failure",
        confidence=confidence,
        content=content,
        tags=["failure", "lesson"],
        agent_id=agent_id,
        mission_id=mission_id,
    )
    mid = store.add(memory)
    log.info("lesson_learned", memory_id=mid, agent_id=agent_id, realm=realm)
    return mid


def learn_from_success(
    store: AgentMemoryStore,
    *,
    agent_id: str,
    mission_id: str,
    what_worked: str,
    confidence: float = 0.8,
    realm: str = "code",
    tags: list[str] | None = None,
) -> str:
    """Create a LESSON memory from a success event."""
    memory = StructuredMemory(
        memory_type=MemoryType.LESSON,
        realm=realm,
        source=f"agent:{agent_id}:success",
        confidence=confidence,
        content=f"What worked: {what_worked}",
        tags=["success", "lesson"] + (tags or []),
        agent_id=agent_id,
        mission_id=mission_id,
    )
    mid = store.add(memory)
    log.info("lesson_success", memory_id=mid, agent_id=agent_id, realm=realm)
    return mid


def import_from_lesson_memory(
    store: AgentMemoryStore,
    *,
    agent_id: str = "system",
) -> int:
    """
    Import entries from the existing core/self_improvement/lesson_memory.py
    into the new StructuredMemory store.  Returns number of entries imported.
    """
    try:
        from core.self_improvement.lesson_memory import LessonMemory
        lm = LessonMemory()
        entries = lm.get_all() if hasattr(lm, "get_all") else []
    except Exception as exc:
        log.debug("lesson_memory_import_unavailable", reason=str(exc)[:100])
        return 0

    imported = 0
    for entry in entries:
        try:
            content = (
                f"What failed: {getattr(entry, 'what_failed', '')}\n"
                f"Root cause: {getattr(entry, 'root_cause', '')}\n"
                f"Fix: {getattr(entry, 'fix_applied', '')}"
            )
            if len(content.strip()) < 10:
                continue
            memory = StructuredMemory(
                memory_type=MemoryType.LESSON,
                realm="code",
                source=f"legacy:lesson_memory:{agent_id}",
                confidence=0.6,
                content=content[:4000],
                tags=["imported", "legacy"],
                agent_id=agent_id,
            )
            store.add(memory)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            log.debug("lesson_import_entry_error", error=str(exc)[:80])

    log.info("lesson_memory_imported", count=imported)
    return imported
