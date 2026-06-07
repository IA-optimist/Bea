# BeaMax Architecture

> Single source of truth for the BeaMax architecture as of SHA `889a1c3`.
> Verified by direct code reading + 5 audit agents on 2026-04-08.

---

## Overview

BeaMax is a layered AI orchestration system built on FastAPI + a custom kernel + Python cognitive core. Its main interface is the **mission lifecycle**: a goal goes in, a structured result comes out, and the system learns from every execution.

```
┌─────────────────────────────────────────────────────────────┐
│  CLIENTS                                                     │
│  • static/app.html (web SPA, French)                        │
│  • beamax_app/ (Flutter mobile, canonical)               │
│  • mobile/ (React Native, secondary, WIP)                   │
│  • frontend/ (React web dashboard, WIP)                     │
└─────────────────────────────────────────────────────────────┘
                          ↓ HTTP/WebSocket
┌─────────────────────────────────────────────────────────────┐
│  API LAYER (api/)                                            │
│  FastAPI · 55 routers · 548 endpoints                       │
│  Middleware: CORS → AccessEnforcement → SecurityHeaders → RateLimit │
│  Auth: Constant-time HMAC + JWT HS256 + access tokens       │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  COGNITIVE CORE (core/)                                      │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  MetaOrchestrator (core/meta_orchestrator.py)       │   │
│  │  Central state machine — 1973 lines, 12 phases      │   │
│  │                                                      │   │
│  │  1. Circuit breaker check                           │   │
│  │  2. Kernel cognitive cycle (classify+plan+route)    │   │
│  │  3. Classification (3-tier fallback)                │   │
│  │  4. Capability routing                              │   │
│  │  5. Memory retrieval (lessons from past)            │   │
│  │  6. Context assembly                                │   │
│  │  7. Mission reasoning state (build)                 │   │
│  │  8. Confidence policy (5-tier gate)                 │   │
│  │  9. Decompose if needed                             │   │
│  │ 10. Security layer check                            │   │
│  │ 11. Execute via delegate (BeaOrchestrator)       │   │
│  │ 12. Post-execution: update state, learn lessons     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  KERNEL LAYER (kernel/)                                      │
│  BeaKernel singleton — boot at startup                   │
│  • 19 capabilities (planning, execution, memory, policy…)   │
│  • 5 memory types (working, episodic, execution, etc.)      │
│  • Real evaluator + learner + planner (heuristic + core)    │
│  • Contracts: Mission, Goal, Plan, Action, Decision         │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  EXECUTION LAYER (executor/ + core/action_executor.py)       │
│  • Task queue (heapq priority, retry, timeout, 4 workers)   │
│  • ActionExecutor: 10 action types, whitelist/blacklist     │
│  • SupervisedExecutor: approval gating                      │
│  • CapabilityDispatcher: native / plugin / MCP routing      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  LLM LAYER (core/llm_factory.py)                             │
│  Provider routing: OpenAI / Anthropic / OpenRouter / Ollama │
│  • Role-based selection (orchestrator/architect/coder/…)    │
│  • Ollama circuit breaker (3 fails → OPEN 30s)              │
│  • Safer-model downgrade (cloud → local)                    │
│  • Key validation                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Mission lifecycle (12 phases)

The canonical entry point is `MetaOrchestrator.run_mission()` (`core/meta_orchestrator.py`, 1973 lines). Every mission goes through these phases in order. Each phase is fail-open (logs WARNING but continues) unless explicitly noted.

### Phase 1: Circuit breaker
**File**: `core/meta_orchestrator.py:364-370`  
Two-state breaker (CLOSED/OPEN). Prevents cascade failures when delegate is broken. Threshold: 5 consecutive failures, 60s reset.

### Phase 2: Kernel cognitive cycle
**File**: `kernel/runtime/kernel.py:run_cognitive_cycle()`  
Calls kernel layer to: classify mission, generate plan, route to capabilities, retrieve relevant lessons. Returns enrichment dict. **Fail-open**: returns `{}` if kernel unavailable, fallback phases run instead.

### Phase 3: Classification
**File**: `core/orchestration/mission_classifier.py`  
3-tier fallback: kernel pre-computed → kernel classifier → core classifier → None. Output: `{task_type, risk_level, reasoning}`.

### Phase 4: Capability routing (BLOC 2)
**File**: `core/meta_orchestrator.py:471-609`  
Skipped if kernel succeeded. Otherwise: semantic router matches goal → capabilities; kernel enrichment; performance hints. Advisory only — does not block execution.

### Phase 5: Memory retrieval (Pass 42 — Phase 3)
**File**: `core/orchestration/memory_retrieval.py`  
Calls `memory_facade.search()` for past failures and successes (top_k=3, score threshold 0.40). Synthesizes "avoid" / "reuse" guidance. Injected into `enriched_goal` as `[MEMORY_LESSONS]`. **Verified**: real queries, not stubs.

### Phase 6: Context assembly
**File**: `core/orchestration/context_assembler.py`  
Returns `{prior_skills, relevant_memories, suggested_approach}`. Injected into metadata.

### Phase 7: Mission reasoning state (Pass 42 — Phase 1)
**File**: `core/orchestration/mission_reasoning_state.py` (550+ lines)  
Builds explicit pre-execution model:
- `initial_state` / `target_state`
- `preconditions` / `dependencies` / `constraints`
- `candidate_actions` (ranked)
- `expected_effects` / `success_criteria` / `failure_modes`

Updated post-execution with `observed_effects`, computed diff, `state_satisfied` boolean (soft 0.33 threshold).

### Phase 8: Confidence policy (Pass 42 — Phase 2)
**File**: `core/orchestration/confidence_policy.py` (352 lines)  
**5 tiers**, all with real behavioral consequences:

| Tier | Confidence | Behavior |
|------|-----------|----------|
| `PROCEED` | ≥ 0.70 | Normal execution |
| `CONTEXT` | 0.50–0.69 | `add_context=True` → triggers extra memory retrieval |
| `CAUTIOUS` | 0.35–0.49 | `require_approval=True` → blocks via approval gate |
| `DECOMPOSE` | 0.20–0.34 | `require_approval` + `decompose_mission` + `use_safer_model` |
| `ABORT` | < 0.20 | Mission raised RuntimeError @ line 958 |

**Risk multipliers**: low=0.00, medium=0.05, high=0.10, critical=0.15  
**Destructive override**: forces CAUTIOUS for `deployment` / `deletion` / `database_write`  
**Prior failures override**: forces CAUTIOUS if similar past failures detected

### Phase 9: Decompose mission (Pass 43)
**File**: `core/meta_orchestrator.py:988-1020`  
When `confidence_policy.decompose_mission == True`, restructures `enriched_goal` into explicit numbered steps from `MissionReasoningState.candidate_actions`.

### Phase 10: Security layer check (BLOC 4)
**File**: `core/meta_orchestrator.py:1088-1150` + `security/__init__.py`  
Calls `get_security_layer().check_action(action_type, mission_id, mode, risk_level, action_target)`.  
- If `escalated`: sets `needs_approval = True`
- If `not allowed`: sets `needs_approval = True`  
**Note**: Does not hard-block — escalates to approval queue. Fail-open if SecurityLayer crashes.

### Phase 11: Execution via delegate
**File**: `core/meta_orchestrator.py:1209-1222`  
```python
outcome = await asyncio.wait_for(
    supervise(delegate.run, mission_id, enriched_goal, ...,
              requires_approval=needs_approval,
              skip_approval=force_approved),
    timeout=mission_timeout_s,
)
```
The delegate is `BeaOrchestrator` (real LLM agents from `agents/crew.py`). The supervise wrapper handles approval gating + retry (MAX_RETRIES=2, 180s per attempt).

### Phase 12: Post-execution learning
**File**: `core/meta_orchestrator.py:1251-1268`  
- `mission_state.update_observed(result, error)` → fills observed effects, computes diff
- Lesson extraction via `KernelLearner.learn()` → stored via `core.orchestration.learning_loop.store_lesson`
- State recorded in metadata for audit trail

---

## Auth flow (end-to-end)

```
1. Request arrives at FastAPI
   ↓
