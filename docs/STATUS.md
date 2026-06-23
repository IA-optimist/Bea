# Béa — Component Status

> Honest per-component maturity rating. Last verified: **2026-06-23** (cross-audit Opus session, branch `claude/audit-truth-map-and-runtime-triage`). Corrections: Flutter v1 table, dependency versions, hexstrike_v2 import status.
> Verified by direct code reading + runtime observation + gate test results.

Packaging truth:
- License: MIT
- Build metadata: `pyproject.toml` (PEP 621, `name=beamax`, `version=0.1.0`)
- Version line: SemVer `0.x` until the public API is frozen
- Wheel validated: `python -m build` → `beamax-0.1.0-py3-none-any.whl`, `import beamax_cli / core / api` OK (T1.5 ✅)

## Summary (June 2026)

| Area | State |
|---|---|
| API (590+ routes) | 🟢 Running — PID stable, 400+ tests passing |
| Auto-improvement daemon | 🟢 **End-to-end working** — first `proposal_saved` 2026-06-16 |
| Business engine | 🟢 AutoContentFlow + CVOptimIA live on Railway |
| Telegram bot | 🟢 Codex gpt-5.5, vision (photos + YouTube), persistent task |
| Mobile APK | 🟢 Flutter 3.41.9, Tailscale access, rebuilt 2026-06-07 |
| Docker stack | 🟢 Back in service 2026-06-05 (postgres/redis/qdrant healthy) |
| Renommage jarvis→bea | ✅ Done 2026-06-07, 823 files, commit `aaee8c6` |
| Forge-builder | 🟢 Committed 2026-06-12, suite verte Windows |
| Provider fallback chain | 🟢 FallbackChainProvider T5.2 — 12 tests |
| Provider runtime health | 🟢 PR #92 — `check_provider_health()`, Ollama autodiscovery, `scripts/provider_healthcheck.py` |
| Sandbox killswitch | 🟢 DockerSandbox timeout+kill() T5.3 — 11 tests |
| Windows CI job | 🟢 Added `test-windows` job T5.4 |
| OTel tracing shim | 🟡 `core/observability/tracing.py` T6.1 — optionnel, fail-open |
| Eval publisher | 🟢 `core/observability/eval_publisher.py` T6.2 — GET/POST /api/v1/evaluations |
| V1 API surface | 🟡 `/api/v1/*` gelé T6.3 — 6 endpoints restants, 3 load-bearing Flutter |
| Plugin signatures | 🟢 HMAC-SHA256 `plugins/signatures.py` T6.4 — verify on registry |
| Client surfaces | 🟡 Inventoriées PR #85 — 2 canoniques, 1 supported (Flutter), 1 expérimental (React) |

**Maturity legend:**
- 🟢 **PROVEN** — Real implementation, used in runtime, gate-tested
- 🟡 **WIRED** — Connected to orchestrator, not proven end-to-end
- 🔵 **SCAFFOLDING** — Code exists, not yet wired (awaiting integration)
- 🔴 **STUB** — Boilerplate only, no real logic
- ⚫ **PLANNED** — Not yet started

---

## 🟢 PROVEN — Production-grade

### Cognitive Core
| Component | File | Evidence |
|-----------|------|----------|
| MetaOrchestrator | `core/meta_orchestrator.py` | 1973 lines, 12 phases, used at every mission, gate-tested |
| Mission lifecycle | `core/mission_system.py` | CRUD + persistence verified by `test_canonical_mission_persistence.py` (17 tests) |
| ConfidencePolicy | `core/orchestration/confidence_policy.py` | 5-tier system with real behavioral consequences (abort line 958, approval line 965, decompose line 988) |
| MissionReasoningState | `core/orchestration/mission_reasoning_state.py` | Full lifecycle: build → update → diff (550+ lines) |
| MemoryRetrieval | `core/orchestration/memory_retrieval.py` | Real `facade.search()` queries with 0.40 score threshold |
| Reasoning engine | `core/orchestration/reasoning_engine.py` | Pre-execution shape/complexity analysis (~1000 lines) |
| Mission classifier | `core/orchestration/mission_classifier.py` | 3-tier fallback, used by routing + policy |
| Learning loop | `core/orchestration/learning_loop.py` | Lesson extraction + storage + retrieval |
| Execution supervisor | `core/orchestration/execution_supervisor.py` | Real approval gate, retry (MAX=2, 180s timeout) |
| LLM Factory | `core/llm_factory.py` | 803 lines, Ollama circuit breaker, role routing, safer_model |

