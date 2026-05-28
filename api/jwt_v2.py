"""JWT hardening v2 — short access + rotating refresh + revocation.

Audit follow-up (Mo2 prep): the legacy `api/auth.py` issues JWTs with a
30-day expiry and no revocation mechanism. A stolen token works for a
month with no way to invalidate it. This module implements the modern
two-token model — fully gated by ``JARVIS_JWT_HARDENING_V2`` so deploying
it does not invalidate active sessions.

Model
-----

  * **Access token** — JWT (HS256), short TTL (default 15 min). Claims:
    ``sub``, ``role``, ``iat``, ``exp``, ``jti`` (unique id for revocation
    lookup), ``typ="access"``.

  * **Refresh token** — opaque random string (32 bytes, urlsafe base64).
    Stored in Redis with metadata ``{sub, role, family_id, jti}`` and the
    configured refresh TTL. NOT a JWT — refresh tokens are sensitive so
    we don't reveal their claims via base64.

Rotation
--------

POST /auth/refresh with a refresh token returns a fresh access + refresh
pair, single-use. The old refresh token is moved to a short-lived
``used`` set so we can detect REPLAY:

  * If a presented refresh token is in the ``used`` set → token has been
    stolen and replayed. We immediately invalidate the entire ``family``
    (all refresh tokens issued in the chain) and force re-login.
  * If a refresh token is unknown → 401, no further damage.

Revocation
----------

Access tokens carry a ``jti``. Logout writes ``revoked:{jti}`` to Redis
with TTL = remaining access token lifetime. Verification rejects any
token whose ``jti`` is in the revoked set.

Refresh tokens are revoked by simply deleting their entry from Redis.

Feature flag
------------

  * ``JARVIS_JWT_HARDENING_V2`` (env). Off (default): legacy 30-day token.
    On: short access + rotating refresh.
  * ``JWT_ACCESS_TTL_SECONDS`` (env, default 900 = 15 minutes).
  * ``JWT_REFRESH_TTL_SECONDS`` (env, default 2592000 = 30 days).
  * ``JWT_REDIS_PREFIX`` (env, default ``jarvis:jwt:``).

Redis dependency
----------------

This module talks to Redis via a small :class:`RedisStore` protocol so
tests can pass an in-memory fake without pulling fakeredis. The default
implementation lazy-loads ``redis`` and connects to ``REDIS_URL``.

If Redis is unreachable, refresh and revocation **fail closed** (the
operation raises). Access token verification falls back to "no revocation
check possible" with a WARNING log, because failing closed there would
break every API call during a Redis outage.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────

_DEFAULT_PREFIX = "jarvis:jwt:"
_DEFAULT_ACCESS_TTL = 15 * 60          # 15 minutes
_DEFAULT_REFRESH_TTL = 30 * 24 * 60 * 60  # 30 days
_USED_REFRESH_GRACE = 60 * 60          # 1 hour replay window


def is_v2_enabled() -> bool:
    """Return True iff JARVIS_JWT_HARDENING_V2 is set to a truthy value."""
    return os.environ.get("JARVIS_JWT_HARDENING_V2", "0").lower() in {
        "1", "true", "yes", "on",
    }


def _access_ttl() -> int:
    return int(os.environ.get("JWT_ACCESS_TTL_SECONDS", _DEFAULT_ACCESS_TTL))


def _refresh_ttl() -> int:
    return int(os.environ.get("JWT_REFRESH_TTL_SECONDS", _DEFAULT_REFRESH_TTL))


def _prefix() -> str:
    return os.environ.get("JWT_REDIS_PREFIX", _DEFAULT_PREFIX)


# ── Redis store protocol + default impl ──────────────────────────

class RedisStore(Protocol):
    """Minimal subset of redis-py we use. Lets tests pass a fake."""

    def get(self, key: str) -> Optional[bytes]: ...
    def set(self, key: str, value: bytes, ex: Optional[int] = None) -> bool: ...
    def delete(self, key: str) -> int: ...
    def exists(self, key: str) -> int: ...
    def sadd(self, key: str, *values: bytes) -> int: ...
    def smembers(self, key: str) -> set[bytes]: ...
    def expire(self, key: str, seconds: int) -> bool: ...


_store_singleton: Optional[RedisStore] = None


def _get_store() -> RedisStore:
    """Lazy-load redis-py and return a connection. Raises if redis missing
    or unreachable. Tests inject via :func:`set_store_for_testing`.
    """
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton

    try:
        import redis  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover — redis is in requirements.lock
        raise RuntimeError(
            "JWT v2 requires the `redis` package. Install it or disable "
            "JARVIS_JWT_HARDENING_V2."
        ) from exc

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    _store_singleton = redis.Redis.from_url(url)
    return _store_singleton


def set_store_for_testing(store: Optional[RedisStore]) -> None:
    """Inject an in-memory fake store for tests. Pass ``None`` to reset."""
    global _store_singleton
    _store_singleton = store


# ── Token primitives ─────────────────────────────────────────────

@dataclass(frozen=True)
class TokenPair:
    """A freshly-issued (access, refresh) pair plus identifying metadata."""

    access_token: str
    refresh_token: str
    access_jti: str
    family_id: str
    access_expires_in: int
    refresh_expires_in: int


def _new_id(nbytes: int = 16) -> str:
    """Return a URL-safe random ID without padding."""
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode()


def _now() -> int:
    return int(time.time())


def _encode_access_jwt(claims: dict[str, Any], secret: str) -> str:
    import jwt as _jwt  # local import: pyjwt may not be present in some test runs
    return _jwt.encode(claims, secret, algorithm="HS256")


def _decode_access_jwt(token: str, secret: str) -> dict[str, Any]:
    import jwt as _jwt
    return _jwt.decode(token, secret, algorithms=["HS256"])


# ── Public API ───────────────────────────────────────────────────

def create_token_pair(
    *,
    sub: str,
    role: str,
    secret: str,
    store: Optional[RedisStore] = None,
) -> TokenPair:
    """Issue a fresh (access, refresh) pair for the given user.

    Generates a new ``family_id``; the refresh chain is tied to this id
    so the whole family can be invalidated atomically if a replay is
    detected later.

    Raises:
        RuntimeError: if Redis is unreachable.
    """
    if not sub:
        raise ValueError("sub (subject) is required")
    s = store or _get_store()
    now = _now()
    access_ttl = _access_ttl()
    refresh_ttl = _refresh_ttl()
    jti = _new_id()
    family_id = _new_id()
    refresh_token = _new_id(32)

    # Access — short JWT.
    access = _encode_access_jwt(
        {
            "sub": sub,
            "role": role,
            "iat": now,
            "exp": now + access_ttl,
            "jti": jti,
            "typ": "access",
        },
        secret,
    )

    # Refresh — opaque, stored server-side with metadata.
    rkey = f"{_prefix()}refresh:{refresh_token}"
    s.set(
        rkey,
        f"{sub}|{role}|{family_id}|{jti}".encode(),
        ex=refresh_ttl,
    )
    # Track the family so we can revoke wholesale.
    fkey = f"{_prefix()}family:{family_id}"
    s.sadd(fkey, refresh_token.encode())
    s.expire(fkey, refresh_ttl)

    return TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        access_jti=jti,
        family_id=family_id,
        access_expires_in=access_ttl,
        refresh_expires_in=refresh_ttl,
    )


def verify_access_token(
    token: str,
    secret: str,
    store: Optional[RedisStore] = None,
) -> Optional[dict[str, Any]]:
    """Decode an access JWT and check the revocation list.

    Returns the claims dict on success, ``None`` otherwise. Reasons it can
    return ``None``:

      * signature invalid,
      * token expired,
      * ``jti`` is in the revoked set.

    If Redis is unreachable, the revocation check is skipped (with a
    WARNING log). The signature and expiry checks still apply — failing
    closed there would break the whole API during a Redis outage.
    """
    try:
        claims = _decode_access_jwt(token, secret)
    except Exception as exc:
        logger.debug("jwt_v2_decode_failed: %s", exc)
        return None

    jti = claims.get("jti")
    if not jti:
        # Token does not carry a JTI — issued by legacy path. Accept it
        # without revocation check (it will expire naturally).
        return claims

    try:
        s = store or _get_store()
        if s.exists(f"{_prefix()}revoked:{jti}"):
            return None
    except Exception as exc:
        logger.warning(
            "jwt_v2_revocation_check_failed",
            extra={"exc_type": type(exc).__name__, "jti_prefix": jti[:8]},
        )
    return claims


def rotate_refresh_token(
    refresh_token: str,
    secret: str,
    store: Optional[RedisStore] = None,
) -> TokenPair:
    """Exchange a refresh token for a fresh (access, refresh) pair.

    Single-use rotation. On replay (refresh token already consumed) the
    entire family is revoked and ``ValueError`` is raised.

    Raises:
        ValueError: token is unknown, expired, or a replay was detected.
        RuntimeError: Redis unreachable.
    """
    s = store or _get_store()
    prefix = _prefix()

    # Detect replay first: was this token already consumed?
    if s.exists(f"{prefix}refresh_used:{refresh_token}"):
        used = s.get(f"{prefix}refresh_used:{refresh_token}")
        if used:
            try:
                _sub, _role, family_id, _jti = used.decode().split("|", 3)
            except ValueError:
                family_id = ""
            if family_id:
                _revoke_family(s, family_id)
        raise ValueError("refresh_token_replay_detected")

    rkey = f"{prefix}refresh:{refresh_token}"
    raw = s.get(rkey)
    if raw is None:
        raise ValueError("refresh_token_unknown_or_expired")

    try:
        sub, role, family_id, _parent_jti = raw.decode().split("|", 3)
    except ValueError as exc:
        raise ValueError("refresh_token_corrupted") from exc

    # Single-use: move to used set with short TTL for replay detection.
    s.delete(rkey)
    s.set(
        f"{prefix}refresh_used:{refresh_token}",
        raw,
        ex=_USED_REFRESH_GRACE,
    )

    # Issue new pair tied to the same family.
    new_jti = _new_id()
    new_refresh = _new_id(32)
    now = _now()
    access_ttl = _access_ttl()
    refresh_ttl = _refresh_ttl()

    access = _encode_access_jwt(
        {
            "sub": sub,
            "role": role,
            "iat": now,
            "exp": now + access_ttl,
            "jti": new_jti,
            "typ": "access",
        },
        secret,
    )

    s.set(
        f"{prefix}refresh:{new_refresh}",
        f"{sub}|{role}|{family_id}|{new_jti}".encode(),
        ex=refresh_ttl,
    )
    fkey = f"{prefix}family:{family_id}"
    s.sadd(fkey, new_refresh.encode())
    s.expire(fkey, refresh_ttl)

    return TokenPair(
        access_token=access,
        refresh_token=new_refresh,
        access_jti=new_jti,
        family_id=family_id,
        access_expires_in=access_ttl,
        refresh_expires_in=refresh_ttl,
    )


def revoke_access_jti(
    jti: str,
    *,
    remaining_ttl_seconds: Optional[int] = None,
    store: Optional[RedisStore] = None,
) -> None:
    """Mark an access token's ``jti`` as revoked.

    ``remaining_ttl_seconds`` should equal the time until the token's own
    ``exp`` (so the revocation entry self-cleans). If unknown, defaults to
    the configured access TTL (worst case: token expires before us).
    """
    if not jti:
        return
    s = store or _get_store()
    ttl = remaining_ttl_seconds if remaining_ttl_seconds is not None else _access_ttl()
    s.set(f"{_prefix()}revoked:{jti}", b"1", ex=max(ttl, 1))


def revoke_refresh_token(
    refresh_token: str,
    store: Optional[RedisStore] = None,
) -> None:
    """Invalidate a refresh token. Idempotent."""
    if not refresh_token:
        return
    s = store or _get_store()
    s.delete(f"{_prefix()}refresh:{refresh_token}")


def _revoke_family(s: RedisStore, family_id: str) -> None:
    """Invalidate every refresh token belonging to a compromised family."""
    if not family_id:
        return
    prefix = _prefix()
    fkey = f"{prefix}family:{family_id}"
    members = s.smembers(fkey)
    for raw in members:
        token = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        s.delete(f"{prefix}refresh:{token}")
    s.delete(fkey)
    logger.warning(
        "jwt_v2_family_revoked",
        extra={"family_id_prefix": family_id[:8], "revoked_count": len(members)},
    )
