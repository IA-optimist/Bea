"""
Redis L1 Cache for Memory System
==================================
Fast in-memory cache layer for PostgreSQL memory backend.

Features:
- Sub-millisecond reads for hot data
- TTL-based expiration (default 1 hour)
- Graceful degradation (cache miss → PostgreSQL fallback)
- Optional: cache warming on startup

Usage:
    cache = RedisMemoryCache()
    cache.set("vault:entry_123", {"content": "..."}, ttl=3600)
    result = cache.get("vault:entry_123")  # Returns dict or None
"""
from __future__ import annotations

import json
import os
from typing import Any

import structlog

log = structlog.get_logger()

# Optional dependency
try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    log.warning("redis_cache.unavailable", hint="pip install redis")


class RedisMemoryCache:
    """
    Redis-based L1 cache for memory system.
    
    Cache keys format:
    - vault:{memory_type}:{key}
    - mission:{mission_id}
    - knowledge:{concept_id}
    
    TTL Strategy:
    - Hot data (vault, mission): 1 hour
    - Knowledge graph: 4 hours
    - Improvement lessons: 24 hours
    """
    
    def __init__(self, redis_url: str | None = None, default_ttl: int = 3600):
        """
        Initialize Redis cache.
        
        Args:
            redis_url: Redis connection string (redis://host:port/db)
                      Falls back to REDIS_URL env var
            default_ttl: Default TTL in seconds (1 hour default)
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.default_ttl = default_ttl
        self._client = None
        
        if not _REDIS_AVAILABLE:
            log.warning("redis_cache.init_skipped", reason="redis not installed")
            return
        
        try:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,  # Auto-decode bytes to str
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Test connection
            self._client.ping()
            log.info("redis_cache.connected", host=self._get_host())
        except Exception as e:
            log.error("redis_cache.connection_failed", error=str(e))
            self._client = None
    
    def _get_host(self) -> str:
        """Extract hostname from redis_url for logging."""
        if not self.redis_url:
            return "none"
        try:
            # Format: redis://host:port/db
            parts = self.redis_url.split("//")
            if len(parts) < 2:
                return "localhost"
            host_part = parts[1].split("/")[0].split(":")[0]
            return host_part
        except Exception:
            return "unknown"
    
    def is_available(self) -> bool:
        """Check if cache is available."""
        return _REDIS_AVAILABLE and self._client is not None
    
    def get(self, key: str) -> dict[str, Any] | None:
        """
        Get cached entry.
        
        Args:
            key: Cache key (e.g., "vault:mission:abc123")
        
        Returns:
            Cached value dict or None if not found/expired
        """
        if not self.is_available():
            return None
        
        try:
            value = self._client.get(key)
            if value:
                log.debug("redis_cache.hit", key=key)
                return json.loads(value)
            log.debug("redis_cache.miss", key=key)
            return None
        except Exception as e:
            log.error("redis_cache.get_failed", key=key, error=str(e))
            return None
    
    def set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> bool:
        """
        Set cached entry with TTL.
        
        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable dict)
            ttl: Time-to-live in seconds (uses default_ttl if None)
        
        Returns:
            True if cached successfully, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            ttl_seconds = ttl if ttl is not None else self.default_ttl
            self._client.setex(
                key,
                ttl_seconds,
                json.dumps(value),
            )
            log.debug("redis_cache.set", key=key, ttl=ttl_seconds)
            return True
        except Exception as e:
            log.error("redis_cache.set_failed", key=key, error=str(e))
            return False
    
    def delete(self, key: str) -> bool:
        """Invalidate cache entry."""
        if not self.is_available():
            return False
        
        try:
            self._client.delete(key)
            log.debug("redis_cache.deleted", key=key)
            return True
        except Exception as e:
            log.error("redis_cache.delete_failed", key=key, error=str(e))
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching pattern.
        
        Args:
            pattern: Redis pattern (e.g., "vault:mission:*")
        
        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            return 0
        
        try:
            keys = self._client.keys(pattern)
            if keys:
                count = self._client.delete(*keys)
                log.info("redis_cache.pattern_deleted", pattern=pattern, count=count)
                return count
            return 0
        except Exception as e:
            log.error("redis_cache.pattern_delete_failed", pattern=pattern, error=str(e))
            return 0
    
    def flush_all(self) -> bool:
        """
        Clear entire cache (USE WITH CAUTION).
        
        Returns:
            True if flushed successfully
        """
        if not self.is_available():
            return False
        
        try:
            self._client.flushdb()
            log.warning("redis_cache.flushed")
            return True
        except Exception as e:
            log.error("redis_cache.flush_failed", error=str(e))
            return False
    
    def stats(self) -> dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dict with hits, misses, size, etc.
        """
        if not self.is_available():
            return {"available": False}
        
        try:
            info = self._client.info("stats")
            return {
                "available": True,
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "hit_rate": (
                    info.get("keyspace_hits", 0) /
                    max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0), 1)
                ),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
            }
        except Exception as e:
            log.error("redis_cache.stats_failed", error=str(e))
            return {"available": False, "error": str(e)}
    
    def close(self):
        """Close Redis connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            log.info("redis_cache.closed")


# Singleton instance
_cache: RedisMemoryCache | None = None


def get_redis_cache() -> RedisMemoryCache:
    """Get shared Redis cache instance."""
    global _cache
    if _cache is None:
        _cache = RedisMemoryCache()
    return _cache


def reset_redis_cache():
    """Reset cache (for testing)."""
    global _cache
    if _cache:
        _cache.close()
    _cache = None
