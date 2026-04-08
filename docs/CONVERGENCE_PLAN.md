# JARVISMAX — CONVERGENCE PLAN
## Atlas Director — Phase 1→4

---

# 1. CURRENT REALITY

## Backend (PROVEN core)
- **582 endpoints** across v1/v2/v3/unversioned
- Mission pipeline: PROVEN (submit→plan→agents→LLM→done)
- Kernel: PROVEN (boot, orchestration, policy, evaluation)
- Agents: PROVEN (36 agents, real LLM calls via OpenRouter)
- Memory: Postgres + Qdrant PROVEN infrastructure, data sparse
- Auth: Bearer token → always maps to "admin" role (no real RBAC)
- Self-improvement daemon: WIRED but blocked by security_gate

## Web (static HTML)
- 13 HTML files in static/ (dashboard, missions, modules, finance, etc.)
- Served by FastAPI static mount
- No framework — vanilla HTML+JS
- Consumes various v2/v3 endpoints
- **No verification that displayed data matches reality**

## Mobile (Flutter/Dart)
- 14 screens (home, missions, modules, admin, health, etc.)
- Points to jarvis.jarvismaxapp.co.uk:443 production
- Consumes v1/v2 endpoints (not v3)
- Has modules_screen that shows toggles for connectors/MCP
- Has session_manager that assumes admin role from /api/v2/session
- **Uncensored mode toggle exists**

## Auth
- Single admin password (JARVIS_ADMIN_PASSWORD env var)
- Bearer token authentication works
- `/api/v2/session` always returns role="admin" via fallback
- No real RBAC — everything is admin-level access
- access_tokens.py has role field but /api/v2/session ignores it

## Modules/MCP/Connectors/Skills (as seen by API)
- MCP: 11 servers listed, ALL disabled, no configured URLs
- Connectors: 5 listed (github, slack, etc.), ALL "not_configured"
- Skills: 6 listed, all templates (never executed)
- Modules health: 0 connected, 0 failing, 0 disabled

## Docs
- ARCHITECTURE.md: reflects structure, not runtime truth
- TRUTH_AUDIT: created this session, honest
- README: partially aspirational

## Docker/Build
- `docker/Dockerfile` builds from `requirements.txt`
- No `pyproject.toml` or `poetry.lock` in build chain
- `requirements.txt` is the real source of truth for deps

## Tests
- 4847 passing unit tests
- 700+ CI gate tests
- No integration tests verified

---

# 2. PROBLEMS / INCONSISTENCIES

## SOLID ✅
1. Kernel boot and orchestration
2. Mission pipeline end-to-end
3. Agent LLM calls (Claude Sonnet via OpenRouter)
4. Postgres persistence (4 modules migrated)
5. Embeddings (OpenRouter)
6. Docker stack (10 containers healthy)
7. 4847 unit tests passing

## TROMPEUR 🔴
1. `/api/v2/session` returns role="admin" for ANY valid token — no real RBAC
2. `multimodal/capabilities` says dalle3=true, vision=true without OpenAI key
3. Finance endpoints return all zeros, presented as feature
4. Venture/Playbooks = static templates, not real executions
5. MCP servers listed as "available" but all disabled
6. Connectors listed but all "not_configured"
7. Mobile modules_screen shows toggles that don't do anything real
8. Web dashboard may show features that are stubs
9. `/aios/status` shows capabilities as "enabled" that are just code-exists checks

## INCOMPLET 🟡
1. RAG: 0 documents indexed
2. Vector memory: collection 1536 empty (101 points only in 384)
3. Redis: 0 keys (unused beyond rate limiter)
4. Self-improvement: blocked by security_gate
5. Voice/Browser: stub endpoints, no runtime
6. Mobile: points to production but some screens consume non-existent data

## CONTRADICTOIRE ⚠️
1. v1/v2/v3 all active simultaneously — client doesn't know which is canonical
2. Mobile uses v1/v2, web uses v2/v3 — fragmented contract
3. `include_in_schema=False` on /api/v2/session hides it from docs but it's critical for auth
4. Modules "health" endpoint says 0 everything but screens show toggles
5. 582 endpoints but frontend uses maybe 20-30

## DANGEREUX ☠️
1. Admin fallback on /api/v2/session — any token = admin
2. No rate limiting on mission submit (could drain OpenRouter credits)
3. LangSmith auth failing on every LLM call (noisy logs, potential leak)
4. Credentials exposed in Telegram group (API keys, SSH passwords)

## DETTE TECHNIQUE
1. api/main.py: 800+ lines, 55 include_router, concentration point
2. agents/crew.py: 1100+ lines, all agent classes in one file
3. 37 broken internal imports (all in try/except but still noise)
4. Dual SQLite/Postgres paths in multiple modules

## DETTE PRODUIT
1. No clear "this is v3, use this" — everything lives together
2. Frontend has pages for features that don't work (finance, voice, browser)
3. Mobile has admin_panel that may show fake data
4. No onboarding — user lands on login, then what?

---

# 3. PRIORITY

## P0 — Fix before any storytelling
1. **Fix /api/v2/session admin fallback** — return real role from token
2. **Add endpoint_status metadata** to all routes (canonical/stub/deprecated)
3. **Fix multimodal/capabilities** — return actual capability state
4. **Disable LangSmith calls** (LANGSMITH_TRACING=false)
5. **Fix MCP/connectors/modules to show honest status**

## P1 — Fix soon
6. Document the real mission model (1-turn, not multi-thread)
7. Remove or gate finance/voice/browser/venture endpoints behind feature flags
8. Make mobile consume only canonical endpoints
9. Clean web dashboards to show only real data

## P2 — Structural
10. Extract route groups from api/main.py into proper router files
11. Create explicit API versioning strategy doc
12. Consolidate front/back contract

## P3 — Polish
13. Premium design alignment
14. Consistent French/English strategy

---

# 4. EXECUTION PLAN — P0

## 4.1 Fix /api/v2/session (admin fallback)
**File**: `api/main.py` lines 502-522
**Action**: Remove fallback admin. Return role from decoded token or access_token table.
**Acceptance**: `curl` with valid token returns real role; invalid token returns 401.

## 4.2 Add endpoint_status to stubs
**Files**: Route files that serve stubs
**Action**: Add `X-Endpoint-Status` header to responses (canonical/wired/stub/deprecated)
**Acceptance**: `curl -I` on stub endpoints shows status header

## 4.3 Fix multimodal/capabilities lying
**File**: `api/routes/multimodal.py` or wherever capabilities are returned
**Action**: Check actual API key presence before returning true
**Acceptance**: Without OPENAI_API_KEY, dalle3=false

## 4.4 Disable LangSmith
**File**: `.env` on production
**Action**: Set LANGSMITH_TRACING=false
**Acceptance**: No more LangSmith auth errors in logs

## 4.5 Honest MCP/connectors/modules status
**Files**: Route handlers for /api/v3/mcp, /api/v3/connectors, /api/v3/modules
**Action**: Ensure status reflects runtime reality, not just code existence
**Acceptance**: disabled shows as disabled, not_configured shows as not_configured
