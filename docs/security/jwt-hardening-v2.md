# JWT Hardening v2 — Rollout Guide

**Status:** prep complete, feature flag off in production.
**Audit reference:** Mo2.

## What changes

The legacy `api/auth.py` issues JWTs with a 30-day expiry and no
revocation mechanism. A stolen token works for a month with no way to
invalidate it.

This rollout introduces a modern two-token model behind a feature flag
(`JARVIS_JWT_HARDENING_V2`). When the flag is **off**, behavior is
unchanged (30-day single token). When the flag is **on**:

| Concept | Legacy (flag off) | v2 (flag on) |
|---|---|---|
| Access TTL | 30 days | 15 minutes (configurable) |
| Refresh token | none | opaque, single-use, rotating |
| Revocation | not possible | server-side, both access (jti) and refresh |
| Replay detection | n/a | yes; revokes the whole token family |
| Storage | stateless | access still stateless, refresh in Redis |
| Logout | clear cookie only | also revokes server-side |

## How v2 works

### Access token

Same shape as the legacy JWT (HS256, base64-encoded claims) but with
extra fields:

- `jti` — random unique ID (16 bytes, urlsafe base64). Used by the
  revocation list.
- `typ` — `"access"`. Distinguishes from any future refresh-JWT variants.
- `exp` — `iat + JWT_ACCESS_TTL_SECONDS` (default 15 min).

The signing secret is unchanged (`config.settings.jarvis_secret_key`),
so legacy tokens issued before the flag flip remain valid until their own
`exp` — no force-logout when you enable v2.

### Refresh token

A 32-byte opaque random string, urlsafe-base64 encoded.

**Not** a JWT: refresh tokens are higher-value than access tokens, and
revealing claims via base64 has no upside (the server has to look it up
in Redis to rotate it anyway). The opaque shape also means a leaked
refresh token cannot be partially trusted.

Server-side storage in Redis (key: `jarvis:jwt:refresh:<token>`):

```
sub|role|family_id|parent_access_jti
```

with TTL = `JWT_REFRESH_TTL_SECONDS` (default 30 days).

### Rotation flow

```
POST /auth/refresh
  body: { "refresh_token": "..." }     # or X-Refresh-Token header

  → 200 { access_token, refresh_token,
          token_type: "bearer",
          expires_in, refresh_expires_in }
```

Single use: the old refresh token is moved into a short-lived
`refresh_used` set (1 hour TTL) and a fresh pair is issued tied to the
same `family_id`.

### Replay detection

If a refresh token presented to `/auth/refresh` is in the
`refresh_used` set, that token has already been consumed — somebody is
replaying a stolen value. We:

1. Look up the `family_id` from the used entry.
2. Delete every live refresh token belonging to that family (`SMEMBERS`
   of `jarvis:jwt:family:<family_id>` followed by `DEL`).
3. Return `401 refresh_token_replay_detected` to **both** the attacker
   and the legitimate user. The legitimate user re-logs in normally;
   the attacker has no path forward.

This is the standard refresh-token-rotation pattern (OWASP, draft-ietf-
oauth-security-topics §4.13).

### Revocation lists

- `jarvis:jwt:revoked:<jti>` — `SETEX 1` with TTL = remaining access
  token lifetime. Written on logout. The verify path checks this set on
  every request and short-circuits on hit.
- `jarvis:jwt:family:<family_id>` — `SET` of all refresh tokens issued
  in a chain. Used for wholesale revocation on replay.

Self-cleaning: every key carries a TTL so the Redis footprint stays
bounded by the configured refresh TTL.

## Feature flag and configuration

| Variable | Default | Purpose |
|---|---|---|
| `JARVIS_JWT_HARDENING_V2` | `0` | Master kill-switch. Off = legacy behavior, on = v2. |
| `JWT_ACCESS_TTL_SECONDS` | `900` | Access token TTL. 15 min is the sweet spot for SPA flows. |
| `JWT_REFRESH_TTL_SECONDS` | `2592000` | Refresh token TTL. 30 days matches the legacy total session length. |
| `JWT_REDIS_PREFIX` | `jarvis:jwt:` | Prefix for all Redis keys. Change to namespace per environment. |
| `REDIS_URL` | `redis://localhost:6379/0` | Where to find Redis. Already used elsewhere. |