2. CORSMiddleware (allow_origins from CORS_ORIGINS env var)
   ↓
3. AccessEnforcementMiddleware (api/middleware.py)
   • Extracts token from: Authorization: Bearer | X-Bea-Token | ?token=
   • Calls check_access(raw_token, path, permission)
   • If is_public_path(path): allow
   • Otherwise: validate via verify_token()
     - jv-* prefix → AccessTokenManager
     - JWT (HS256) → PyJWT
     - Static token → hmac.compare_digest
   • On failure: return 401/403/429
   • On success: set request.state.user
   ↓
4. SecurityHeadersMiddleware (CSP, X-Frame-Options)
   ↓
5. RateLimitMiddleware (sliding window per IP+path)
   ↓
6. Per-route Depends(require_auth) (defense in depth)
   • Reads request.state.user (set by middleware)
   • Or re-verifies via verify_token() as fallback
   ↓
7. Route handler executes
```

**Constant-time comparison**: `hmac.compare_digest()` used everywhere (no `==` for token compare).

**Public paths** (`api/access_enforcement.py:_PUBLIC_PATHS`):
- `/health`, `/api/v2/health`, `/api/v3/system/readiness` (Docker healthcheck)
- `/`, `/app.html`
- `/auth/login`, `/auth/token`
- `/docs`, `/openapi.json`, `/redoc`

**Static file extensions bypass** (CSS/JS/PNG/ICO/SVG/WOFF2 only — `.html` excluded).

---

## Kernel layer

**Singleton**: `kernel/runtime/kernel.py:BeaKernel` initialized at startup via `kernel/runtime/boot.py:boot_kernel()`.

### Subsystems (registered at boot)

| Subsystem | File | Registered from |
|-----------|------|----------------|
| Policy engine | `kernel/adapters/policy_adapter.py` | `core.policy_engine.PolicyEngine.check_action` |
| Planner | `kernel/planning/planner.py` | `core.planner.build_plan` |
| Orchestrator | `kernel/runtime/kernel.py` | `core.meta_orchestrator.MetaOrchestrator.run_mission` |
| Mission classifier | `kernel/classifier/` | `core.orchestration.mission_classifier.classify` |
| Reflection | `kernel/evaluation/scorer.py` | `core.orchestration.reflection.reflect` |
| Critique | `kernel/evaluation/scorer.py` | `core.orchestration.reasoning_engine.critique_output` |
| Lesson storage | `kernel/learning/learner.py` | `core.orchestration.learning_loop.store_lesson` |
| Lesson retrieval | `kernel/memory/interfaces.py` | `core.learning_loop.find_relevant_lessons` |
| Memory facade | `kernel/memory/interfaces.py` | `core.memory_facade.MemoryFacade` (with K1 wrapper) |
| Capability router | `kernel/routing/` | `core.capability_routing.router.route_mission` |

### Memory types (5)

`kernel/memory/interfaces.py`:

| Type | Purpose | Backend |
|------|---------|---------|
| `working` | Short-lived context (in-memory dict, 200-item limit, TTL eviction) | RAM |
| `episodic` | Event log | MemoryFacade (Qdrant) |
| `execution` | Plan history | MemoryFacade (Qdrant) |
| `procedural` | Learned skills | MemoryFacade (Qdrant) |
| `semantic` | Facts/knowledge | MemoryFacade (Qdrant) |

### Capabilities (19)

`kernel/capabilities/registry.py` registers 19 capabilities at boot:
- **Planning**: `plan_generation`, `plan_validation`, `decision_evaluation`
- **Execution**: `skill_execution`, `tool_invocation`, `code_generation`, `quality_review`
- **Memory**: `memory_write`, `memory_recall`
- **Policy**: `risk_evaluation`, `policy_check`
- **Domain**: `market_intelligence`, `product_design`, `financial_reasoning`, `compliance_reasoning`, `risk_assessment`, `venture_planning`, `strategy_reasoning`

---

## Execution layer

**Two parallel execution paths** coexist:

### `core/action_executor.py` (PRIMARY — used at runtime)
Real daemon thread started at boot. Dispatches actions by keyword matching (research/planning/building/review/improvement). Risk classification (LOW/MEDIUM/HIGH/CRITICAL). Used by agents.

### `executor/` directory (SUPPORT)
Lower-level building blocks:
- **`execution_engine.py`** — Heapq priority queue, 4 concurrent workers, retry policy with exponential backoff, 30s timeout per task, LRU eviction at 500 terminal tasks
- **`runner.py`** — `ActionExecutor` class with 10 action types (read_file, write_file, run_command, etc.), whitelist/blacklist, post-write guard checks
- **`supervised_executor.py`** — Wraps ActionExecutor with `RiskEngine` analysis. LOW → auto. MEDIUM → blocked + notify. HIGH → blocked + notify.
- **`task_queue.py`** — Async queue (`asyncio.PriorityQueue`)
- **`capability_dispatch.py`** — Routes to native handler / plugin / MCP

**Note**: `core/action_executor.py` is the runtime path. The `executor/` modules provide lower-level primitives invoked by it and by `core/orchestrator.py`.

---

## LLM Factory

**File**: `core/llm_factory.py` (803 lines)

### Provider selection (priority order)

1. **`_provider_override` ContextVar** (set by Phase 0c routing)
2. **`_safer_model_active` ContextVar** (set by Phase 8 confidence policy when DECOMPOSE tier)
3. **`ROLE_PROVIDERS` map** (per-role default)
4. **`settings.model_strategy`** (env var)
5. **Fallback**: `settings.model_fallback`

### Role-based routing

| Role | Default model |
|------|---------------|
| `orchestrator` | claude-sonnet-4.5 |
| `architect` | claude-sonnet-4.5 |
| `coder` | claude-sonnet-4.5 |
| `self_improvement` | claude-sonnet-4.5 |
| `fast` | gpt-4o-mini |
| `fallback` | gpt-4o-mini |
| `vision` | gpt-4o-mini |

`LOCAL_ONLY_ROLES` (advisor, memory, code, vision) never escalate to cloud.

### Ollama circuit breaker

States: `CLOSED` (normal) → `OPEN` (fast-fail) → `HALF` (recovery probe).
- Threshold: 3 failures in 60s window → OPEN
- Recovery: 30s → HALF (one probe allowed)
- Success in HALF → CLOSED

### Key validation

`_is_valid_key()` rejects:
- `None` or empty string
- Length < 20 chars
- Contains placeholder fragments (`change_me`, `your_key`, `xxx`, etc.)

---

## Self-improvement pipeline

**Files**: `core/self_improvement/`

```
1. FailureCollector.collect()       → Recent mission failures
2. ImprovementPlanner.plan()        → Improvement proposals
3. CandidateGenerator.generate()    → Code or workspace candidates
4. For each candidate:
   - Code patch  → PromotionPipeline.execute()
                   ├── Sandbox test (no network)
                   ├── Critic review
                   ├── Test runner (pytest)
                   └── Decision: PROMOTE / REVIEW / REJECT
   - Workspace   → SafeExecutor.execute()