### Kernel
| Component | File | Evidence |
|-----------|------|----------|
| Boot sequence | `kernel/runtime/boot.py` | 11 registrations at startup |
| BeaKernel singleton | `kernel/runtime/kernel.py` | `run_cognitive_cycle()` is the cognitive brain |
| Memory interfaces | `kernel/memory/interfaces.py` | 5 typed memory categories with registration slots |
| Capability registry | `kernel/capabilities/registry.py` | 19 capabilities registered |
| Evaluator | `kernel/evaluation/scorer.py` | Real heuristic + core reflection/critique vote |
| Learner | `kernel/learning/learner.py` | Lesson extraction + storage |
| Planner | `kernel/planning/planner.py` | Core planner registered + heuristic fallback |
| Contracts | `kernel/contracts/types.py` | Mission, Goal, Plan, Action, Decision types |

### Execution
| Component | File | Evidence |
|-----------|------|----------|
| ActionExecutor (runtime) | `core/action_executor.py` | Daemon thread, dispatch by keyword, used by agents |
| Execution engine | `executor/execution_engine.py` | Heapq priority queue, retry, timeout, 4 workers |
| Task queue | `executor/task_queue.py` | Async priority queue |
| Action runner | `executor/runner.py` | 10 action types, whitelist/blacklist, post-write guard |
| Capability dispatch | `executor/capability_dispatch.py` | Native / plugin / MCP routing |

### Auth & Security
| Component | File | Evidence |
|-----------|------|----------|
| AccessEnforcementMiddleware | `api/middleware.py` | Validates token before route handler runs |
| JWT auth | `api/auth.py` | HS256 with `hmac.compare_digest`, PyJWT |
| Per-route auth (require_auth) | `api/_deps.py` | Used by 46/53 route files |
| Rate limiter | `api/rate_limiter.py` | Sliding window, Redis-backed (in-memory fallback) |
| Production secret enforcement | `config/settings.py:enforce_production_secrets` | Hard-fails on insecure defaults if `BEA_PRODUCTION=true` |

### Tests & CI
| Component | Status |
|-----------|--------|
| Gate tests | Current hardening lane green ✅ |
| Mission persistence regression | 17 tests, all green |
| Terminal state truth (ghost-DONE fix) | 20 tests, all green |
| Cognitive upgrade tests | Phase 1+2+3 covered |
| Access enforcement | 30 tests, all green |
| Self-improvement execution | Patch lifecycle covered |

### Self-improvement pipeline
| Component | File | Evidence |
|-----------|------|----------|
| Engine | `core/self_improvement/engine.py` | Full cycle: collect → plan → generate → execute |
| Test runner | `core/self_improvement/test_runner.py` | Real pytest integration, regression detection |
| Promotion pipeline | `core/self_improvement/promotion_pipeline.py` | Sandbox + secret scrubbing + decisions |
| Sandbox safety | `--network=none`, secret scrubbing | Verified |

### Business handlers (wired into orchestrator)
| Mission type | Status |
|--------------|--------|
| `business.scan_opportunities` | 🟢 Real API calls (Product Hunt RSS, Reddit JSON, HN Algolia) |
| `business.optimize_taxes` | 🟢 Real France tax calculation |
| `business.check_compliance` | 🟢 Regex-based blacklist/greylist (RED/YELLOW/GREEN) |

### Web canonical interface
| Component | File | Evidence |
|-----------|------|----------|
| Web SPA | `static/app.html` (973 lines) | Canonical web control surface; kept alongside API and Flutter |
| Admin cockpit | `static/cockpit.html` | Secondary admin view — missions, agents, security, business metrics |