The flag reader is `api.jwt_v2.is_v2_enabled()` — case-insensitive
("1", "true", "yes", "on"). Anything else (including unset) = off.

## Rollout plan

### Phase 0 — landed (now)

- Module `api/jwt_v2.py` and tests `tests/test_jwt_v2.py`,
  `tests/test_auth_routes_v2_flag.py` (38 tests). Flag defaults off.
- `/auth/token` and `/auth/refresh` and `/auth/logout` wired to branch
  on the flag.
- Legacy code path unchanged.

### Phase 1 — staging enable

1. Set `JARVIS_JWT_HARDENING_V2=1` on staging.
2. Verify the staging frontend can log in, refresh, and log out.
3. Watch logs for `jwt_v2_family_revoked` (replay detections) and
   `jwt_v2_revocation_check_failed` (Redis health).
4. Run an explicit logout flow and confirm a subsequent request with the
   same access token returns 401.

### Phase 2 — frontend prep (only once Phase 1 is green)

Frontends must adopt the refresh flow:

- Store `refresh_token` securely (HttpOnly cookie preferred — adding a
  second cookie `jarvis_refresh` is a 5-line change). Avoid
  `localStorage`.
- On any 401 from an authenticated endpoint, **retry once** after calling
  `/auth/refresh`. Drop the user to the login screen if that 401s too.
- Implement a background refresh ~1 minute before `expires_in` so calls
  rarely see a 401.

### Phase 3 — production enable

Same as Phase 1 but in prod. Keep the flag config ready to flip back
off if anything breaks — every Phase-1 code path still works under the
flag-off rollback.

### Phase 4 — legacy retirement (not in this PR)

Once metrics show 100% of issued tokens are v2 (e.g. 35 days after
Phase 3 — longer than the longest legacy `exp`), remove the legacy
branch from `api/routes/auth.py`. The legacy `create_access_token`
helper in `api/auth.py` can also be retired.

## Operational notes

- **Redis down:** access token verification falls back to "no revocation
  check possible" with a WARNING log. The signature and expiry checks
  still apply. Refresh and rotation fail closed (the user must re-login).
  This is intentional — failing closed everywhere would brick the API
  during a Redis outage.
- **Multiple workers:** Redis is the single source of truth for the
  revocation list and the refresh-token store, so there's no race between
  workers.
- **Clock skew:** TTLs are wall-clock based. Same constraint as the
  legacy path; no new sensitivity.

## Test surface

- `tests/test_jwt_v2.py` (30 tests) — pure module unit tests with an
  in-memory fake Redis (no real Redis needed in CI):
  - flag values, claim shape, signature/expiry validation, jti
    revocation, rotation, replay detection, family revocation, Redis
    outage fallback.
- `tests/test_auth_routes_v2_flag.py` (8 tests) — end-to-end with a
  FastAPI `TestClient` under both flag states:
  - flag off returns single token; flag on returns pair; refresh
    rotates; replay returns 401; logout revokes jti; legacy refresh path
    untouched when flag is off.

## Known gaps

**Closed in follow-up commits (after the original prep):**

- ✅ Legacy `verify_token` in `api/auth.py` now consults the v2
  revocation list when the JWT carries a `jti` and the flag is on.
  Closed in `tests/test_legacy_verify_token_revokes_v2.py` (4 tests
  covering: accept-not-revoked, reject-after-revoke, ignore-when-flag-off,
  legacy-token-without-jti-still-works).
- ✅ Three Prometheus counters wired:
  - `jarvis_jwt_v2_pairs_issued_total{origin="login"|"rotation"}`
  - `jarvis_jwt_v2_rotations_total{outcome="ok"|"replay"|"unknown"}`
  - `jarvis_jwt_v2_revocations_total{kind="access"|"refresh"|"family"}`
  Visible on `/metrics`. Coverage: `tests/test_jwt_v2_metrics.py`
  (10 tests).

**Still deferred (intentional, scoped):**

- HttpOnly cookie for the refresh token is not implemented; the current
  contract returns it in the body. Frontend currently has to handle the
  storage. Tracked for Phase 2.