5. Emit observability event
```

**Key safety properties**:
- Sandbox runs with `--network=none`
- Secret scrubbing before returning results
- Test regression detection
- Disabled by default in `BEA_PRODUCTION=true` mode

---

## Business handlers

**File**: `core/orchestration/business_missions.py`

Registered at startup via `register_business_handlers()` (called from `main.py:109`).

| Mission type | Handler | Status |
|--------------|---------|--------|
| `business.scan_opportunities` | `handle_scan_opportunities()` | ✅ WIRED — calls real `OpportunityScanner` (Product Hunt RSS, Reddit JSON, HN Algolia) |
| `business.build_product` | `handle_build_product()` | 🚧 WIRED but `ProductBuilder` generates HTML template |
| `business.deploy_product` | `handle_deploy_product()` | 🚧 Handler exists, deploy logic TODO |
| `business.check_compliance` | `handle_check_compliance()` | ✅ WIRED — calls real `ComplianceChecker` (regex blacklist/greylist) |
| `business.optimize_taxes` | `handle_optimize_taxes()` | ✅ WIRED — calls `TaxOptimizer` (France calculation) |
| `business.track_revenue` | `handle_track_revenue()` | 🚧 WIRED but `RevenueEngine` is dataclasses-only |

---

## Configuration

**File**: `config/settings.py`

All settings read from environment variables with sensible defaults. Production hard-fails via `enforce_production_secrets()` if `BEA_PRODUCTION=true` and:
- `BEA_SECRET_KEY` is the default placeholder
- `BEA_ADMIN_PASSWORD` is empty
- `BEA_API_TOKEN` is empty

`enforce_llm_key()` raises `RuntimeError` at startup if no LLM provider key is configured (unless `DRY_RUN=true`).

See [API_REFERENCE.md](API_REFERENCE.md) for the full list of env vars.

---

## Tests

**Gate tests** (must pass on every PR — 802 tests across 15 files):
- `test_terminal_state_truth.py` — Ghost-DONE regression
- `test_canonical_mission_persistence.py` — Mission store CRUD
- `test_hierarchical_planner.py`
- `test_production_hardening_p34.py`
- `test_mission_engine.py`
- `test_capability_routing.py`
- `test_kernel.py`
- `test_self_improvement_engine.py`
- `test_secret_vault.py`
- `test_identity_manager.py`
- `test_evaluation_engine.py`
- `test_economic_cognition.py`
- `test_surgical_hardening.py`
- `test_self_improvement_execution.py`
- `test_cognitive_upgrade.py`

**Full suite**: ~5000 tests, 802 gated. See [STATUS.md](STATUS.md) for known stale failures.

---

## Deployment

### Local dev
```bash
python main.py
```

### Docker (single command)
```bash
docker-compose up -d
```

Services started:
- `beamax-api` (port 8000)
- `postgres` (vector + relational)
- `redis` (cache + rate limiting)
- `qdrant` (vector memory, port 6333)
- `caddy` (TLS reverse proxy)
- `ollama` (optional, GPU)

See [QUICKSTART.md](QUICKSTART.md) for environment setup.
