# JarvisMax API Reference

> Generated from `api/main.py` and `api/routes/*.py` at SHA `889a1c3`.
> **548 endpoints** across **53 router files** + **8 inline routes** in `main.py`.

---

## Base URL

- Local: `http://localhost:8000`
- Docker: `http://localhost:8000` (mapped from container)

## Authentication

All routes (except those listed in **Public paths** below) require authentication:

```bash
# JWT (issued by /auth/token)
curl -H "Authorization: Bearer <jwt-token>" http://localhost:8000/api/v3/missions

# Static API token
curl -H "X-Jarvis-Token: <jarvis-api-token>" http://localhost:8000/api/v3/missions

# Access token (jv-* prefix)
curl -H "Authorization: Bearer jv-xxxx-yyyy" http://localhost:8000/api/v3/missions
```

### Public paths (no auth required)

- `GET /` (redirects to `/app.html`)
- `GET /app.html` (web SPA)
- `GET /health`
- `GET /api/v2/health`
- `GET /api/v3/system/readiness` (Docker healthcheck)
- `POST /auth/login`
- `POST /auth/token`
- `GET /docs` (OpenAPI Swagger, only if `ENABLE_API_DOCS=1`)
- `GET /openapi.json`
- `GET /redoc`
- Static asset extensions: `.css`, `.js`, `.png`, `.ico`, `.svg`, `.woff2`

---

## Inline routes (defined in `api/main.py`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | Public | Redirects to `/app.html` |
| GET | `/api/v2/session` | `Depends(require_auth)` | Returns current user session info (role, username) |
| POST | `/auth/token` | Public | Login with username/password (OAuth2 form) → JWT |
| POST | `/auth/login` | Public | Alias for `/auth/token` |
| GET | `/auth/me` | Manual `require_auth` | Current user info |
| POST | `/auth/refresh` | Manual token verify | Refresh JWT |
| WebSocket | `/ws/stream` | Validated by `ws_handler` before `accept()` | Real-time mission events |
| GET | `/api/v3/system/registry` | `Depends(require_auth)` | Router registry status |

---

## Authentication

### POST `/auth/token`

Login with admin credentials. Returns a JWT.

**Request** (form-data):
```
username=admin
password=<JARVIS_ADMIN_PASSWORD>
```

**Response**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

### GET `/auth/me`

**Headers**: `Authorization: Bearer <jwt>`

**Response**:
```json
{
  "ok": true,
  "user": {
    "username": "admin",
    "role": "admin",
    "auth_type": "jwt"
  }
}
```

### POST `/auth/refresh`

**Headers**: `Authorization: Bearer <jwt>` (must be valid)

**Response**: New JWT.

---

## Mission lifecycle (canonical v3)

### POST `/api/v3/missions`

Submit a new mission.

**Request body**:
```json
{
  "goal": "Analyze the latest GitHub PR for security issues",
  "mode": "auto",
  "metadata": {
    "task_type": "code",
    "risk_level": "low"
  }
}
```

**Response**:
```json
{
  "mission_id": "msn_abc123",
  "status": "CREATED",
  "created_at": "2026-04-08T14:30:00Z"
}
```

### GET `/api/v3/missions`

List missions.

**Query params**:
- `limit` (default 100)
- `status` — filter by status
- `intent` — filter by intent

### GET `/api/v3/missions/{mission_id}`

Get a single mission.

**Response**: Full `MissionContext` with status, plan, agents used, results, trace.

### POST `/api/v3/missions/{mission_id}/approve`

Approve a mission pending validation. Re-runs with `force_approved=True`.

**Request body** (optional):
```json
{
  "note": "Approved by reviewer"
}
```

### POST `/api/v3/missions/{mission_id}/reject`

Reject a pending mission.

### Mission statuses

| Status | Description |
|--------|-------------|
| `CREATED` | Mission accepted, awaiting orchestration |
| `PLANNED` | Plan generated |
| `RUNNING` | Currently executing |
| `REVIEW` | Awaiting evaluation |
| `PENDING_VALIDATION` | Awaiting human approval |
| `AWAITING_APPROVAL` | (alias) |
| `DONE` | Successfully completed |
| `FAILED` | Failed or rejected |

---

## System status & health

### GET `/health`
Public. Returns `{"status": "ok"}`.

### GET `/api/v2/health`
Public. Returns full system health.

### GET `/api/v3/system/readiness`
Public. Used by Docker healthcheck. Returns:
```json
{
  "ok": true,
  "ready": true,
  "status": "ready",
  "probes": {
    "llm_key": true,
    "qdrant": true,
    "orchestrator": true
  }
}
```

Returns 503 if any probe fails.

### GET `/api/v2/status`
**Auth required**. Returns system overview (uptime, mission counts, agent registry, capabilities).

### GET `/api/v3/system/registry`
**Auth required**. Returns status of all 55 mounted routers.

---

## Modules management (admin)

### Agents

