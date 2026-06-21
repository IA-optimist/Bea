# Frontend / Client Surfaces — Béa

> Last verified: **2026-06-21**. Maintained by whoever modifies a surface.
> This document is the authoritative registry of all client-facing interfaces.

---

## Surface Inventory

| Surface | Path | Status | Primary API version | v1 calls |
|---------|------|--------|---------------------|----------|
| `static/app.html` | `static/app.html` | **CANONICAL** | v3 (some v2) | none |
| `static/cockpit.html` | `static/cockpit.html` | **CANONICAL** | v2/v3 | none |
| Flutter mobile | `beamax_app/` | **SUPPORTED** | v3 ✅ (migration done PR #91) | 0 — APK rebuild pending |
| React frontend | `frontend/` | **EXPERIMENTAL** | v2/v3 | none |
| `orchestrate-cli/` | `orchestrate-cli/` | **SUPPORTED** | Python CLI (no HTTP) | N/A |
| `mobile/` | — | **ABSENT** | — | — |
| `orchestrate-mobile/` | — | **ABSENT** | — | — |

### Status definitions

| Status | Meaning |
|--------|---------|
| **CANONICAL** | Official, maintained, production-serving |
| **SUPPORTED** | Actively used, some tech debt, supported |
| **EXPERIMENTAL** | Works, not production primary, may change |
| **ABSENT** | Directory does not exist |
| **ARCHIVED_CANDIDATE** | Unused, should be deleted in a cleanup PR |

---

## Surface Details

### `static/app.html` — CANONICAL (admin cockpit)

Single-file HTML+JS admin dashboard served at `/app.html`.

- **Purpose**: Admin-only ops panel (mission submit, approve, system health, modules)
- **Auth**: `X-Bea-Token` header or Bearer token
- **API usage**: v3 for all operations, v2 for auth (`/api/v2/auth/login`, `/api/v2/auth/logout`) and capabilities
- **v1 calls**: none
- **Modification rule**: Keep it as a minimal cockpit. Do not add complex JS frameworks. Changes must preserve the single-file constraint.

### `static/cockpit.html` — CANONICAL (secondary admin view)

Secondary admin view also served from `static/`.

- **Purpose**: Dashboard for missions, agents, security tools, business metrics
- **Auth**: Bearer token
- **API usage**: v2/v3 (comments show endpoint paths inline)
- **v1 calls**: none
- **Modification rule**: Same as `app.html` — minimal, single-file.

### `beamax_app/` — SUPPORTED (canonical mobile client)

Flutter app targeting Android. Current APK at `C:\Users\Desktop\Bea_app.apk`, rebuilt 2026-06-07, reachable over Tailscale.

- **Purpose**: Mobile control panel for Béa — missions, agents, business, security, autonomy decisions
- **Auth**: Bearer JWT (`HardcodedConfig.apiToken` or acquired via login)
- **API usage**: Primarily v3, v2 for agents/abort, **v1 for 3 endpoints (see below)**
- **Key files**: `beamax_app/lib/services/api_service.dart`, `beamax_app/lib/screens/`
- **Build**: `flutter build apk --release --no-tree-shake-icons` (from `C:\bea_app` — accent-free path)
- **Modification rule**: Changes to API calls require rebuilding and redistributing the APK.

#### Active v1 calls — NONE ✅ (migration complete, PR #91, 2026-06-21)

All three former v1 calls have been migrated to v3 in `api_service.dart`.
The v1 allowlist in `tests/test_client_v1_allowlist.py` is now empty.
APK rebuild required to ship the migration to the device.

| Method | Path | Old v1 URL | Migrated to v3 |
|--------|------|------------|----------------|
| `POST` | pause | `/api/v1/missions/{id}/pause` | ✅ `/api/v3/missions/{id}/pause` |
| `POST` | resume | `/api/v1/missions/{id}/resume` | ✅ `/api/v3/missions/{id}/resume` |
| `GET` | stream | `/api/v1/missions/{id}/stream` | ✅ `/api/v3/missions/{id}/stream` |

**Next step**: rebuild APK (`flutter build apk --release --no-tree-shake-icons` from `C:\bea_app`) and distribute. Once the APK ships, the v1 endpoints in `mission_control.py` can be removed.

### `frontend/` — EXPERIMENTAL (React business dashboard)

React + TypeScript + Vite frontend focused on business intelligence.

- **Purpose**: Opportunities, products, MCP management, self-improvement status
- **Auth**: Bearer token via Axios interceptor
- **API usage**: v3 for business/MCP, v2 for missions/skills/self-improvement
- **v1 calls**: none
- **Build**: `npm run build` (Dockerfile in `frontend/`)
- **Status**: Works locally, not deployed as primary surface. Serves as v3 API reference implementation.
- **Modification rule**: Extend v3 only. Do not introduce new v2 calls.

### `orchestrate-cli/` — SUPPORTED (Python CLI tool)

Python CLI for orchestrating Béa missions from the command line.

- **Purpose**: Developer/ops CLI — not a browser client
- **API usage**: HTTP to `api/v3/missions` and related endpoints (see `orchestrate-cli/src/`)
- **v1 calls**: needs verification (see `tests/test_client_v1_allowlist.py`)
- **Modification rule**: Extend v3 only. No new v2 or v1 calls.

---

## Rules for Adding a New Client Interface

1. **Use v3 endpoints only** — `/api/v3/*` for all new functionality.
2. **Never introduce new `/api/v1/*` calls.** The allowlist in `tests/test_client_v1_allowlist.py` will fail CI.
3. **Avoid new `/api/v2/*` calls** unless the resource genuinely doesn't exist in v3.
4. **Document it here** before shipping — add a row to the Surface Inventory table.
5. **Auth**: use `Authorization: Bearer <token>` or `X-Bea-Token` header. Do not hard-code tokens.
6. **Single binary constraint for Flutter**: any API change requires an APK rebuild and redistribution.

---

## v1 Sunset Plan

**Migration sequence** (all server-side work complete):

1. **✅ Ship v3 streaming endpoint** — `GET /api/v3/missions/{id}/stream` shipped in PR #90.

2. **✅ Ship v3 pause/resume** — `POST /api/v3/missions/{id}/pause` + `/resume` shipped in PR #90.

3. **✅ Flutter code migrated** (PR #91, 2026-06-21):
   - 3 URLs updated in `api_service.dart` — `pauseMission`, `resumeMission`, `streamMissionLogs`
   - `_V1_ALLOWLIST` emptied — CI fails on any new v1 client call
   - `scripts/check_client_v1_usage.py` confirms 0 v1 runtime calls

4. **✅ APK rebuilt** (PR #94, 2026-06-21):
   - `C:\bea_app\lib\services\api_service.dart` synced to v3
   - `flutter build apk --release --no-tree-shake-icons` → `app-release.apk` 23.0 MB
   - Stale v1 doc comment in `streamMissionLogs` removed

5. **TODO — Install and validate on device**:
   - Transfer APK to Android device (sideload or `adb install`)
   - Login, submit a mission, use pause/resume/stream
   - Check server logs: confirm all calls go to `/api/v3/`, zero to `/api/v1/`
   - Checklist: see below

6. **TODO — Remove v1 server-side endpoints** (after step 5):
   - Remove `POST /missions/{id}/pause`, `/resume`, `GET /missions/{id}/stream` from `api/routes/mission_control.py`
   - Remove `GET /api/v1/health`, `/missions/{id}/log`, `/system/status` (no known callers)
   - If `mission_control.py` becomes empty, remove the file entirely

**Sunset deadline: 2026-10-01** (hard date — `Sunset` header already set in V1DeprecationMiddleware).

### Device validation checklist (manual — after APK install)

```
[ ] APK installed without errors (sideload or adb install)
[ ] App starts, login/auto-login works
[ ] Submit a mission — appears in mission list
[ ] Pause a running mission:
    - Tap Pause in the app
    - Server log shows: POST /api/v3/missions/{id}/pause (NOT /api/v1/)
[ ] Resume the mission:
    - Tap Resume in the app
    - Server log shows: POST /api/v3/missions/{id}/resume (NOT /api/v1/)
[ ] View mission stream:
    - Open mission detail with live stream
    - Server log shows: GET /api/v3/missions/{id}/stream (NOT /api/v1/)
[ ] Verify zero /api/v1/ calls in server access log during the session
[ ] DONE — v1 endpoints can now be removed
```

---

## API Version Authorization per Surface

| Surface | v1 allowed | v2 allowed | v3 allowed |
|---------|-----------|-----------|-----------|
| `static/app.html` | no | auth only | yes |
| `static/cockpit.html` | no | yes | yes |
| `beamax_app/` | **none** (migration complete PR #91) | yes | yes |
| `frontend/` | no | yes | yes |
| `orchestrate-cli/` | no | no | yes |
| New surfaces | **never** | no | yes |
