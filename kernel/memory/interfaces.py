"""
kernel/memory/interfaces.py — Typed memory subsystem interfaces.

Defines 5 memory categories with typed read/write operations.
Each delegates to existing storage implementations (fail-open).

K1 RULE: no imports from core/ at module level.
core-facing functions are registered via register_* slots (Pass 13).

Memory types:
  - working:    short-lived, current mission context
  - episodic:   event-based, what happened and when
  - semantic:   facts and knowledge (concept → data)
  - procedural: how to do things (skill patterns, successful approaches)
  - execution:  plan run history for pattern reuse

Registration slots (Pass 13):
  register_lesson_retrieve(fn)  — fn(goal, task_type, max_results) → list[dict]
"""
from __future__ import annotations

import threading
from typing import Callable, Optional
import structlog

from kernel.contracts.types import MemoryRecord
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("kernel.memory")

# ── Registration slot: lesson retrieval (Pass 13) ─────────────────────────────
# core registers a callable at boot — kernel calls it without importing core.
# Signature: fn(goal: str, task_type: str, max_results: int) -> list[dict]
_lesson_retrieve_fn: Optional[Callable] = None

# Registration slot: execution memory persist (K1 fix for _persist_record)
# Signature: fn(record_id, goal, success) -> None
_execution_persist_fn: Optional[Callable] = None

# Registration slot: execution pattern recall (K1 fix for recall_execution_patterns)
# Signature: fn() -> list[dict]
_execution_patterns_fn: Optional[Callable] = None

# ── Registration slots: MemoryFacade bridge (Pass 19 — R6) ────────────────────
# R6: all memory goes through MemoryFacade. Core registers facade.store and
# facade.search at boot so the kernel can delegate persistence without importing core.
# Signature store: fn(content: str, content_type: str, tags: list, metadata: dict) -> dict
# Signature search: fn(query: str, top_k: int) -> list[dict]
_facade_store_fn: Optional[Callable] = None
_facade_search_fn: Optional[Callable] = None


def register_lesson_retrieve(fn: Callable) -> None:
    """Register core's lesson retrieval function. Called once at boot from main.py."""
    global _lesson_retrieve_fn
    _lesson_retrieve_fn = fn
    log.debug("kernel_lesson_retrieve_registered")


def register_execution_persist(fn: Callable) -> None:
    """Register core's execution memory persist function. Called once at boot."""
    global _execution_persist_fn
    _execution_persist_fn = fn
    log.debug("kernel_execution_persist_registered")


def register_execution_patterns(fn: Callable) -> None:
    """Register core's execution pattern recall function. Called once at boot."""
    global _execution_patterns_fn
    _execution_patterns_fn = fn
    log.debug("kernel_execution_patterns_registered")


def register_facade_store(fn: Callable) -> None:
    """
    Register MemoryFacade.store as the kernel's long-term persistence backend (R6).
    Called once at boot. Signature: fn(content, content_type, tags, metadata) -> dict.
    """
    global _facade_store_fn
    _facade_store_fn = fn
    log.debug("kernel_facade_store_registered")


def register_facade_search(fn: Callable) -> None:
    """
    Register MemoryFacade.search as the kernel's long-term retrieval backend (R6).
    Called once at boot. Signature: fn(query, top_k) -> list[dict].
    """
    global _facade_search_fn
    _facade_search_fn = fn
    log.debug("kernel_facade_search_registered")


