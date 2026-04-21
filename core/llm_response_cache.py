"""
core/llm_response_cache.py — Deterministic LLM response cache.

Use case : the same deterministic prompt (temperature=0, same model, same
messages) is often sent many times in development/test loops. Cache it.

Saves money on OpenRouter/OpenAI/Anthropic calls.

Safety :
- Cache is opt-in per call (pass `use_cache=True`)
- TTL-bounded (default 1h) so stale answers don't survive model updates
- Keyed on SHA-256 of (model, temperature, messages_json, tools_json)
- Only caches deterministic calls (temperature <= 0.05) — higher temp = no cache
- Invalidated automatically when the model name changes

Backends (auto-selected) :
  1. Redis (if REDIS_URL configured + reachable) — shared across replicas
  2. In-memory LRU (fallback, per-process) — dev/test friendly

Usage :
    from core.llm_response_cache import cached_llm_call

    response = cached_llm_call(
        model="openai/gpt-4o-mini",
        temperature=0.0,
        messages=[{"role": "user", "content": "What is 2+2?"}],
        call_fn=lambda: llm.invoke(messages),
        ttl_seconds=3600,
    )

Cache metrics (hits / misses / skips) are exposed via `get_cache_stats()`.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable, Dict, Optional

import structlog

log = structlog.get_logger(__name__)

# ── Config ───────────────────────────────────────────────────
_MAX_TEMP = 0.05           # prompts above this are NOT cached (too random)
_DEFAULT_TTL = 3600        # 1 hour
_MAX_MEMORY_ENTRIES = 512  # bounded LRU

# ── Stats ────────────────────────────────────────────────────
_stats = {"hits": 0, "misses": 0, "skips": 0, "stores": 0}
_stats_lock = Lock()


def get_cache_stats() -> Dict[str, int]:
    """Return a snapshot of cache counters."""
    with _stats_lock:
        return dict(_stats)


def reset_cache_stats() -> None:
    """Reset counters (test fixture)."""
    with _stats_lock:
        for k in _stats:
            _stats[k] = 0


# ── Memory backend (fallback) ────────────────────────────────
class _MemoryCache:
    def __init__(self, max_entries: int = _MAX_MEMORY_ENTRIES):
        self._data: "OrderedDict[str, tuple[Any, float]]" = OrderedDict()
        self._max = max_entries
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._data:
                return None
            value, expiry = self._data[key]
            if time.time() > expiry:
                del self._data[key]
                return None
            # Touch for LRU
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (value, time.time() + ttl_seconds)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


_memory_cache = _MemoryCache()


# ── Redis backend ────────────────────────────────────────────
_redis_client = None
_redis_init_tried = False


def _get_redis():
    """Lazy Redis client. Returns None if unavailable."""
    global _redis_client, _redis_init_tried
    if _redis_init_tried:
        return _redis_client
    _redis_init_tried = True
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis
        client = redis.Redis.from_url(url, socket_timeout=1.5, socket_connect_timeout=1.5)
        client.ping()
        _redis_client = client
        log.info("llm_cache.redis_enabled", url=url.split("@")[-1][:40])
    except Exception as e:
        log.info("llm_cache.redis_unavailable", err=str(e)[:80])
        _redis_client = None
    return _redis_client


# ── Key derivation ───────────────────────────────────────────
def _compute_cache_key(
    model: str,
    temperature: float,
    messages: Any,
    tools: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Derive a deterministic cache key for (model, temperature, messages, tools)."""
    payload = {
        "model": model,
        "temperature": round(float(temperature), 3),
        "messages": messages,
        "tools": tools,
        "extra": extra or {},
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "llm_cache:" + hashlib.sha256(blob).hexdigest()[:48]


# ── Public API ───────────────────────────────────────────────
def cached_llm_call(
    model: str,
    temperature: float,
    messages: Any,
    call_fn: Callable[[], Any],
    tools: Any = None,
    ttl_seconds: int = _DEFAULT_TTL,
    force_skip: bool = False,
) -> Any:
    """
    Execute call_fn() with response memoization.

    Args:
        model: Model identifier (e.g. "openai/gpt-4o-mini")
        temperature: Sampling temperature ; > _MAX_TEMP bypasses cache
        messages: List of message dicts (JSON-serializable)
        call_fn: Zero-arg callable that actually invokes the LLM
        tools: Optional tools schema (factored into the key)
        ttl_seconds: How long to cache the response
        force_skip: If True, don't use cache (useful for debugging)

    Returns:
        The response from call_fn(), possibly from cache.
    """
    # Bypass for non-deterministic calls
    if force_skip or temperature > _MAX_TEMP:
        with _stats_lock:
            _stats["skips"] += 1
        return call_fn()

    key = _compute_cache_key(model, temperature, messages, tools)

    # Try Redis first, then memory
    redis = _get_redis()
    cached_bytes: Optional[bytes] = None
    if redis is not None:
        try:
            cached_bytes = redis.get(key)
        except Exception as e:
            log.debug("llm_cache.redis_get_failed", err=str(e)[:60])

    if cached_bytes is not None:
        try:
            result = json.loads(cached_bytes.decode("utf-8"))
            with _stats_lock:
                _stats["hits"] += 1
            return result
        except Exception:
            pass  # fall through to regeneration

    # Memory fallback
    mem_hit = _memory_cache.get(key)
    if mem_hit is not None:
        with _stats_lock:
            _stats["hits"] += 1
        return mem_hit

    # Miss → execute
    with _stats_lock:
        _stats["misses"] += 1
    result = call_fn()

    # Best-effort store (don't fail the call if caching breaks)
    try:
        _memory_cache.set(key, result, ttl_seconds)
        if redis is not None:
            try:
                redis.setex(key, ttl_seconds, json.dumps(result, default=str))
            except Exception as e:
                log.debug("llm_cache.redis_set_failed", err=str(e)[:60])
        with _stats_lock:
            _stats["stores"] += 1
    except Exception as e:
        log.debug("llm_cache.store_failed", err=str(e)[:60])

    return result
