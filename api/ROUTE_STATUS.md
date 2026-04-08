# API Route Status — Single Source of Truth
## Updated: 2026-04-06

Classification based on runtime testing on jarvismax-prod.

## Legend
- **CANONICAL**: Primary endpoint, actively used, returns real data
- **LEGACY-ACTIVE**: Old version still consumed by clients, works
- **PARTIAL**: Endpoint works but returns incomplete/shallow data
- **STUB**: Returns 200 but data is empty, static, or hardcoded
- **DEPRECATED**: Should not be used, will be removed
- **DEAD**: Returns errors, 404, or is unreachable

---

## CANONICAL (v2/v3 — use these)

### Mission Pipeline
| Method | Path | Status | Notes |
|--------|------|--------|-------|
| POST | /api/v2/missions/submit | CANONICAL | Primary mission entry point |
| GET | /api/v2/missions | CANONICAL | List missions with full data |
| GET | /api/v2/missions/{id} | CANONICAL | Mission detail with agent outputs |
| POST | /api/v2/missions/{id}/approve | CANONICAL | Approve pending mission |
| POST | /api/v2/missions/{id}/reject | CANONICAL | Reject pending mission |
| POST | /api/v2/missions/{id}/abort | CANONICAL | Abort running mission |

### System
| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/health | CANONICAL | Component health check |
| GET | /api/v3/system/readiness | CANONICAL | Probe-based readiness |
| GET | /api/v3/system/registry | CANONICAL | Router registry (56 routers, 633 routes) |
| GET | /api/v2/session | CANONICAL | Session info (real role from token) |

### Kernel
| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v3/kernel/status | CANONICAL | Kernel boot status |
| GET | /api/v3/kernel/capabilities | CANONICAL | 19 registered capabilities |

### Agents
| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v2/agents | CANONICAL | Agent list (36 agents) |
| GET | /api/v3/agents | CANONICAL | Agent list with descriptions |
| GET | /api/v3/agents/status | CANONICAL | Team availability |

### Modules/MCP
| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v3/mcp/servers | PARTIAL | Lists 11 servers, all disabled |
| GET | /api/v3/mcp/health | PARTIAL | Reflects real health (disabled=disabled) |
| GET | /api/v3/connectors | PARTIAL | Lists 5, all not_configured |
| GET | /api/v3/modules/health | CANONICAL | Honest: shows 0/0/0 when nothing connected |

### Security
| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v3/security/status | CANONICAL | 6 active rules, audit trail |
| POST | /api/v3/security/check | CANONICAL | Security rule evaluation |

---

## LEGACY-ACTIVE (v1 — clients still use)

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v1/missions | LEGACY-ACTIVE | Mobile app uses this |
| POST | /api/v1/mission/run | LEGACY-ACTIVE | Old mission submit |
| GET | /api/v1/health | LEGACY-ACTIVE | Simple health check |
| POST | /auth/login | LEGACY-ACTIVE | Admin login → JWT |
| POST | /auth/token | LEGACY-ACTIVE | Token creation |

---

