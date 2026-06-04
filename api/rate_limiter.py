"""
JARVIS MAX — Rate Limiter (Redis + In-Memory fallback)
========================================================
Sliding-window rate limiting per IP+path.

Design:
- Redis sliding window: ZADD only on allow, prune before count
- In-memory fallback: same semantics, dict[key] → list[timestamps]
- Fail-open: if Redis errors, fall back to in-memory
- Key format: rl:{ip}:{path_prefix} (both backends use same format)
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)

# ── Route group limits (requests per window) ──

ROUTE_LIMITS: dict[str, tuple[int, int]] = {
    # (max_requests, window_seconds)
    "/auth/":     (10, 60),     # Auth: 10/min
    "/api/v1/":   (60, 60),     # API v1: 60/min
    "/api/v2/":   (60, 60),     # API v2: 60/min
    "/api/v3/":   (60, 60),     # API v3: 60/min
    "/health":    (120, 60),    # Health: 120/min
    "default":    (30, 60),     # Everything else: 30/min
}


def _trusted_proxy_ips() -> set[str]:
    return {
        ip.strip()
        for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
        if ip.strip()
    }


def _client_ip_from_scope(scope) -> str:
    direct_ip = scope.get("client", ("unknown",))[0] if scope.get("client") else "unknown"
    if direct_ip not in _trusted_proxy_ips():
        return direct_ip

    headers = dict(scope.get("headers", []))
    fwd = headers.get(b"x-forwarded-for", b"").decode("latin-1").strip()
    if not fwd:
        return direct_ip
    return fwd.split(",", 1)[0].strip() or direct_ip


def _route_key(path: str) -> str:
    """Map a path to its route group prefix (max 50 chars)."""
    for prefix in ("/auth/", "/api/v1/", "/api/v2/", "/api/v3/", "/health"):
        if path.startswith(prefix):
            return prefix
    return path[:50]


def _get_limit(path: str) -> tuple[int, int]:
    """Get (max_requests, window_seconds) for a path."""
    for prefix, limit in ROUTE_LIMITS.items():
        if prefix != "default" and path.startswith(prefix):
            return limit
    return ROUTE_LIMITS["default"]


# ═══════════════════════════════════════════════════════════════
# IN-MEMORY BACKEND
# ═══════════════════════════════════════════════════════════════

class InMemoryRateLimiter:
    """Thread-safe in-memory sliding window limiter."""

    def __init__(self):
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 min

    def allow(self, client_ip: str, path: str) -> bool:
        """Check and record a request. Returns True if allowed."""
        key = f"rl:{client_ip}:{_route_key(path)}"
        max_req, window = _get_limit(path)
        now = time.time()
        cutoff = now - window

        with self._lock:
            # Prune old entries
            bucket = self._buckets[key]
            self._buckets[key] = [ts for ts in bucket if ts > cutoff]
            bucket = self._buckets[key]

            # Count current window
            if len(bucket) >= max_req:
                return False

            # Only add timestamp on allow
            bucket.append(now)
            self._maybe_cleanup(now)
            return True

    def _maybe_cleanup(self, now: float) -> None:
        """Periodic cleanup of stale buckets (called under lock)."""
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale = [k for k, v in self._buckets.items() if not v]
        for k in stale:
            del self._buckets[k]


# ═══════════════════════════════════════════════════════════════
# REDIS BACKEND
# ═══════════════════════════════════════════════════════════════

class RedisRateLimiter:
    """Redis sorted-set sliding window limiter."""

    def __init__(self, redis_client):
        self._redis = redis_client

    def allow(self, client_ip: str, path: str) -> bool:
        """Check and record a request. Returns True if allowed."""
        key = f"rl:{client_ip}:{_route_key(path)}"
        max_req, window = _get_limit(path)
        now = time.time()
        cutoff = now - window

        try:
            pipe = self._redis.pipeline(True)
            # 1. Prune old entries
            pipe.zremrangebyscore(key, 0, cutoff)
            # 2. Count current window
            pipe.zcard(key)
            results = pipe.execute()
            current_count = results[1]

            if current_count >= max_req:
                return False

            # 3. Only add on allow (not before the check)
            pipe2 = self._redis.pipeline(True)
            pipe2.zadd(key, {str(now): now})
            pipe2.expire(key, window + 10)  # TTL = window + buffer
            pipe2.execute()
            return True

        except Exception as e:
            logger.debug(f"Redis rate limiter error: {e}")
            raise  # Let caller fall back


# ═══════════════════════════════════════════════════════════════
# COMPOSITE LIMITER (Redis → In-Memory failover)
# ═══════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Production rate limiter.
    Tries Redis first; falls back to in-memory on any error.
    """

    def __init__(self, redis_client=None):
        self._redis_limiter = RedisRateLimiter(redis_client) if redis_client else None
        self._memory_limiter = InMemoryRateLimiter()

    def allow(self, client_ip: str, path: str) -> bool:
        """Returns True if request is allowed."""
        if self._redis_limiter:
            try:
                return self._redis_limiter.allow(client_ip, path)
            except Exception:
                logger.debug("rate_limiter_redis_failed_fallback_memory", exc_info=True)  # Fail-open: fall back to in-memory
        return self._memory_limiter.allow(client_ip, path)


# ═══════════════════════════════════════════════════════════════
# STARLETTE MIDDLEWARE WRAPPER
# ═══════════════════════════════════════════════════════════════

# Paths that bypass rate limiting (health probes, static assets)
_RATE_LIMIT_EXEMPT_PREFIXES = ("/health", "/readiness", "/static", "/index.html", "/favicon")

_global_limiter = RateLimiter()


class RateLimitMiddleware:
    """
    ASGI middleware that enforces sliding-window rate limiting per IP+path.

    Exempt paths: health, readiness, static assets.
    Returns HTTP 429 with Retry-After header on violation.
    Fail-open: if the limiter raises unexpectedly, the request passes through.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Exempt health/static paths
        if any(path.startswith(p) for p in _RATE_LIMIT_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Trust X-Forwarded-For only from explicitly configured proxies.
        client_ip = _client_ip_from_scope(scope)

        try:
            allowed = _global_limiter.allow(client_ip, path)
        except Exception:
            allowed = True  # Fail-open

        if not allowed:
            _, window = _get_limit(path)
            body = b'{"detail":"Too Many Requests","retry_after":' + str(window).encode() + b"}"
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(window).encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            logger.warning("rate_limit_exceeded", extra={"client_ip": client_ip, "path": path})
            return

        await self.app(scope, receive, send)