### Mobile canonical interface
| Component | File | Evidence |
|-----------|------|----------|
| Flutter app | `beamax_app/` (~7,400 lines) | Canonical mobile path. Secure storage, token refresh, WS reconnect. |

### Client surfaces — API version usage (PR #85, 2026-06-21)

| Surface | Status | v1 calls | v3 calls | Notes |
|---------|--------|----------|----------|-------|
| `static/app.html` | CANONICAL | 0 | ✅ all | auth via v2 only |
| `static/cockpit.html` | CANONICAL | 0 | ✅ all | v2 for agents |
| `beamax_app/` (Flutter) | SUPPORTED | **0** ✅ (PR #91 2026-06-21) | ✅ all | APK rebuild pending — v1 endpoints still live server-side |
| `frontend/` (React) | EXPERIMENTAL | 0 | ✅ most | v2 for self-improvement endpoints |
| `orchestrate-cli/` | SUPPORTED | 0 | ✅ all | Python CLI, no browser |

**Flutter v1 migration: COMPLETE (PR #91, 2026-06-21, verified 2026-06-23)** — `grep -rn "api/v1" beamax_app/lib/` returns 0 active hits.
- `POST /api/v3/missions/{id}/pause` (line 550) ✅
- `POST /api/v3/missions/{id}/resume` (line 559) ✅
- `GET /api/v3/missions/{id}/stream` (line 755) ✅

**APK rebuild required** before removing server-side v1 endpoints. See `docs/FRONTEND_SURFACES.md`.

See `docs/FRONTEND_SURFACES.md` for full inventory and migration plan.

---

## 🟡 WIRED — Connected, not fully proven

| Component | File | Why wired vs proven |
|-----------|------|---------------------|
| MemoryFacade | `core/memory_facade.py` | Registered in main.py:189-218 with K1 wrapper. Used by retrieval. Not stress-tested with live Qdrant. |
| MCP server (bea_mcp) | `core/mcp/bea/bea_mcp_server.py` | 3 read-only tools (memory_search, mission_status, list_missions). Untested with live MCP clients. |
| MCP registry | `core/mcp/mcp_registry.py` | Infrastructure ready, sidecars defined, not actively called by orchestrator |
| Adapters | `kernel/adapters/*.py` | 5 adapter modules (capability/event/plan/mission/result/policy). Used at boot. |
| Connectors (filesystem, HTTP, GitHub) | `connectors/*.py` | Code exists, agents use direct tools instead |
| Reasoning prepass | `core/orchestration/reasoning_engine.py` | Called from meta_orchestrator @ line 438. Real logic. Edge cases not fully covered. |
| WebSocket auth | `api/ws.py` | Token validated before `accept()`. Live connection edge cases not fully tested. |

### Business handlers (wired but partial)
| Mission type | Status |
|--------------|--------|
| `business.build_product` | 🟡 Handler wired, but `ProductBuilder` generates static HTML template (no React/Next.js, no deploy) |
| `business.deploy_product` | 🟡 Handler exists, deployment logic is `# TODO: Implement actual deployment (Vercel API + Railway API)` |
| `business.track_revenue` | 🟡 Handler wired, but `RevenueEngine` is dataclasses-only (no Stripe integration) |

---

## 🔵 SCAFFOLDING — Awaiting orchestrator integration

> These files exist with substantial code but are not yet wired. **Do not delete** — they're being progressively integrated.

### Business top-level (1,274 lines)
| File | Lines | Notes |
|------|-------|-------|
| `business/business_engine.py` | 342 | Orchestrator-style facade for SaaS generation pipeline |
| `business/business_orchestrator.py` | 240 | Higher-level workflow coordinator |
| `business/business_knowledge.py` | 450 | Domain knowledge base |
| `business/layer.py` | 242 | Business layer abstraction |

### Future revenue streams
| File | Lines | Status |
|------|-------|--------|
| `agent_marketplace/marketplace.py` | 511 | AgentListing dataclasses, future marketplace |
| `data_intelligence/market_intel_service.py` | 401 | Competitor/market trend service skeleton |
| `security/blue_team/soc_service.py` | (TBD) | SOC service class, standalone |

### Capabilities
| File | Lines | Status |
|------|-------|--------|
| `executor/desktop_env/browser.py` | 58 | Browser automation skeleton |
| `executor/desktop_env/editor.py` | 106 | File editor capability |
| `executor/desktop_env/sandbox.py` | 146 | Sandbox execution |
| `executor/desktop_env/terminal.py` | 141 | Terminal interaction |
| `core/agent_specialization.py` | 888 | Task clustering / agent specialization (test-only currently) |

### Plugins
| File | Status |
|------|--------|
| `plugins/plugin_registry.py` | Production-ready infrastructure, registry currently empty |

---

## 🔴 STUB — Boilerplate only

### HexStrike v2 refactor (5% complete)
| File | Lines | Status |
|------|-------|--------|
| `mcp/hexstrike_v2/recon/nmap_tool.py` | 85 | Auto-extracted template, `# TODO: Extract implementation` |
| `mcp/hexstrike_v2/recon/amass_tool.py` | 85 | Same template |
| `mcp/hexstrike_v2/recon/dnsenum_tool.py` | 85 | Same template |
| `mcp/hexstrike_v2/recon/masscan_tool.py` | 85 | Same template |
| `mcp/hexstrike_v2/recon/nmap_advanced_tool.py` | 85 | Same template |
| `mcp/hexstrike_v2/recon/subfinder_tool.py` | 85 | Same template |
| `mcp/hexstrike_v2/scanning/*` (3 tools) | 85 each | Same template |
| `mcp/hexstrike_v2/web/*` (6 tools) | 85 each | Same template |
| `mcp/hexstrike_v2/exploitation/*` (2 tools) | 85 each | Same template |

**17 tools extracted as stubs / 156 total in `hexstrike-ai/hexstrike_server.py`** (the legacy 17,289-line monolith). Refactor migration is ~5% complete. `hexstrike_v2` import: **OK** (psutil==5.9.8 in requirements.txt). Stubs are templates only — no real implementation.

### Other stubs
| Item | File | Issue |
|------|------|-------|
| Multimodal endpoints | `api/routes/multimodal.py` | Stub responses (no real provider integration) |
| Voice routes | `api/routes/voice.py` | Gated behind `ENABLE_STUB_ROUTES` |
| Browser routes | `api/routes/browser.py` | Gated behind `ENABLE_STUB_ROUTES` |
| Playbooks | `api/routes/playbooks.py` | Static data |
| Venture | `api/routes/venture.py` | Static experiments |

---

## 🚧 SECONDARY (lower priority than canonical)

### React frontend (`frontend/`)
36 TS/TSX files. React 18 + Vite + Tailwind + Recharts. Beautiful UI.
- **Status**: 🟡 Wired, with some legacy route debt
- The client now uses same-origin auth and the remaining API surface is mostly v2/v3 mixed
- `Dashboard` still suppresses some fetch failures, so empty panels can hide backend drift
- **Action needed**: keep pruning stale `/api/v2/*` calls as the shell migrates to the stable surface

### React Native mobile (`mobile/`)
2,767 lines. Expo SDK 50.
- **Status**: 🟡 Secondary / legacy
- Kept for compatibility; Flutter remains canonical mobile
- Freeze this surface unless it is intentionally revived

---

## ⚠️ Known issues

### Security
The remaining high-risk auth drifts listed in earlier audits are now resolved:

- `api/routes/extensions.py` keeps router-level `Depends(require_auth)`.
- `api/routes/venture.py` imports `require_auth` hard and does not fall back to a permissive router.
- `api/routes/metrics_mobile.py` no longer has a silent bypass when `BEA_API_TOKEN` is absent.
- `api/main.py` fails closed in production if the access-enforcement middleware cannot load.

The residual security debt is now concentrated in the broader exception-swallows / legacy API surface, not in these auth entry points.

### Code quality
- Bare `except Exception: pass` patterns reduced to ~0 in source; remaining silent paths use structured `swallowed_exception` logs.
- 4 copies of `_check_auth` (1 canonical + 3 local in routes)
- `class Mission` still exists in more than one layer for now
- `_extract_final_output` duplicate already removed

### Repo hygiene
- `.env.agents` is not present in the current tree
- 3 unused dependencies in `requirements.txt`: `beautifulsoup4`, `lxml`, `pandas`
- All critical dependencies present: `psutil==5.9.8`, `structlog==25.5.0`, `langchain==1.3.9` ✅
- Current versions: `pytest==9.0.3`, `fastapi==0.137.1`, `starlette==1.3.1` ✅
- `hexstrike_v2` import: **OK** (psutil present) — stubs are 5% implemented, not runtime-active
- **P1 debt:** `core.policy.policy_engine.get_policy_engine` referenced in `tool_executor.py:733` uses wrong path (`core/policy/policy_engine.py` does not exist; real file is `core/policy_engine.py` and lacks `get_policy_engine`). Policy check fails silently for all tools; high-risk tools (`shell_execute`, `code_execute`) fail-closed as fallback.

### CI gates
- `ruff check .` is **blocking**
- `mypy` runs as a **delta gate** via `scripts/check_mypy_baseline.py`
- Coverage gate is **blocking** with `--cov-fail-under=60`
- `except/pass`, test marker, Bandit, and pip-audit debt are protected by ratchet baselines
- Wheel build is checked in CI and in full local validation when `build` is installed
- `pytest` blocks merge
- `scripts/validate_local.py` mirrors the key gates locally

### Docker
- Dockerfile runs as non-root user `bea` (`USER bea` line 69)
- Health endpoint in Dockerfile points to `/health`; verify `compose.prod.yml` alignment

### Tests
- **Gate tests: current hardening lane green** ✅
- Full suite: ~4730 pass / 170 fail (most failures are stale tests for deleted UI patterns)

---

## Maturity summary

| Maturity | Components | LOC estimate |
|----------|-----------|--------------|
| 🟢 PROVEN | Cognitive core, kernel, execution, auth, gate tests, observability store, eval publisher, plugin signatures | ~50,000 |
| 🟡 WIRED | MemoryFacade, MCP (manifests + signed tool loader), connectors, business handlers, plugins (signed) | ~10,000 |
| 🔵 SCAFFOLDING | business top-level, marketplace, data intelligence, desktop_env | ~3,500 |
| 🔴 STUB | HexStrike v2 tools, multimodal endpoints, voice, browser | ~2,000 |
| ⚫ PLANNED | Full HexStrike v2 split, Stripe integration hardening, deploy automation | — |

**Bottom line**: The Bea cognitive core is **PROVEN and stable**. The business automation layer is **scaffolding being progressively wired in**. MCP and plugin layers now have signatures. HexStrike v2 is staged for external extraction under `subprojects/hexstrike_v2/`.

---

## Task 6 — Observability & public surface

| # | Item | Status |
|---|------|--------|
| 6.1 | OpenTelemetry tracing shim (`core/observability/tracing.py`, wired in startup) | 🟢 Done |
| 6.2 | Eval scores auto-published (`core/observability/eval_publisher.py`, `GET/POST /api/v1/evaluations`) | 🟢 Done |
| 6.3 | V1 → V2 migration guide endpoint (`GET /api/v1/migration`, sunset 2026-10-01) | 🟢 Done |
| 6.4 | Plugin registry signatures (`plugins/signatures.py`, metadata signed, registry verifies) | 🟢 Done |
| 6.5 | Canonical frontend ADR-002 (web SPA canonical; Flutter/React Native not in this repo) | 🟢 Done |
| 6.6 | HexStrike v2 staged for split (`subprojects/hexstrike_v2/`, vendored module deprecated) | 🟡 In progress |

---

## How to use this file

- **New contributor**: Read this first. Understand which components are PROVEN vs SCAFFOLDING.
- **Before deleting code**: Check if it's marked SCAFFOLDING — those files are pre-positioned for integration.
- **Before claiming a feature**: Verify the maturity level here.
- **Before running tests**: Gate tests must pass. Full suite has ~170 known stale failures (documented in CODE_REVIEW.md).

Last updated: 2026-06-20
