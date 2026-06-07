# BeaMax — Component Status

> Honest per-component maturity rating. Last verified: 2026-04-08, SHA `889a1c3`.
> Verified by direct code reading + 5 audit agents + gate test results.

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
| Gate tests | **802/802 pass** ✅ |
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
| Web SPA | `static/app.html` (973 lines) | Single canonical web app, French, sessionStorage auth |

### Mobile canonical interface
| Component | File | Evidence |
|-----------|------|----------|
| Flutter app | `beamax_app/` (~7,400 lines) | Documented as canonical in all docs (ROADMAP, RUNTIME_TRUTH, etc.). Secure storage, token refresh, WS reconnect. |

---

## 🟡 WIRED — Connected, not fully proven

| Component | File | Why wired vs proven |
|-----------|------|---------------------|
| MemoryFacade | `core/memory_facade.py` | Registered in main.py:189-218 with K1 wrapper. Used by retrieval. Not stress-tested with live Qdrant. |
| MCP server (bea_mcp) | `bea_mcp/bea_mcp_server.py` | 3 read-only tools (memory_search, mission_status, list_missions). Untested with live MCP clients. |
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

**17 tools extracted as stubs / 156 total in `hexstrike-ai/hexstrike_server.py`** (the legacy 17,289-line monolith). Refactor migration is ~5% complete. **`hexstrike_v2` import currently fails** because `psutil` is missing from `requirements.txt`.

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
- **Status**: 🔴 Backend integration BROKEN
- API client calls `/api/v2/system/status` and `/api/v2/products/deploy` — these routes do not exist in v2
- `.catch(() => null)` swallows errors, dashboard shows empty data
- **Action needed**: Update `frontend/src/api/client.ts` BASE_URL or backend routes

### React Native mobile (`mobile/`)
2,767 lines. Expo SDK 50.
- **Status**: 🔵 Scaffolding, secondary to Flutter
- Same broken API client as frontend (`/api/v2/*` mismatch)
- Not documented anywhere — Flutter (`beamax_app/`) remains canonical
- **Action needed**: Decide canonical mobile (Flutter or React Native) or document coexistence

---

## ⚠️ Known issues

### Security (4 issues)
| # | File | Issue | Severity |
|---|------|-------|----------|
| 1 | `api/routes/extensions.py` | No `Depends()` at router level — relies entirely on middleware | HIGH |
| 2 | `api/routes/venture.py:26-29` | `_auth = None` if import fails → fail-open | HIGH |
| 3 | `api/routes/metrics_mobile.py:52-54` | `if t:` — silent bypass when `BEA_API_TOKEN` not set | HIGH |
| 4 | `api/main.py:75-81` | Middleware ImportError logged but app starts in degraded mode | MEDIUM |

### Code quality
- 333 `except Exception: pass` patterns in `core/` and `api/` (silent failures)
- 4 copies of `_check_auth` (1 canonical + 3 local in routes)
- 2 incompatible `class Mission` definitions (kernel + business)
- `_extract_final_output` had a duplicate (now fixed)

### Repo hygiene
- `.env.agents` committed (placeholders only, but bad practice)
- 3 unused dependencies in `requirements.txt`: `beautifulsoup4`, `lxml`, `pandas`
- Missing dependencies: `psutil` (causes `hexstrike_v2` import failure), `structlog`, `langchain_*`
- Outdated versions: `pytest==7.4.4` (current 8.x), `fastapi==0.109.0` (current 0.115.x)

### CI gates
- `ruff check . --exit-zero` — always passes
- `mypy core/ --ignore-missing-imports` with `continue-on-error: true` — always passes
- Coverage upload with `continue-on-error: true` — always passes
- Only `pytest` actually blocks merge

### Docker
- Container runs as **root** (no `USER appuser`)
- Health endpoints inconsistent: `/api/v2/health` (Dockerfile) vs `/health` (compose.prod.yml)

### Tests
- **Gate tests: 802/802 pass** ✅
- Full suite: ~4730 pass / 170 fail (most failures are stale tests for deleted UI patterns)

---

## Maturity summary

| Maturity | Components | LOC estimate |
|----------|-----------|--------------|
| 🟢 PROVEN | Cognitive core, kernel, execution, auth, gate tests | ~50,000 |
| 🟡 WIRED | MemoryFacade, MCP, connectors, business handlers | ~10,000 |
| 🔵 SCAFFOLDING | business top-level, marketplace, data intelligence, desktop_env, plugins | ~3,500 |
| 🔴 STUB | HexStrike v2 tools, multimodal endpoints, voice, browser | ~2,000 |
| ⚫ PLANNED | Full HexStrike v2 (139 tools), Stripe integration, deploy automation | — |

**Bottom line**: The Bea cognitive core is **PROVEN and stable**. The business automation layer is **scaffolding being progressively wired in**. The system is honest about this distinction in this STATUS.md (READMEs from earlier merges may overclaim — defer to this file).

---

## How to use this file

- **New contributor**: Read this first. Understand which components are PROVEN vs SCAFFOLDING.
- **Before deleting code**: Check if it's marked SCAFFOLDING — those files are pre-positioned for integration.
- **Before claiming a feature**: Verify the maturity level here.
- **Before running tests**: Gate tests must pass. Full suite has ~170 known stale failures (documented in CODE_REVIEW.md).

Last updated: 2026-04-08
