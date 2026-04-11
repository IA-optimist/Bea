"""
JARVIS MAX — Memory Facade
============================
Single memory interface for the orchestrator and all agents.

Wraps all existing memory implementations without replacing them.
Routes reads/writes to the appropriate backend based on content type.

Existing systems preserved:
    - memory/memory_bus.py (MemoryBus) — multi-backend router
    - core/tools/memory_toolkit.py — agent-facing tools
    - core/improvement_memory.py — improvement tracking
    - core/knowledge_memory.py — knowledge base
    - memory/decision_memory.py — decision patterns
    - memory/vault_memory.py — vault storage
    - core/memory.py (MemoryBank) — simple JSON store

This facade does NOT replace any of those. It provides a unified
query surface and routes to the most appropriate backend.

Usage:
    from core.memory_facade import get_memory_facade

    facade = get_memory_facade()

    # Store
    facade.store("Fixed auth bug by adding token refresh",
                 content_type="solution", tags=["auth", "bugfix"])

    # Search (queries all backends, merges results)
    results = facade.search("authentication issues", top_k=5)

    # Get recent entries of a specific type
    recent = facade.get_recent(content_type="decision", n=10)

    # Backend health
    health = facade.health()
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import queue as _queue_module
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CONTENT TYPES
# ═══════════════════════════════════════════════════════════════

CONTENT_TYPES = frozenset({
    "solution",         # Problem → solution pairs
    "error",            # Error context and fixes
    "patch",            # Code changes
    "decision",         # Architecture/design decisions
    "pattern",          # Recurring patterns
    "objective",        # Goals and objectives
    "mission_outcome",  # Mission results
    "knowledge",        # General knowledge
    "failure",          # Failed mission outcomes (for learning)
    "general",          # Catch-all
})


@dataclass
class MemoryEntry:
    """Normalized memory entry across all backends."""
    content:      str
    content_type: str = "general"
    tags:         list[str] = field(default_factory=list)
    source:       str = ""           # Which backend stored it
    score:        float = 0.0        # Relevance score (0-1)
    timestamp:    float = field(default_factory=time.time)
    metadata:     dict = field(default_factory=dict)
    entry_id:     str = ""

    def to_dict(self) -> dict:
        return {
            "content": self.content[:2000],
            "content_type": self.content_type,
            "tags": self.tags,
            "source": self.source,
            "score": round(self.score, 3),
            "timestamp": self.timestamp,
            "entry_id": self.entry_id,
        }


# ═══════════════════════════════════════════════════════════════
# BACKEND REGISTRY
# ═══════════════════════════════════════════════════════════════

class _BackendStatus:
    """Track backend availability."""
    def __init__(self, name: str):
        self.name = name
        self.available = False
        self.last_check = 0.0
        self.error = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "last_check": self.last_check,
            "error": self.error,
        }


# Content type → preferred backend routing
_ROUTING: dict[str, list[str]] = {
    "solution":        ["memory_toolkit", "memory_bus"],
    "error":           ["memory_toolkit", "memory_bus"],
    "patch":           ["memory_bus_patches", "memory_toolkit"],
    "decision":        ["decision_memory", "knowledge_jsonl"],
    "pattern":         ["knowledge_memory", "knowledge_jsonl"],
    "objective":       ["objective_store"],
    "mission_outcome": ["knowledge_jsonl"],
    "knowledge":       ["knowledge_memory", "memory_bus"],
    "failure":         ["knowledge_jsonl", "memory_bus"],
    "general":         ["memory_bus", "memory_toolkit"],
}


class MemoryFacade:
    """
    Unified memory interface for JarvisMax.

    Wraps existing memory backends. All operations fail-open.
    If primary backend is unavailable, falls back to JSONL.
    """

    def __init__(self, settings=None, workspace_dir: str = "workspace"):
        self._settings = settings
        self._workspace = Path(workspace_dir)
        self._workspace.mkdir(parents=True, exist_ok=True)

        # JSONL fallback (always available)
        self._fallback_path = self._workspace / "memory_facade_store.jsonl"

        # Backend availability cache
        self._backends: dict[str, _BackendStatus] = {}
        for name in ["memory_bus", "memory_toolkit", "knowledge_memory",
                      "decision_memory", "objective_store", "improvement_memory",
                      "memory_bus_patches", "knowledge_jsonl"]:
            self._backends[name] = _BackendStatus(name)

        # knowledge_jsonl is always available (it's local files)
        self._backends["knowledge_jsonl"].available = True
        self._backends["knowledge_jsonl"].last_check = time.time()

    # ── Store ─────────────────────────────────────────────────────────────────

    def store(
        self,
        content: str,
        content_type: str = "general",
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """
        Store content in the most appropriate backend.

        Routes based on content_type. Falls back to JSONL if backend unavailable.
        Returns {"ok": True/False, "backend": "...", "entry_id": "..."}.
        Never raises.
        """
        if content_type not in CONTENT_TYPES:
            content_type = "general"
        tags = tags or []
        metadata = metadata or {}
        entry_id = hashlib.md5(f"{content[:100]}:{time.time()}".encode()).hexdigest()[:12]

        # Try preferred backends in order
        backends = _ROUTING.get(content_type, ["knowledge_jsonl"])
        for backend_name in backends:
            try:
                ok = self._store_to_backend(backend_name, content, content_type, tags, metadata, entry_id)
                if ok:
                    return {"ok": True, "backend": backend_name, "entry_id": entry_id}
            except Exception as e:
                self._backends[backend_name].available = False
                self._backends[backend_name].error = str(e)[:100]
                log.debug("memory_facade_store_fallthrough", backend=backend_name, err=str(e)[:80])

        # Fallback to JSONL
        try:
            self._store_jsonl(content, content_type, tags, metadata, entry_id)
            return {"ok": True, "backend": "jsonl_fallback", "entry_id": entry_id}
        except Exception as e:
            log.debug("memory_facade_store_failed", err=str(e)[:80])
            return {"ok": False, "backend": "none", "entry_id": entry_id}

    def _store_to_backend(
        self, backend: str, content: str, content_type: str,
        tags: list[str], metadata: dict, entry_id: str,
    ) -> bool:
        """Attempt to store in a specific backend. Returns True if successful."""
        if backend == "memory_toolkit":
            return self._store_memory_toolkit(content, content_type, tags)
        elif backend == "memory_bus":
            return self._store_memory_bus(content, content_type, tags, metadata)
        elif backend == "memory_bus_patches":
            return self._store_memory_bus_patch(content, metadata)
        elif backend == "knowledge_memory":
            return self._store_knowledge_memory(content, tags)
        elif backend == "decision_memory":
            return self._store_decision_memory(content, metadata)
        elif backend == "knowledge_jsonl":
            self._store_jsonl(content, content_type, tags, metadata, entry_id)
            return True
        return False

    def _store_memory_toolkit(self, content: str, content_type: str, tags: list[str]) -> bool:
        """Route to core/tools/memory_toolkit.py functions."""
        try:
            if content_type == "solution":
                from core.tools.memory_toolkit import memory_store_solution
                result = memory_store_solution(problem=tags[0] if tags else "unknown", solution=content, tags=tags)
                return result.get("success", False)
            elif content_type == "error":
                from core.tools.memory_toolkit import memory_store_error
                result = memory_store_error(error_type=tags[0] if tags else "unknown", context=content)
                return result.get("success", False)
            elif content_type == "patch":
                from core.tools.memory_toolkit import memory_store_patch
                result = memory_store_patch(filename=tags[0] if tags else "unknown", description=content, diff="")
                return result.get("success", False)
            return False
        except ImportError:
            self._backends["memory_toolkit"].available = False
            return False
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:240")
            return False

    def _store_memory_bus(self, content: str, content_type: str, tags: list[str], metadata: dict) -> bool:
        """Route to memory/memory_bus.py."""
        try:
            from memory.memory_bus import MemoryBus
            if self._settings:
                bus = MemoryBus(self._settings)
                bus.remember(content, metadata={"type": content_type, **metadata}, tags=tags)
                self._backends["memory_bus"].available = True
                return True
            return False
        except ImportError:
            self._backends["memory_bus"].available = False
            return False
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:256")
            return False

    def _store_memory_bus_patch(self, content: str, metadata: dict) -> bool:
        """Route patch to MemoryBus.remember_patch()."""
        try:
            from memory.memory_bus import MemoryBus
            if self._settings:
                bus = MemoryBus(self._settings)
                bus.remember_patch(content, success=metadata.get("success", True), model=metadata.get("model", ""))
                return True
            return False
        except ImportError:
            return False
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:270")
            return False

    def _store_knowledge_memory(self, content: str, tags: list[str]) -> bool:
        """Route to core/knowledge_memory.py."""
        try:
            from core.knowledge_memory import get_knowledge_memory
            km = get_knowledge_memory()
            km.add(content=content, tags=tags)
            self._backends["knowledge_memory"].available = True
            return True
        except ImportError:
            self._backends["knowledge_memory"].available = False
            return False
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:284")
            return False

    def _store_decision_memory(self, content: str, metadata: dict) -> bool:
        """Route to memory/decision_memory.py."""
        try:
            from memory.decision_memory import get_decision_memory
            dm = get_decision_memory()
            dm.record(content=content, decision_type=metadata.get("decision_type", "general"))
            self._backends["decision_memory"].available = True
            return True
        except ImportError:
            self._backends["decision_memory"].available = False
            return False
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:298")
            return False

    def _store_jsonl(
        self, content: str, content_type: str,
        tags: list[str], metadata: dict, entry_id: str,
    ) -> None:
        """Fallback: append to local JSONL file."""
        entry = {
            "id": entry_id,
            "content": content[:3000],
            "type": content_type,
            "tags": tags[:10],
            "metadata": {k: str(v)[:200] for k, v in list(metadata.items())[:10]},
            "timestamp": time.time(),
        }
        with open(self._fallback_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        content_type: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """
        Search across all available memory backends.

        Merges results from multiple backends, deduplicates by content hash,
        and returns sorted by relevance. Never raises.
        """
        results: list[MemoryEntry] = []

        # 1. Try memory_toolkit search
        try:
            from core.tools.memory_toolkit import memory_search_similar
            search_result = memory_search_similar(query=query, top_k=top_k)
            if search_result.get("success") and search_result.get("output"):
                for item in search_result.get("results", []):
                    results.append(MemoryEntry(
                        content=str(item.get("payload", {}).get("solution", item.get("content", ""))),
                        content_type=item.get("payload", {}).get("type", "solution"),
                        tags=item.get("payload", {}).get("tags", []),
                        source="memory_toolkit",
                        score=item.get("score", 0.5),
                    ))
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:346")
            pass

        # 2. Try memory_bus search.
        # Root-cause fix: the previous implementation silently skipped vector search
        # whenever called from an async context (which is always the case during real
        # missions). We now run bus.search() on a fresh event loop in a daemon thread
        # so it never blocks or deadlocks the main event loop thread.
        try:
            from memory.memory_bus import MemoryBus
            if self._settings:
                bus = MemoryBus(self._settings)
                _result_q: _queue_module.Queue = _queue_module.Queue()

                def _run_bus_search():
                    try:
                        _loop = asyncio.new_event_loop()
                        try:
                            _res = _loop.run_until_complete(bus.search(query, top_k=top_k))
                            _result_q.put(("ok", _res))
                        finally:
                            _loop.close()
                    except Exception as _te:
                        _result_q.put(("err", str(_te)[:80]))

                _t = threading.Thread(target=_run_bus_search, daemon=True)
                _t.start()
                _t.join(timeout=3.0)  # 3s cap — memory search must be fast

                if not _t.is_alive():
                    try:
                        _status, _val = _result_q.get_nowait()
                        if _status == "ok" and isinstance(_val, list):
                            for item in _val:
                                results.append(MemoryEntry(
                                    content=str(item.get("content", "")),
                                    content_type=item.get("metadata", {}).get("type", "general"),
                                    source="memory_bus",
                                    score=item.get("score", 0.4),
                                ))
                    except _queue_module.Empty:
                        _silent_log.debug("suppressed_exception", src='memory_facade.py')
                else:
                    log.debug("memory_bus_search_thread_timeout", query=query[:40])
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:search_bus")


        # 3. Search JSONL fallback
        try:
            results.extend(self._search_jsonl(query, content_type, top_k))
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:373")
            pass

        # Deduplicate by content hash
        seen = set()
        unique = []
        for r in results:
            h = hashlib.md5(r.content[:200].encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(r)

        # Filter by content_type if specified
        if content_type:
            unique = [r for r in unique if r.content_type == content_type]

        # Sort by score (descending) and return top_k
        unique.sort(key=lambda x: x.score, reverse=True)
        return unique[:top_k]

    def _search_jsonl(
        self, query: str, content_type: str | None, top_k: int,
    ) -> list[MemoryEntry]:
        """Search JSONL fallback with basic text matching."""
        entries = []
        if not self._fallback_path.exists():
            return entries

        query_lower = query.lower()
        query_words = set(query_lower.split())

        try:
            for line in self._fallback_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if content_type and item.get("type") != content_type:
                        continue
                    content_lower = item.get("content", "").lower()
                    # Simple word-overlap scoring
                    content_words = set(content_lower.split())
                    overlap = len(query_words & content_words)
                    if overlap > 0:
                        score = min(overlap / max(len(query_words), 1), 1.0)
                        entries.append(MemoryEntry(
                            content=item.get("content", ""),
                            content_type=item.get("type", "general"),
                            tags=item.get("tags", []),
                            source="jsonl_fallback",
                            score=score * 0.6,  # Lower score than vector search
                            timestamp=item.get("timestamp", 0),
                            entry_id=item.get("id", ""),
                        ))
                except json.JSONDecodeError:
                    continue
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:429")
            pass

        entries.sort(key=lambda x: x.score, reverse=True)
        return entries[:top_k]

    # ── Get Recent ────────────────────────────────────────────────────────────

    def get_recent(
        self,
        content_type: str | None = None,
        n: int = 10,
    ) -> list[MemoryEntry]:
        """
        Get most recent memory entries, optionally filtered by type.
        Reads from JSONL fallback (always available). Never raises.
        """
        entries = []
        try:
            if not self._fallback_path.exists():
                return entries
            for line in self._fallback_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if content_type and item.get("type") != content_type:
                        continue
                    entries.append(MemoryEntry(
                        content=item.get("content", ""),
                        content_type=item.get("type", "general"),
                        tags=item.get("tags", []),
                        source="jsonl_fallback",
                        timestamp=item.get("timestamp", 0),
                        entry_id=item.get("id", ""),
                    ))
                except json.JSONDecodeError:
                    continue
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:467")
            pass
        entries.sort(key=lambda x: x.timestamp, reverse=True)
        return entries[:n]

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        """
        Check health of all memory backends.
        Returns {backend_name: {available, last_check, error}}.
        """
        self._probe_backends()
        return {
            name: status.to_dict()
            for name, status in self._backends.items()
        }

    def _probe_backends(self) -> None:
        """Probe each backend for availability."""
        now = time.time()
        for name, status in self._backends.items():
            # Only re-probe every 60s
            if now - status.last_check < 60:
                continue
            status.last_check = now
            try:
                if name == "memory_toolkit":
                    from core.tools.memory_toolkit import memory_search_similar
                    status.available = True
                elif name == "memory_bus":
                    from memory.memory_bus import MemoryBus
                    status.available = True
                elif name == "knowledge_memory":
                    from core.knowledge_memory import get_knowledge_memory
                    status.available = True
                elif name == "decision_memory":
                    from memory.decision_memory import get_decision_memory
                    status.available = True
                elif name == "improvement_memory":
                    from core.improvement_memory import get_improvement_memory
                    status.available = True
                elif name == "knowledge_jsonl":
                    status.available = True
                status.error = ""
            except ImportError as e:
                status.available = False
                status.error = f"ImportError: {e}"
            except Exception as e:
                status.available = False
                status.error = str(e)[:100]

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self, older_than_days: int = 30) -> dict:
        """
        Clean up expired entries from JSONL fallback.
        Does NOT touch other backends (they have their own lifecycle).
        Returns {removed: int, remaining: int}. Never raises.
        """
        try:
            if not self._fallback_path.exists():
                return {"removed": 0, "remaining": 0}

            cutoff = time.time() - (older_than_days * 86400)
            lines = self._fallback_path.read_text(encoding="utf-8").strip().split("\n")
            kept = []
            removed = 0
            for line in lines:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if item.get("timestamp", 0) < cutoff:
                        removed += 1
                    else:
                        kept.append(line)
                except json.JSONDecodeError:
                    kept.append(line)

            self._fallback_path.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")
            return {"removed": removed, "remaining": len(kept)}
        except Exception as e:
            log.debug("memory_facade_cleanup_failed", err=str(e)[:80])
            return {"removed": 0, "remaining": -1}

    def search_relevant(
        self,
        query: str,
        min_score: float = 0.3,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """Search with relevance filter — only returns entries above min_score."""
        results = self.search(query=query, top_k=top_k * 2)  # fetch more, then filter
        filtered = [r for r in results if (r.score or 0) >= min_score]
        # Sort by score descending
        filtered.sort(key=lambda e: e.score or 0, reverse=True)
        return filtered[:top_k]

    def stats(self) -> dict:
        """Return memory system health statistics."""
        stat: dict = {"backends": {}}
        try:
            jsonl = self._workspace / "memory_store.jsonl"
            if jsonl.exists():
                lines = sum(1 for _ in open(jsonl))
                stat["backends"]["jsonl"] = {"entries": lines}
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:574")
            pass
        try:
            from memory.vault_memory import get_vault_memory
            vault = get_vault_memory()
            stat["backends"]["vault"] = {"tables": len(vault.table_names()) if hasattr(vault, 'table_names') else -1}
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:580")
            pass
        try:
            from memory.decision_memory import get_decision_memory
            dm = get_decision_memory()
            stat["backends"]["decision"] = {"entries": dm.count() if hasattr(dm, 'count') else -1}
        except Exception as _exc:
            log.debug("memory_exception", err=str(_exc)[:120], location="memory_facade:586")
            pass
        stat["backend_count"] = len(stat["backends"])
        return stat



    # ── Convenience methods (route through store) ────────────────

    def store_decision(self, content: str, mission_id: str = "", **meta) -> dict:
        """Store a decision/audit entry."""
        return self.store(
            content=content,
            content_type="decision",
            tags=["decision"] + ([f"mission:{mission_id}"] if mission_id else []),
            metadata={"mission_id": mission_id, **meta},
        )

    def store_failure(self, content: str, error_class: str = "", mission_id: str = "") -> dict:
        """Store a failure for learning."""
        # AI OS memory layer integration (fail-open)
        try:
            from core.memory.memory_layers import get_memory_layer, MemoryMetadata
            ml = get_memory_layer()
            ml.store(content[:500], "mission_memory",
                     metadata=MemoryMetadata(source="orchestrator", confidence=0.8,
                                              scope=f"mission:{mission_id}",
                                              tags=["failure", error_class]),
                     mission_id=mission_id, importance=0.8)
        except Exception:
            _silent_log.debug("suppressed_exception", src='memory_facade.py')
        # AI OS vector memory for failure (fail-open)
        try:
            from core.memory.vector_memory import get_vector_memory
            vm = get_vector_memory()
            vm.store_embedding(content[:500], "mission_memory",
                               source="orchestrator", mission_id=mission_id,
                               importance=0.8, confidence=0.8,
                               tags=["failure", error_class])
        except Exception:
            _silent_log.debug("suppressed_exception", src='memory_facade.py')
        return self.store(
            content=content,
            content_type="failure",
            tags=["failure", error_class] if error_class else ["failure"],
            metadata={"mission_id": mission_id, "error_class": error_class},
        )

    def store_outcome(self, content: str, mission_id: str = "", status: str = "done") -> dict:
        """Store a mission outcome."""
        # AI OS memory layer integration (fail-open)
        try:
            from core.memory.memory_layers import get_memory_layer, MemoryMetadata
            ml = get_memory_layer()
            ml.store(content[:500], "mission_memory",
                     metadata=MemoryMetadata(source="orchestrator", confidence=0.7,
                                              scope=f"mission:{mission_id}"),
                     mission_id=mission_id, importance=0.6)
        except Exception:
            _silent_log.debug("suppressed_exception", src='memory_facade.py')
        # AI OS vector memory (fail-open, async-like)
        try:
            from core.memory.vector_memory import get_vector_memory
            vm = get_vector_memory()
            vm.store_embedding(content[:500], "mission_memory",
                               source="orchestrator", mission_id=mission_id,
                               importance=0.6, confidence=0.7)
        except Exception:
            _silent_log.debug("suppressed_exception", src='memory_facade.py')
        return self.store(
            content=content,
            content_type="mission_outcome",
            tags=["outcome", status],
            metadata={"mission_id": mission_id, "status": status},
        )

    def get_decisions(self, query: str = "", top_k: int = 5) -> list:
        """Retrieve recent decisions."""
        return self.search(query or "decision", content_type="decision", top_k=top_k)

    def get_failures(self, query: str = "", top_k: int = 5) -> list:
        """Retrieve recent failures."""
        return self.search(query or "failure error", content_type="failure", top_k=top_k)

# ═══════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════

_facade: MemoryFacade | None = None
_facade_lock = threading.Lock()


def get_memory_facade(settings=None, workspace_dir: str = "workspace") -> MemoryFacade:
    """Return singleton MemoryFacade instance. Thread-safe double-checked locking."""
    global _facade
    if _facade is None:
        with _facade_lock:
            if _facade is None:
                _facade = MemoryFacade(settings=settings, workspace_dir=workspace_dir)
                try:
                    log.info("memory_facade.singleton_created")
                except Exception:
                    _silent_log.debug("suppressed_exception", src='memory_facade.py')
    return _facade
