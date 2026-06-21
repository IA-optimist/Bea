# Frontend / Client Surfaces — Béa

> Last verified: **2026-06-21**. Maintained by whoever modifies a surface.
> This document is the authoritative registry of all client-facing interfaces.

---

## Surface Inventory

| Surface | Path | Status | Primary API version | v1 calls |
|---------|------|--------|---------------------|----------|
| `static/app.html` | `static/app.html` | **CANONICAL** | v3 (some v2) | none |
| `static/cockpit.html` | `static/cockpit.html` | **CANONICAL** | v2/v3 | none |
| Flutter mobile | `beamax_app/` | **SUPPORTED** | v3 (3 v1 pending) | 3 — see below |
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

#### Active v1 calls (allowlisted, do not add more)

| Method | Path | Source file:line | v3 target | Status |
|--------|------|------------------|-----------|--------|
| `POST` | `/api/v1/missions/{id}/pause` | `api_service.dart:550` | `/api/v3/missions/{id}/pause` | ✅ v3 endpoint shipped (PR #90) — APK rebuild pending |
| `POST` | `/api/v1/missions/{id}/resume` | `api_service.dart:559` | `/api/v3/missions/{id}/resume` | ✅ v3 endpoint shipped (PR #90) — APK rebuild pending |
| `GET` | `/api/v1/missions/{id}/stream` | `api_service.dart:753` | `/api/v3/missions/{id}/stream` | ✅ v3 endpoint shipped (PR #90) — APK rebuild pending |

**These three calls are the only authorized v1 calls across all client surfaces.**
Each has a `TODO(v3-migration)` comment in the source pointing to this document.

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

**Server-side v3 endpoints are now all shipped (PR #90, 2026-06-21).**
The remaining work is purely client-side (APK rebuild). **Migration sequence** (in order):

1. **✅ Ship v3 streaming endpoint** — `GET /api/v3/missions/{id}/stream` now in
   `api/routes/convergence.py`. SSE format identical to v1 — delegates to the same
   `_sse_generator`. Flutter change: one-line URL update in `api_service.dart:753`.

2. **✅ Ship v3 pause/resume** — `POST /api/v3/missions/{id}/pause` +
   `/resume` now in `api/routes/convergence.py`. Flutter change: two-line URL update
   in `api_service.dart:550,559`.

3. **TODO — Flutter APK rebuild** (unblocked):
   - Update 3 URLs in `beamax_app/lib/services/api_service.dart` (`TODO(v3-migration)` markers)
   - `flutter build apk --release --no-tree-shake-icons` from a copy in `C:\bea_app`
   - Distribute APK

3. **Remove v1 endpoints** (after APK adoption):
   - Remove `POST /missions/{id}/pause`, `/resume`, `GET /missions/{id}/stream` from `mission_control.py`
   - Remove `GET /api/v1/health`, `/missions/{id}/log`, `/system/status` (no active callers)
   - If `mission_control.py` becomes empty, remove the file entirely

**Sunset deadline: 2026-10-01** (hard date — `Sunset` header already set in V1DeprecationMiddleware).

---

## API Version Authorization per Surface

| Surface | v1 allowed | v2 allowed | v3 allowed |
|---------|-----------|-----------|-----------|
| `static/app.html` | no | auth only | yes |
| `static/cockpit.html` | no | yes | yes |
| `beamax_app/` | **allowlist only** (3 endpoints) | yes | yes |
| `frontend/` | no | yes | yes |
| `orchestrate-cli/` | no | no | yes |
| New surfaces | **never** | no | yes |
