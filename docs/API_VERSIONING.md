# API Versioning — v1, v2, v3

## Current State (2026-04-21)

The JarvisMax API exposes endpoints across three coexisting versions.
This doc maps them out, explains the coexistence rationale, and tracks
deprecation roadmap.

## Counts (after audit phase-11, 2026-04-25)

| Version | Routers | Status         | Notes |
|---------|---------|----------------|-------|
| v1      | 1       | **deprecated, sunset 2026-10-01** | Mission control only — kept while Flutter app migrates `/api/v1/missions/{id}/stream` to a v3 SSE equivalent |
| v2      | 8       | stable         | Core mission / auth / agents surface |
| v3      | 35      | **preferred**  | Modern surface — cognition, business, observability, extensions |

### v1 sunset progress

- **2026-04-25** — `V1DeprecationMiddleware` added : every `/api/v1/*` response
  now carries `Deprecation: true` + `Sunset: 2026-10-01T00:00:00Z` per RFC 8594,
  and emits a `api.v1.deprecated_call` structlog warning so Grafana can track
  residual traffic.
- **2026-04-25** — 7 v1 endpoints removed (zero static callers, v2 equivalents
  existed) :
  - `POST /api/v1/missions/{id}/approve` → `/api/v2/missions/{id}/approve`
  - `POST /api/v1/missions/{id}/reject` → `/api/v2/missions/{id}/reject`
  - `POST /api/v1/missions/{id}/cancel` → `/api/v2/missions/{id}/abort`
  - `POST /api/v1/mission/run` → `/api/v2/missions/submit`
  - `GET /api/v1/missions/{id}/summary` → `/api/v2/missions/{id}`
  - `GET /api/v1/trace/{id}` (no callers)
  - `GET /api/v1/trace/mission/{id}` (no callers)
- **TODO** — ship `/api/v3/missions/{id}/stream` (SSE) and migrate
  `jarvismax_app/lib/services/api_service.dart:677` to it. Once mobile rollout
  is at 100%, remove the last v1 endpoints.

## v1 endpoints (DEPRECATED — do not add new ones)

Remaining endpoints in `api/routes/mission_control.py` (sunset 2026-10-01) :

| Endpoint | Migration target | Notes |
|---|---|---|
| `GET /api/v1/health` | `GET /api/health` | redundant ; remove after telemetry confirms 0 traffic |
| `GET /api/v1/missions` | `GET /api/v2/missions` | redundant |
| `GET /api/v1/missions/{id}/log` | none yet | needs `/api/v3/missions/{id}/log` |
| `GET /api/v1/system/status` | `GET /api/v2/status` or `/api/v3/system/readiness` | redundant |
| `POST /api/v1/missions/{id}/pause` | none yet | needs `/api/v3/missions/{id}/pause` (kill if unused) |
| `POST /api/v1/missions/{id}/resume` | none yet | needs `/api/v3/missions/{id}/resume` (kill if unused) |
| `GET /api/v1/missions/{id}/stream` | none yet | **load-bearing** — used by Flutter mobile app |

**Sunset plan** : every response carries `Deprecation: true` + `Sunset: 2026-10-01`
headers. Concrete removal target : when Grafana shows
`sum(rate(api_requests_total{version="v1"}[7d])) == 0` AND the Flutter app has
shipped a release using `/api/v3/missions/{id}/stream` (TODO).

## v2 endpoints (STABLE)

Primary product surface. Do NOT add new resource types here ; extend v3 instead.

| Router                        | File                                       |
|-------------------------------|--------------------------------------------|
| `/api/v2/agents`              | api/routes/agent_builder.py                |
| `/api/v2/auth/*`              | api/main.py                                |
| `/api/v2/browser`             | api/routes/browser.py                      |
| `/api/v2/health`              | api/main.py                                |
| `/api/v2/learning`            | api/routes/learning.py                     |
| `/api/v2/missions` / `/task`  | api/main.py + api/routes/missions.py       |
| `/api/v2/multimodal`          | api/routes/multimodal.py                   |
| `/api/v2/objectives`          | api/routes/objectives.py                   |

**Stability contract** : breaking changes require a MAJOR release bump.
Additive changes (new fields, new endpoints) are allowed.

## v3 endpoints (PREFERRED — where new work lands)

Newer surface covering cognition, business automation, extensions. Design
principles :

1. **Resource-oriented** : nouns, not verbs (`/api/v3/missions/{id}/replay`
   instead of `/api/v3/replayMission`)
2. **Consistent auth** : `Depends(require_auth)` on every router
3. **Typed contracts** : Pydantic v2 models, no untyped dicts
4. **Error envelope** : `{"error": "...", "detail": {...}}` with HTTP code

Routers (35 total, see `grep -rn 'prefix="/api/v3' api/` for the live list).

## Cross-version rules

- **Auth headers** : same `Authorization: Bearer` / `X-Jarvis-Token` / cookie
  across all versions. The auth dependency (`api._deps._check_auth`) is
  version-agnostic.
- **Rate limiting** : applied uniformly to `/api/*` at middleware level.
- **CORS** : same origin list for all versions.
- **Observability** : every route emits `api.request` structlog events with
  `version` tag (add if missing).

## Audit findings (2026-04-21)

Issues to address in follow-up PRs :

1. **Duplicate `/api/v3/connectors`** : `api/routes/connectors.py` declares
   `prefix="/api/v3/connectors"` while `api/routes/modules_v3.py` uses bare
   `prefix="/api/v3"` with a `/connectors` subroute — mount order matters
   and is fragile. Fix : force modules_v3 to avoid shadow, or merge.

2. **`/api/v3` bare-prefix routers** are dangerous for shadowing
   (modules_v3.py, chat.py, convergence.py). Prefer explicit sub-prefixes.

3. **v1 mission-control** : still alive, 3 routers. Audit actual callers
   (mobile app build + ops scripts) before sunset.

4. **No `Deprecation` header** on v1 responses. Add
   `response.headers["Deprecation"] = "true"` + `Sunset` date.

5. **No OpenAPI version tag** : `/docs` shows all three versions mixed.
   Consider 3 separate schemas (`/docs/v2`, `/docs/v3`) or tag grouping.

## Action items

- [ ] Add `Deprecation: true` + `Sunset: 2026-10-01` headers to all v1 routes
- [ ] Remove shadowing between `modules_v3.py` and resource-specific v3 routers
- [ ] Count v1 callers in Grafana : `sum(rate(api_requests_total{version="v1"}[7d]))` — when near zero, schedule removal
- [ ] Add `version` label to all `api.request` structlog events
- [ ] Migrate mobile app calls from v1 → v2/v3 (Flutter `api_client.dart`)