- `GET /api/v3/agents` — List agents
- `POST /api/v3/agents` — Create agent
- `PUT /api/v3/agents/{agent_id}` — Update agent
- `DELETE /api/v3/agents/{agent_id}` — Delete agent
- `POST /api/v3/agents/{agent_id}/test` — Test agent
- `POST /api/v3/agents/{agent_id}/toggle` — Enable/disable
- `POST /api/v3/agents/{agent_id}/duplicate` — Clone agent

### Skills

- `GET /api/v3/skills` — List skills
- `POST /api/v3/skills` — Create skill
- `PUT /api/v3/skills/{skill_id}` — Update skill
- `DELETE /api/v3/skills/{skill_id}` — Delete skill
- `POST /api/v3/skills/{skill_id}/test` — Test skill
- `POST /api/v3/skills/{skill_id}/toggle` — Enable/disable

### Connectors

- `GET /api/v3/connectors` — List connectors
- `POST /api/v3/connectors` — Create connector
- `DELETE /api/v3/connectors/{connector_id}` — Delete

### MCP servers

- `GET /api/v3/mcp` — List MCP servers
- `GET /api/v3/mcp/servers` — Detailed list
- `GET /api/v3/mcp/stats` — MCP statistics

### Health overview

- `GET /api/v3/modules/health` — Aggregate health for agents/skills/connectors/MCP

All `/api/v3/modules/*` and `/api/v3/{agents,skills,connectors,mcp}/*` routes are protected by **router-level `Depends(require_auth)`**.

---

## Vault (secrets management)

All `/vault/*` routes require auth (router-level).

- `POST /vault/unlock` — Unlock vault with master password
- `POST /vault/lock` — Lock vault
- `GET /vault/status` — Vault status
- `POST /vault/create` — Create new secret
- `POST /vault/update` — Update/rotate secret value
- `POST /vault/use` — Use secret (agent injection)
- `POST /vault/reveal` — Reveal plaintext (admin only)
- `POST /vault/delete` — Delete secret
- `GET /vault/list` — List secret metadata
- `GET /vault/logs` — Audit logs

---

## Identity management

All `/identity/*` routes require auth.

- `POST /identity/create` — Create identity (template-driven)
- `POST /identity/link` — Link identity to service/domain
- `POST /identity/use` — Retrieve credentials via vault
- `POST /identity/revoke` — Revoke identity
- `POST /identity/rotate` — Rotate secret
- `POST /identity/delete` — Delete identity
- `GET /identity/list` — List identities
- `GET /identity/graph` — Identity relationship graph
- `GET /identity/logs` — Audit logs
- `GET /identity/templates` — Available provider templates

---

## Tokens (admin)

`/api/v3/tokens/*` — Admin-only.

- `POST /api/v3/tokens` — Create access token (returns `jv-*` token)
- `GET /api/v3/tokens` — List tokens
- `DELETE /api/v3/tokens/{token_id}` — Revoke token
- `POST /api/v3/tokens/{token_id}/disable` — Disable
- `POST /api/v3/tokens/{token_id}/enable` — Re-enable

---

## Self-improvement

- `GET /api/v2/self-improvement/status` — Loop status (viewer role)
- `GET /api/v2/self-improvement/suggestions` — Pending suggestions
- `POST /api/v2/self-improvement/run` — Trigger cycle (admin)
- `POST /api/v2/self-improvement/approve` — Approve a candidate
- `POST /api/v2/self-improvement/reject` — Reject a candidate

RBAC: `viewer` can read, `admin` can trigger.

---

## Cognitive features

### Cognitive events
- `GET /api/v3/cognitive-events/journal` — Journal
- `GET /api/v3/cognitive-events/recent` — Recent events
- `GET /api/v3/cognitive-events/lab` — Lab events
- `GET /api/v3/cognitive-events/degraded` — Degraded events

### Capability routing
- `GET /api/v3/capability-routing/capabilities` — List capabilities
- `POST /api/v3/capability-routing/resolve` — Resolve capability for goal
- `POST /api/v3/capability-routing/route` — Route goal to capability
- `POST /api/v3/capability-routing/refresh` — Refresh registry
- `GET /api/v3/capability-routing/history` — Routing history
- `GET /api/v3/capability-routing/provider-stats` — Provider statistics
- `GET /api/v3/capability-routing/summary` — Summary

### Reasoning trace
- `GET /api/v3/trace/{mission_id}` — Mission decision trace

---

## Business endpoints

### Finance (gated by `ENABLE_STUB_ROUTES=true`)

All `/api/v3/finance/*` routes require auth (router-level).

- `GET /api/v3/finance/products` — List Stripe products
- `POST /api/v3/finance/product` — Create product
- `POST /api/v3/finance/price` — Create price
- `POST /api/v3/finance/payment_link` — Generate payment link
- `GET /api/v3/finance/customers` — List customers
- `POST /api/v3/finance/customer` — Create customer
- `GET /api/v3/finance/subscriptions` — List subscriptions
- `POST /api/v3/finance/subscription` — Create subscription
- `POST /api/v3/finance/invoice` — Create draft invoice
- `GET /api/v3/finance/revenue_summary` — MRR/ARR
- `GET /api/v3/finance/pl` — Profit/loss
- `GET /api/v3/finance/pending` — Pending approvals
- `POST /api/v3/finance/approve` — Approve action
- `POST /api/v3/finance/deny` — Deny action
- `GET /api/v3/finance/audit` — Audit log

