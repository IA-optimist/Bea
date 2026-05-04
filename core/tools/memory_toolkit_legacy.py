from __future__ import annotations
import structlog
log = structlog.get_logger("core.tools.memory_toolkit_legacy")
__all__ = ["store_memory", "search_memory", "get_recent_memories"]

def store_memory(key, content, tags=None):
    try:
        from core.memory_facade import get_memory_facade
        get_memory_facade().store(content=f"{key}: {content}", tags=tags or [])
        return True
    except Exception as e:
        log.debug("store_memory_failed", err=str(e)[:80])
        return False

def search_memory(query, top_k=5):
    try:
        from core.memory_facade import get_memory_facade
        results = get_memory_facade().search(query, top_k=top_k)
        return [{"content": getattr(r,"content","") if not isinstance(r,dict) else r.get("content",""),
                 "score": float(getattr(r,"score",0.0) if not isinstance(r,dict) else r.get("score",0.0))}
                for r in results]
    except Exception as e:
        log.debug("search_memory_failed", err=str(e)[:80])
        return []

def get_recent_memories(limit=10):
    try:
        from core.memory_facade import get_memory_facade
        f = get_memory_facade()
        return f.get_recent(limit=limit) if hasattr(f, "get_recent") else []
    except Exception as e:
        log.debug("get_recent_memories_failed", err=str(e)[:80])
        return []
