"""
Session store abstraction for Bea.

Local development may use an in-memory store. Private/public beta and other
multi-process deployments must use Redis-backed storage explicitly.

The module keeps the interface small and testable. Redis is imported lazily so
unit tests do not require a live Redis service.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    def get(self, session_id: str) -> dict[str, Any] | None: ...

    def set(self, session_id: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None: ...

    def delete(self, session_id: str) -> None: ...


def _normalize_profile(profile: str | None) -> str:
    value = (profile or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"", "auto"}:
        return "local"
    if value in {"dev", "development", "local", "test"}:
        return "local"
    if value in {"beta", "private_beta", "public_beta", "production", "prod", "vps"}:
        return value
    return value


def _normalize_backend(backend: str | None) -> str:
    value = (backend or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not value:
        return "memory"
    if value in {"inmemory", "memory", "in_memory"}:
        return "memory"
    if value == "redis":
        return "redis"
    return value


@dataclass(frozen=True)
class SessionStoreConfig:
    profile: str = "local"
    backend: str = "memory"
    redis_url: str | None = None


class InMemorySessionStore:
    """Local-only, single-process-only, not beta-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, tuple[dict[str, Any], float | None]] = {}

    def _purge_expired(self, session_id: str | None = None) -> None:
        now = time.time()
        keys = [session_id] if session_id is not None else list(self._records.keys())
        for key in keys:
            if key is None:
                continue
            payload = self._records.get(key)
            if payload is None:
                continue
            _, expires_at = payload
            if expires_at is not None and expires_at <= now:
                self._records.pop(key, None)

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge_expired(session_id)
            payload = self._records.get(session_id)
            if payload is None:
                return None
            value, _ = payload
            return dict(value)

    def set(self, session_id: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        expires_at = None if ttl_seconds is None else time.time() + max(0, ttl_seconds)
        with self._lock:
            self._records[session_id] = (dict(value), expires_at)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._records.pop(session_id, None)


class RedisSessionStore:
    """Redis-backed, multi-process-safe session store.

    Redis is imported lazily. The store never logs session contents.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        *,
        client: Any | None = None,
        key_prefix: str = "bea:session",
    ) -> None:
        self.redis_url = redis_url or os.getenv("BEA_REDIS_URL") or os.getenv("REDIS_URL") or ""
        self._client = client
        self._key_prefix = key_prefix.rstrip(":") + ":"

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}"

    def _require_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.redis_url:
            raise RuntimeError("RedisSessionStore requires BEA_REDIS_URL or REDIS_URL")
        try:
            import redis  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - import failure path
            raise RuntimeError("redis package is not installed") from exc
        self._client = redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def ping(self) -> bool:
        client = self._require_client()
        return bool(client.ping())

    def get(self, session_id: str) -> dict[str, Any] | None:
        client = self._require_client()
        raw = client.get(self._key(session_id))
        if raw in (None, ""):
            return None
        try:
            value = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON payload for session {session_id!r}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Session payload for {session_id!r} is not an object")
        return value

    def set(self, session_id: str, value: dict[str, Any], ttl_seconds: int | None = None) -> None:
        client = self._require_client()
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        key = self._key(session_id)
        if ttl_seconds is None:
            client.set(key, payload)
            return
        client.setex(key, int(ttl_seconds), payload)

    def delete(self, session_id: str) -> None:
        client = self._require_client()
        client.delete(self._key(session_id))


def get_session_store(profile: str | None = None, config: Any | None = None, *, client: Any | None = None) -> SessionStore:
    """Return the session store for a requested profile.

    Local/dev/test profiles may use in-memory storage.
    Beta/prod profiles require Redis explicitly and never fall back silently.
    """
    cfg = config
    backend = None
    redis_url = None
    if cfg is not None:
        backend = getattr(cfg, "bea_session_store", None)
        redis_url = getattr(cfg, "bea_redis_url", None)
    backend = _normalize_backend(backend or os.getenv("BEA_SESSION_STORE"))
    if not redis_url:
        redis_url = os.getenv("BEA_REDIS_URL") or os.getenv("REDIS_URL")
    resolved_profile = _normalize_profile(profile)
    beta_profiles = {"beta", "private_beta", "public_beta", "production", "prod", "vps"}

    if resolved_profile in beta_profiles:
        if backend != "redis":
            raise RuntimeError(f"{resolved_profile} requires BEA_SESSION_STORE=redis")
        if not redis_url:
            raise RuntimeError(f"{resolved_profile} requires BEA_REDIS_URL or REDIS_URL")
        return RedisSessionStore(redis_url=redis_url, client=client)

    if backend == "redis":
        if not redis_url:
            raise RuntimeError("Redis session store requested but BEA_REDIS_URL/REDIS_URL is missing")
        return RedisSessionStore(redis_url=redis_url, client=client)

    return InMemorySessionStore()
