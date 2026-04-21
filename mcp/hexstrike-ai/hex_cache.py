"""
HexStrike Cache — command result caching (LRU + TTL).

Extrait depuis hexstrike_server.py (17k lignes) pour isoler le composant
de caching autonome. Backward-compat : `from .hex_cache import HexStrikeCache, cache`.

NOTE : hexstrike_v2/core/cache.py expose un `CommandCache` plus moderne
(persistance disque, TTL par entrée, invalidation explicite). Cette
implémentation legacy est conservée pour ne pas casser les 150+ endpoints
de hexstrike v1 qui y font référence. Migration v1 → v2 est un chantier
séparé (voir MIGRATION_GUIDE.md dans hexstrike_v2/).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger("hexstrike_server")

CACHE_SIZE = 1000
CACHE_TTL = 3600  # 1 hour


class HexStrikeCache:
    """Advanced caching system for command results"""

    def __init__(self, max_size: int = CACHE_SIZE, ttl: int = CACHE_TTL):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.stats = {"hits": 0, "misses": 0, "evictions": 0}

    def _generate_key(self, command: str, params: Dict[str, Any]) -> str:
        """Generate cache key from command and parameters"""
        key_data = f"{command}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def _is_expired(self, timestamp: float) -> bool:
        """Check if cache entry is expired"""
        return time.time() - timestamp > self.ttl

    def get(self, command: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached result if available and not expired"""
        key = self._generate_key(command, params)

        if key in self.cache:
            timestamp, data = self.cache[key]
            if not self._is_expired(timestamp):
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                self.stats["hits"] += 1
                logger.info(f"💾 Cache HIT for command: {command}")
                return data
            else:
                # Remove expired entry
                del self.cache[key]

        self.stats["misses"] += 1
        logger.info(f"🔍 Cache MISS for command: {command}")
        return None

    def set(self, command: str, params: Dict[str, Any], result: Dict[str, Any]):
        """Store result in cache"""
        key = self._generate_key(command, params)

        # Remove oldest entries if cache is full
        while len(self.cache) >= self.max_size:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            self.stats["evictions"] += 1

        self.cache[key] = (time.time(), result)
        logger.info(f"💾 Cached result for command: {command}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hit_rate": f"{hit_rate:.1f}%",
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "evictions": self.stats["evictions"],
        }


# Global cache instance (singleton pattern pour backward-compat v1).
cache = HexStrikeCache()


__all__ = ["HexStrikeCache", "cache", "CACHE_SIZE", "CACHE_TTL"]