## STUB (returns 200 but no real data)

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v3/finance/* | STUB | All zeros, no Stripe configured |
| GET | /api/v3/venture/* | STUB | 0 hypotheses, 0 experiments |
| GET | /api/v3/playbooks | STUB | Static templates, never executed |
| GET | /api/v3/plans | STUB | Returns [] |
| GET | /api/v2/multimodal/capabilities | PARTIAL | Now honest (false for unavailable) |
| POST | /api/v2/multimodal/image/* | STUB | No real OpenAI key |
| POST | /api/v2/multimodal/voice/* | STUB | No Whisper/TTS configured |
| POST | /api/v2/browser/* | STUB | No Playwright |
| POST | /api/v2/voice/* | STUB | No Twilio |
| GET | /api/v3/cognitive/* | PARTIAL | Minimal data (2 nodes, 0 edges) |
| GET | /api/v3/economic/* | PARTIAL | 85 memory records but empty recommendations |
| GET | /aios/* | PARTIAL | Dashboard introspection, not real metrics |

---

## DEAD / NOT VERIFIED

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | /api/v3/observability/status | DEAD | Returns 401 |
| GET | /api/v3/performance/* | NOT VERIFIED | ~80 endpoints, untested |
| GET | /api/v3/execution/* | NOT VERIFIED | Build/deploy system |
| GET | /api/v3/extensions/* | NOT VERIFIED | Extension management |

---

## ENDPOINT COUNT SUMMARY

| Category | Count | % |
|----------|-------|---|
| CANONICAL | ~30 | 5% |
| LEGACY-ACTIVE | ~15 | 3% |
| PARTIAL | ~50 | 9% |
| STUB | ~80 | 14% |
| NOT VERIFIED | ~400+ | 69% |
| DEAD | ~5 | 1% |
| **TOTAL** | **582** | |

**Reality**: Only ~5% of endpoints are proven canonical.
The API surface is 10-20x larger than what's actually used and verified.

---

## CLIENT ENDPOINT MAP (verified 2026-04-06)

### Web (static/*.html) — 52 distinct endpoints

| Endpoint | HTTP | Classification | Status |
|----------|------|---------------|--------|
| /api/v2/missions/submit | POST | CANONICAL | ✅ 200 |
| /api/v2/missions | GET | CANONICAL | ✅ 200 |
| /api/v2/agents | GET | CANONICAL | ✅ 200 |
| /api/v2/agents/:id | GET | CANONICAL | ✅ 200 |
| /api/v2/agents/create | POST | CANONICAL | ✅ 200 |
| /api/v2/status | GET | CANONICAL | ✅ 200 |
| /api/v2/system/capabilities | GET | CANONICAL | ✅ 200 |
| /api/v2/system/health | GET | CANONICAL | ✅ 200 |
| /api/v2/multimodal/capabilities | GET | CANONICAL | ✅ 200 (honest) |
| /api/v2/learning/report | GET | PARTIAL | ✅ 200 |
| /api/v2/learning/global_lessons | GET | PARTIAL | ✅ 200 |
| /api/v3/agents | GET | CANONICAL | ✅ 200 |
| /api/v3/missions | GET | CANONICAL | ✅ 200 |
| /api/v3/modules/health | GET | CANONICAL | ✅ 200 |
| /api/v3/mcp/servers | GET | PARTIAL | ✅ 200 |
| /api/v3/mcp/stats | GET | PARTIAL | ✅ 200 |
| /api/v3/connectors | GET | PARTIAL | ✅ 200 |
| /api/v3/skills | GET | CANONICAL | ✅ 200 |
| /api/v3/tokens | GET | CANONICAL | ✅ 200 (fixed: was /api/auth/tokens) |
| /api/v3/system/readiness | GET | CANONICAL | ✅ 200 (fixed: was /api/v3/readiness) |
| /api/v3/cognitive-events/* | GET | PARTIAL | ✅ 200 |
| /api/v3/capability-routing/* | GET | PARTIAL | ✅ 200 |
| /api/v3/economic/* | GET | PARTIAL | ✅ 200 |
| /api/v3/execution-history | GET | PARTIAL | ✅ 200 |
| /api/v3/plans | GET | PARTIAL | ✅ 200 (returns []) |
| /api/v3/runs | GET | PARTIAL | ✅ 200 |
| /api/v3/templates | GET | PARTIAL | ✅ 200 |
| /api/health | GET | CANONICAL | ✅ 200 |
| /api/v3/metrics/summary | GET | PARTIAL | ✅ 200 |
| /api/v3/finance | GET | STUB | 🚫 404 (feature-flagged) |
| /api/v2/task | POST | LEGACY-ACTIVE | ✅ 200 (alias → submit) |
| /api/v2/tasks | GET | LEGACY-ACTIVE | ✅ 200 (alias → missions) |
| /api/v2/multimodal/image/generate | POST | STUB | returns error (no key) |
| /api/v2/multimodal/voice/tts | POST | STUB | 🚫 404 (feature-flagged) |

### Mobile (Flutter) — 26 distinct endpoints

| Endpoint | HTTP | Classification | Status |
|----------|------|---------------|--------|
| /api/v2/session | GET | CANONICAL | ✅ 200 (real role) |
| /api/v3/missions | GET | CANONICAL | ✅ 200 |
| /api/v3/missions/:id | GET | CANONICAL | ✅ 200 |
| /api/v3/missions/:id/approve | POST | CANONICAL | ✅ 200 |
| /api/v3/missions/:id/reject | POST | CANONICAL | ✅ 200 |
| /api/v3/agents | GET | CANONICAL | ✅ 200 |
| /api/v3/modules/health | GET | CANONICAL | ✅ 200 |
| /api/v3/skills | GET | CANONICAL | ✅ 200 |
| /api/v3/mcp | GET | PARTIAL | ✅ 200 |
| /api/v3/connectors | GET | PARTIAL | ✅ 200 |
| /api/v2/agents | GET | CANONICAL | ✅ 200 |
| /api/v2/status | GET | CANONICAL | ✅ 200 |
| /api/v2/system/capabilities | GET | CANONICAL | ✅ 200 |
| /api/v2/system/policy-mode | GET | CANONICAL | ✅ 200 |
| /api/v2/self-improvement/suggestions | GET | PARTIAL | ✅ 200 |
| /api/v2/metrics/recent | GET | PARTIAL | ✅ 200 |
| /api/v3/metrics/* | GET | PARTIAL | ✅ 200 |
| /api/v3/:type/:id/toggle | POST | CANONICAL | ✅ 200 |
| /api/v3/:type/:id/test | POST | CANONICAL | ✅ 200 |
| /api/v2/tasks | GET | LEGACY-ACTIVE | ✅ 200 |
| /api/stats | GET | LEGACY-ACTIVE | ✅ 200 (fixed: was 500) |
| /api/system/mode | GET | LEGACY-ACTIVE | ✅ 200 |
| /api/system/mode/uncensored | POST | LEGACY-ACTIVE | ⚠️ works but dangerous |
| /api/v1/missions/:id/stream | GET | LEGACY-ACTIVE | ✅ 200 (SSE) |

### Convergence Strategy
1. **No breaking changes**: All legacy endpoints kept until mobile app update
2. **Feature-flagged stubs**: finance/venture/browser/voice/playbooks → 404 by default
3. **Fixed broken paths**: /api/stats (500→200), /api/auth/tokens (404→200), /api/v3/readiness (404→200)
4. **Next mobile release**: Migrate /api/v2/tasks → /api/v3/missions, /api/stats → /api/v2/status
