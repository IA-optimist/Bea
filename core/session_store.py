"""
PolicyEngine session store abstraction.

Backends:
  InMemorySessionStore — dev/test, single-process, thread-safe.
  RedisSessionStore    — beta/prod, multi-worker.
                         Fail-closed: raises RuntimeError if Redis unreachable.
                         No silent fallback to memory.

Config (env vars):
  POLICY_SESSION_STORE       memory | redis  (default: memory)
  REDIS_URL                  required when store=redis
  POLICY_SESSION_TTL_SECONDS session TTL in seconds (default: 3600)

Known limitation (P2 — multi-worker atomicity):
  RedisSessionStore.get() returns a deserialized copy. SessionPolicy._lock is
  per-object, so check_and_record() is NOT atomically safe across multiple
  worker processes. For a single-worker beta deployment this is sufficient.
  Full multi-worker atomicity requires a Lua INCR script or Redis WATCH pattern
  — tracked as a future improvement.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

if TYPE_CHECKING:
    from core.policy_engine import SessionPolicy


# ──────────────────────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────────────────────

def _to_store_dict(session: "SessionPolicy") -> dict:
    age_s = time.monotonic() - session.started_at
    return {
        "session_id":   session.session_id,
        "limits":       session.limits,
        "actions_done": session.actions_done,
        "tokens_used":  session.tokens_used,
        "cloud_calls":  session.cloud_calls,
        "cost_usd":     session.cost_usd,
        "created_epoch": time.time() - age_s,
    }


def _from_store_dict(data: dict) -> "SessionPolicy":
    from core.policy_engine import SessionPolicy  # local import to avoid circular
    s = SessionPolicy.__new__(SessionPolicy)
    s.session_id   = data["session_id"]
    s.limits       = data["limits"]
    s.actions_done = data["actions_done"]
    s.tokens_used  = data["tokens_used"]
    s.cloud_calls  = data["cloud_calls"]
    s.cost_usd     = data["cost_usd"]
    # Map wall-clock creation time back to monotonic
    age_s = time.time() - data["created_epoch"]
    s.started_at   = time.monotonic() - age_s
    s._lock        = threading.Lock()
    return s


# ──────────────────────────────────────────────────────────────
# In-memory backend (dev / test)
# ──────────────────────────────────────────────────────────────

class InMemorySessionStore:
    """Thread-safe in-memory session store. Dev/test only."""

    def __init__(self) -> None:
        self._data: dict[str, "SessionPolicy"] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> "SessionPolicy | None":
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, session: "SessionPolicy") -> None:
        with self._lock:
            self._data[key] = session

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def items(self) -> list[tuple[str, "SessionPolicy"]]:
        with self._lock:
            return list(self._data.items())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data


# ──────────────────────────────────────────────────────────────
# Redis backend (beta / prod)
# ──────────────────────────────────────────────────────────────

class RedisSessionStore:
    """Redis-backed session store for multi-worker deployments.

    Fail-closed: if Redis is unreachable at construction, raises RuntimeError.
    There is NO silent fallback to InMemorySessionStore.

    Note: check_and_record() atomicity is per-object only (single-worker safe).
    True multi-worker atomic increment requires a Redis Lua script — see module
    docstring.
    """

    _PREFIX = "bea:policy:session:"

    @staticmethod
    def _redact_url(url: str) -> str:
        """Return a Redis URL safe for logs: hide password, keep scheme/host/port."""
        try:
            parsed = urlparse(url)
            if not parsed.hostname:
                return "<redacted>"
            safe_netloc = parsed.hostname
            if parsed.port:
                safe_netloc = f"{safe_netloc}:{parsed.port}"
            rebuilt = parsed._replace(netloc=safe_netloc)
            return urlunparse(rebuilt)
        except Exception:
            return "<redacted>"

    def __init__(self, redis_url: str, ttl_seconds: int = 3600) -> None:
        import redis as _redis
        try:
            self._client = _redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
        except Exception as exc:
            safe_url = self._redact_url(redis_url)
            raise RuntimeError(
                f"POLICY_SESSION_STORE=redis: cannot reach Redis at {safe_url}. "
                f"No fallback to memory. Fix Redis or set POLICY_SESSION_STORE=memory. "
                f"Cause: {exc}"
            ) from exc
        self._ttl = ttl_seconds

    def _k(self, key: str) -> str:
        return f"{self._PREFIX}{key}"

    def get(self, key: str) -> "SessionPolicy | None":
        raw = self._client.get(self._k(key))
        if raw is None:
            return None
        return _from_store_dict(json.loads(raw))

    def set(self, key: str, session: "SessionPolicy") -> None:
        self._client.setex(self._k(key), self._ttl, json.dumps(_to_store_dict(session)))

    def delete(self, key: str) -> None:
        self._client.delete(self._k(key))

    def keys(self) -> list[str]:
        prefix = self._k("")
        return [k[len(prefix):] for k in self._client.keys(f"{prefix}*")]

    def __len__(self) -> int:
        return len(self.keys())

    def items(self) -> list[tuple[str, "SessionPolicy"]]:
        return [(k, self.get(k)) for k in self.keys()]  # type: ignore[misc]

    def clear(self) -> None:
        for k in self.keys():
            self.delete(k)

    def __contains__(self, key: str) -> bool:
        return self._client.exists(self._k(key)) > 0


# ──────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────

def build_session_store() -> "InMemorySessionStore | RedisSessionStore":
    """Instantiate the correct store from environment variables.

    POLICY_SESSION_STORE=memory (default) — allowed in dev/test.
    POLICY_SESSION_STORE=redis            — required for beta/prod multi-worker.
      Requires REDIS_URL to be set. Raises RuntimeError if Redis unreachable.
    """
    store_type = os.getenv("POLICY_SESSION_STORE", "memory").strip().lower()
    ttl = int(os.getenv("POLICY_SESSION_TTL_SECONDS", "3600"))

    if store_type == "redis":
        url = os.getenv("REDIS_URL", "").strip()
        if not url:
            raise RuntimeError(
                "POLICY_SESSION_STORE=redis requires REDIS_URL to be set."
            )
        return RedisSessionStore(url, ttl_seconds=ttl)

    if store_type != "memory":
        raise RuntimeError(
            f"Unknown POLICY_SESSION_STORE={store_type!r}. Valid values: 'memory', 'redis'."
        )
    return InMemorySessionStore()
