"""
Command Cache — Cache command results to avoid repeated execution
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached command result"""
    key: str
    result: Any
    timestamp: float
    command: str
    ttl_seconds: int


class CommandCache:
    """
    LRU cache for command results.
    
    Usage:
        cache = CommandCache(max_size=1000, default_ttl=3600)
        
        # Store result
        cache.set("nmap -sV example.com", result_data)
        
        # Retrieve result
        cached = cache.get("nmap -sV example.com")
        if cached:
            print("Using cached result")
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 3600,  # 1 hour
        persist_path: Optional[Path] = None,
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.persist_path = persist_path
        
        # OrderedDict for LRU behavior
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        
        # Stats
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        
        # Load persisted cache if exists
        if persist_path and persist_path.exists():
            self._load_from_disk()
    
    def _make_key(self, command: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Generate cache key from command + params"""
        key_data = command
        if params:
            key_data += json.dumps(params, sort_keys=True)
        
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    def get(
        self,
        command: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """
        Get cached result if available and not expired.
        
        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(command, params)
        
        if key not in self._cache:
            self._misses += 1
            logger.debug(f"Cache miss: {command[:50]}...")
            return None
        
        entry = self._cache[key]
        
        # Check expiration
        age = time.time() - entry.timestamp
        if age > entry.ttl_seconds:
            logger.debug(f"Cache expired: {command[:50]}... (age: {age:.1f}s)")
            del self._cache[key]
            self._misses += 1
            return None
        
        # Move to end (LRU)
        self._cache.move_to_end(key)
        
        self._hits += 1
        logger.debug(f"Cache hit: {command[:50]}... (age: {age:.1f}s)")
        
        return entry.result
    
    def set(
        self,
        command: str,
        result: Any,
        ttl: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Store result in cache.
        
        Args:
            command: Command that was executed
            result: Result to cache
            ttl: Time-to-live in seconds (None = default)
            params: Command parameters (for key generation)
        """
        key = self._make_key(command, params)
        ttl = ttl or self.default_ttl
        
        entry = CacheEntry(
            key=key,
            result=result,
            timestamp=time.time(),
            command=command,
            ttl_seconds=ttl,
        )
        
        # Add to cache
        self._cache[key] = entry
        self._cache.move_to_end(key)
        
        # Evict oldest if over size
        if len(self._cache) > self.max_size:
            oldest_key, _ = self._cache.popitem(last=False)
            self._evictions += 1
            logger.debug(f"Cache evicted oldest entry (key: {oldest_key[:16]}...)")
        
        logger.debug(f"Cache set: {command[:50]}... (ttl: {ttl}s)")
        
        # Persist if configured
        if self.persist_path:
            self._save_to_disk()
    
    def invalidate(self, command: str, params: Optional[Dict[str, Any]] = None) -> bool:
        """
        Invalidate (remove) a cached entry.
        
        Returns:
            True if entry was found and removed
        """
        key = self._make_key(command, params)
        
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cache invalidated: {command[:50]}...")
            return True
        
        return False
    
    def clear(self) -> None:
        """Clear all cache entries"""
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared ({count} entries removed)")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "evictions": self._evictions,
        }
    
    def _save_to_disk(self) -> None:
        """Persist cache to disk as JSON."""
        if not self.persist_path:
            return

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = []
            for entry in self._cache.values():
                try:
                    json.dumps(entry.result)
                except TypeError:
                    logger.debug("Skipping non-JSON-serializable cache entry", extra={"key": entry.key[:16]})
                    continue
                payload.append({
                    "key": entry.key,
                    "result": entry.result,
                    "timestamp": entry.timestamp,
                    "command": entry.command,
                    "ttl_seconds": entry.ttl_seconds,
                })

            self.persist_path.write_text(json.dumps(payload), encoding="utf-8")

            logger.debug(f"Cache persisted to {self.persist_path}")
        except Exception as e:
            logger.error(f"Failed to persist cache: {e}")
    
    def _load_from_disk(self) -> None:
        """Load cache from disk."""
        if not self.persist_path or not self.persist_path.exists():
            return

        try:
            raw_entries = json.loads(self.persist_path.read_text(encoding="utf-8"))
            loaded: OrderedDict[str, CacheEntry] = OrderedDict()
            for item in raw_entries if isinstance(raw_entries, list) else []:
                entry = CacheEntry(
                    key=str(item["key"]),
                    result=item.get("result"),
                    timestamp=float(item["timestamp"]),
                    command=str(item["command"]),
                    ttl_seconds=int(item["ttl_seconds"]),
                )
                loaded[entry.key] = entry

            self._cache = loaded

            # Clean expired entries
            now = time.time()
            expired_keys = [
                key for key, entry in self._cache.items()
                if (now - entry.timestamp) > entry.ttl_seconds
            ]

            for key in expired_keys:
                del self._cache[key]

            logger.info(f"Cache loaded from {self.persist_path} ({len(self._cache)} entries)")
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
            self._cache = OrderedDict()


# Global cache instance
cache = CommandCache(
    max_size=1000,
    default_ttl=3600,
    persist_path=Path.home() / ".hexstrike" / "cache.json"
)