### Stripe webhook (separate router, no JWT)

- `POST /finance/webhook/stripe` — Stripe events. Auth via signature verification (`STRIPE_WEBHOOK_SECRET`).

### Other business routes

- `GET /api/v3/economic/stats` — Economic statistics
- `GET /api/v3/economic/recommendations` — Recommendations
- `GET /api/v3/economic/chains` — Decision chains
- `POST /api/v3/business/scan_opportunities` — Scan business opportunities (via mission handler)

---

## Tool & action execution

### Action console
- `GET /api/v3/actions/console` — Recent actions
- `POST /api/v3/actions/execute` — Execute action

### Plan runner
- `POST /api/v3/plans/run` — Execute plan
- `GET /api/v3/plans/runs/{run_id}` — Run status
- `POST /api/v3/plans/runs/{run_id}/resume` — Resume
- `POST /api/v3/plans/runs/{run_id}/cancel` — Cancel

### Approval queue
- `GET /api/v3/approval/queue` — Pending approvals
- `POST /api/v3/approval/{item_id}/approve` — Approve
- `POST /api/v3/approval/{item_id}/reject` — Reject

---

## Multimodal (stubs)

- `POST /api/v2/multimodal/image/generate` — Image generation
- `POST /api/v2/multimodal/image/describe` — Vision (describe)
- `POST /api/v2/multimodal/voice/stt` — Speech to text
- `POST /api/v2/multimodal/voice/tts` — Text to speech
- `GET /api/v2/multimodal/capabilities` — Available providers

---

## Browser & voice (gated by `ENABLE_STUB_ROUTES=true`)

- `POST /api/v2/browser/navigate`
- `POST /api/v2/browser/screenshot`
- `POST /api/v2/voice/stt`
- `POST /api/v2/voice/tts`

---

## Metrics & observability

- `GET /api/v3/metrics/summary` — System overview (auth required)
- `GET /api/v3/metrics/routing` — Routing metrics
- `GET /api/v3/metrics/tools` — Tool usage
- `GET /api/v3/metrics/improvement` — Self-improvement metrics
- `GET /api/v3/metrics/failures` — Failure analysis

---

## WebSocket

### `/ws/stream`

Real-time mission events. Token validated **before** `accept()`.

**Connect**:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/stream');
ws.send(JSON.stringify({type: 'auth', token: '<jwt>'}));
```

Or via header (for non-browser clients):
```
X-Jarvis-Token: <token>
```
or
```
Authorization: Bearer <jwt>
```

**Event types received**:
- `system` — `reconnected`, `auth_expired`
- `mission_update` — Mission state change
- `mission_done`, `mission_failed`
- `task_progress`
- `agent_thinking`
- `token_stream`
- `action_pending`, `action_approved`, `action_rejected`

---

## Rate limiting

Enforced by `RateLimitMiddleware`:

| Path pattern | Limit |
|--------------|-------|
| `/auth/*` | 10 req/min |
| `/api/v2/*` | 60 req/min |
| `/api/v3/*` | 60 req/min |
| `/health`, `/api/v3/system/readiness` | 120 req/min (exempt-ish) |

Returns `429 Too Many Requests` with `Retry-After` header. Per IP+path sliding window.

---

## Error response format

```json
{
  "error": "Authentication required",
  "code": 401,
  "support": "Please contact support or renew your access."
}
```

| Status | Meaning |
|--------|---------|
| 200 | OK |
| 400 | Bad request |
| 401 | Authentication required |
| 403 | Forbidden / expired / revoked |
| 404 | Not found |
| 429 | Rate limit exceeded |
| 500 | Internal error |
| 503 | Service unavailable (readiness probe failed) |

---

## Environment variables

See [QUICKSTART.md](QUICKSTART.md) for the full list. Critical ones:

| Variable | Purpose | Required |
|----------|---------|----------|
| `JARVIS_SECRET_KEY` | JWT signing | YES (production) |
| `JARVIS_ADMIN_PASSWORD` | Admin login | YES (production) |
| `JARVIS_API_TOKEN` | Static API token | YES (production) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | LLM provider | At least one |
| `QDRANT_HOST`, `QDRANT_PORT` | Vector store | YES |
| `POSTGRES_*` | Database (optional, falls back to SQLite) | NO |
| `JARVIS_PRODUCTION` | Hard-fail on insecure config | Recommended |
| `ENABLE_STUB_ROUTES` | Mount finance/browser/voice routes | NO |
| `CORS_ORIGINS` | Comma-separated allowed origins | NO |

---

## Router count

**56 routers mounted** in `api/main.py` (53 in `api/routes/` + 3 added by hermes merge).

**548 endpoints** total across all routers (`grep -c "@router\." api/routes/*.py`).

Use `GET /api/v3/system/registry` for live router status.