class MemoryInterface:
    """
    Unified memory interface for the kernel.

    Provides typed access to all 5 memory categories through a single API.
    Each write emits a kernel event (fail-open).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._working: dict[str, MemoryRecord] = {}  # in-memory working store
        self._max_working = 200

    # ── Working Memory (short-lived, current context) ─────────

    def write_working(self, key: str, content: dict,
                      mission_id: str = "", ttl: float = 3600) -> MemoryRecord:
        """Store short-lived context for the current mission."""
        record = MemoryRecord(
            memory_type="working",
            content=content,
            mission_id=mission_id,
            ttl=ttl,
            source="kernel",
        )
        with self._lock:
            self._working[key] = record
            if len(self._working) > self._max_working:
                self._evict_expired()
        self._emit_write(record)
        return record

    def read_working(self, key: str) -> dict | None:
        with self._lock:
            record = self._working.get(key)
            if record and not record.expired:
                return record.content
            return None

    def clear_working(self, mission_id: str = "") -> int:
        """Clear working memory, optionally for a specific mission."""
        with self._lock:
            if mission_id:
                keys = [k for k, v in self._working.items() if v.mission_id == mission_id]
            else:
                keys = list(self._working.keys())
            for k in keys:
                del self._working[k]
            return len(keys)

    # ── Episodic Memory (what happened) ───────────────────────

    def write_episodic(self, content: dict, mission_id: str = "",
                       step_id: str = "", source: str = "") -> MemoryRecord:
        """Record an episode (event + context) for future recall."""
        record = MemoryRecord(
            memory_type="episodic",
            content=content,
            mission_id=mission_id,
            step_id=step_id,
            source=source,
        )
        self._persist_record(record)
        self._emit_write(record)
        return record

    # ── Execution Memory (plan run history) ───────────────────

    def write_execution(self, content: dict, plan_id: str = "",
                        mission_id: str = "") -> MemoryRecord:
        """Record execution history for pattern reuse."""
        record = MemoryRecord(
            memory_type="execution",
            content=content,
            plan_id=plan_id,
            mission_id=mission_id,
            source="plan_runner",
        )
        self._persist_record(record)
        self._emit_write(record)
        return record

    def recall_execution_patterns(self) -> list[dict]:
        """Recall successful execution patterns via registered function (K1-compliant)."""
        try:
            if _execution_patterns_fn is not None:
                result = _execution_patterns_fn()
                return result if isinstance(result, list) else []
        except Exception as _e:
            log.debug("memory_recall_execution_patterns_failed", err=str(_e)[:80])
        return []

    # ── Procedural Memory (how to do things) ──────────────────

    def write_procedural(self, content: dict, source: str = "") -> MemoryRecord:
        """Record a learned procedure or approach."""
        record = MemoryRecord(
            memory_type="procedural",
            content=content,
            source=source,
        )
        self._persist_record(record)
        self._emit_write(record)
        return record

    # ── Semantic Memory (facts and knowledge) ─────────────────

    def write_semantic(self, content: dict, source: str = "",
                       confidence: float = 1.0) -> MemoryRecord:
        """Record a fact or piece of knowledge."""
        record = MemoryRecord(
            memory_type="semantic",
            content=content,
            source=source,
            confidence=confidence,
        )
        self._persist_record(record)
        self._emit_write(record)
        return record

    # ── Retrieval (Pass 13) ────────────────────────────────────

    def retrieve_lessons(self, goal: str, task_type: str = "",
                         max_results: int = 3) -> list[dict]:
        """
        Retrieve lessons relevant to a goal from the registered retrieval function.

        Returns a list of dicts, each with at minimum:
          - goal_summary:          str
          - what_to_do_differently: str
          - relevance:             float (optional)

        Fail-open: returns [] if function not registered or raises.
        K1 RULE: no import from core/ — delegates via registration slot.
        """
        try:
            if _lesson_retrieve_fn is not None:
                result = _lesson_retrieve_fn(goal, task_type, max_results)
                return result if isinstance(result, list) else []
        except Exception as _e:
            log.debug("memory_retrieve_lessons_failed", err=str(_e)[:80])
        return []

    # ── Unified Search (Pass 19 — R6) ─────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search long-term memory via MemoryFacade (R6).

        Delegates to _facade_search_fn if registered.
        Returns [] if facade not available (fail-open).
        K1-compliant: no import from core/.
        """
        try:
            if _facade_search_fn is not None:
                result = _facade_search_fn(query, top_k)
                return result if isinstance(result, list) else []
        except Exception as _se:
            log.debug("memory_facade_search_failed", err=str(_se)[:80])
        return []

    # ── Helpers ────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._working.items() if v.expired]
        for k in expired:
            del self._working[k]

    def _persist_record(self, record: MemoryRecord) -> None:
        """
        Persist to MemoryFacade (R6 — Pass 19) with narrow execution slot as fallback.

        Priority:
          1. _facade_store_fn (MemoryFacade.store) — all memory types (R6)
          2. _execution_persist_fn — execution type only (backward compat)
        Fail-open: silently ignores errors.
        """
        try:
            if _facade_store_fn is not None:
                # Map kernel memory_type → MemoryFacade content_type
                _ctype_map = {
                    "episodic": "mission_outcome",
                    "execution": "pattern",
                    "procedural": "solution",
                    "semantic": "knowledge",
                    "working": "general",
                }
                _content_type = _ctype_map.get(record.memory_type, "general")
                _content_str = (
                    record.content.get("summary", "")
                    or record.content.get("goal", "")
                    or str(record.content)[:500]
                )
                _facade_store_fn(
                    _content_str,
                    _content_type,
                    [record.memory_type, f"mission:{record.mission_id}"],
                    {"record_id": record.record_id, "source": record.source},
                )
                return
        except Exception as _fe:
            log.debug("memory_facade_store_failed", err=str(_fe)[:80])
        # Fallback: narrow execution slot (backward compat)
        try:
            if record.memory_type == "execution" and _execution_persist_fn is not None:
                _execution_persist_fn(
                    record_id=record.record_id,
                    goal=record.content.get("goal", ""),
                    success=record.content.get("success", False),
                )
        except Exception:
            _silent_log.debug("suppressed_exception", src='interfaces.py')

    def _emit_write(self, record: MemoryRecord) -> None:
        """
        Record memory write event.

        Note: we do NOT emit through the kernel event emitter here because
        that emitter delegates to the cognitive journal (ce_emit), which would
        create duplicate system-domain events and pollute lab/runtime boundaries.
        Memory writes are already observable through the memory stats API.
        """
        pass  # Intentionally no-op to avoid cognitive journal re-entry

    def stats(self) -> dict:
        with self._lock:
            working_count = len(self._working)
            expired_count = sum(1 for v in self._working.values() if v.expired)
        return {
            "working_memory": {"count": working_count, "expired": expired_count},
            "types": ["working", "episodic", "execution", "procedural", "semantic"],
        }


# ── Singleton ─────────────────────────────────────────────────

_interface: MemoryInterface | None = None
_lock = threading.Lock()


def get_memory() -> MemoryInterface:
    global _interface
    if _interface is None:
        with _lock:
            if _interface is None:
                _interface = MemoryInterface()
    return _interface
