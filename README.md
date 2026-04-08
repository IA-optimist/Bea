# JarvisMax

> Autonomous AI orchestration system — cognitive core + business automation scaffolding.

**Version**: 1.0.0 · **Status**: Internal beta (Jarvis cognitive core PROVEN, business layer WIP) · **License**: MIT

---

## What this is

JarvisMax has two layers with very different maturity:

### 🟢 Jarvis Cognitive Core — PROVEN

A mission orchestration system with real cognitive features:

- **MetaOrchestrator** — 12-phase mission lifecycle (classify → plan → route → retrieve memory → reason → execute → learn)
- **ConfidencePolicy** — 5 tiers (PROCEED / CONTEXT / CAUTIOUS / DECOMPOSE / ABORT) that actually gate execution
- **MemoryRetrieval** — pre-planning lesson injection from past failures and successes
- **MissionReasoningState** — build initial/target state, track expected vs observed post-execution
- **LLM Factory** — provider routing (OpenAI / Anthropic / OpenRouter / Ollama) with circuit breaker
- **Self-improvement** — sandbox-validated patch promotion pipeline
- **Kernel layer** — 19 capabilities, 5 memory types, contracts, policy, learning
- **Auth** — layered middleware + per-route `Depends(require_auth)`, `hmac.compare_digest`, JWT HS256, access tokens

**Proof**: 802/802 gate tests pass. 557 routes load at boot.

### 🚧 Business Automation Layer — WIP

Scaffolding being progressively wired into the orchestrator:

- **Business Engine** — opportunity scanner (Product Hunt / Reddit / HN) wired; product builder generates HTML templates; deploy is TODO
- **Tax Optimizer** — France compliance calculation, wired via `business.optimize_taxes` handler
- **HexStrike v1** — 150+ pentest tools (legacy monolith, registered but not orchestrated)
- **HexStrike v2** — modular refactor in progress (17 tool files, currently template stubs)
- **SOC Service** — standalone class, orchestration WIP
- **Data Intelligence** — service class ready, scanning logic WIP
- **Agent Marketplace** — schema defined, marketplace WIP
- **React Frontend** — UI complete, backend integration WIP (some endpoints mismatched)
- **React Native Mobile** — scaffolding, secondary to the Flutter canonical app

See [docs/STATUS.md](docs/STATUS.md) for honest per-component maturity.

---

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/UniTy01/Jarvismax-master.git
cd Jarvismax-master
cp .env.example .env
# Edit .env: set at least ANTHROPIC_API_KEY (or another LLM key) + JARVIS_SECRET_KEY

# 2. Start Qdrant (required for memory)
docker run -d -p 6333:6333 qdrant/qdrant:v1.9.7

# 3. Install and run
pip install -r requirements.txt
pip install langchain-anthropic   # or langchain-openai if using OpenRouter
python main.py

# 4. Verify
curl http://localhost:8000/api/v3/system/readiness
```

Full guide: [docs/QUICKSTART.md](docs/QUICKSTART.md)

Docker stack: `docker-compose up -d`

---

## Repository layout

```
main.py                    # Canonical entrypoint (kernel boot + FastAPI startup)
api/                       # FastAPI app (55+ routers, 548 endpoints)
  main.py                  # App init, middleware stack, router mounts
  routes/                  # 53 route modules
  _deps.py, auth.py        # Auth dependencies, JWT, constant-time compare
  access_enforcement.py    # Middleware token validation
  middleware.py            # Auth middleware, rate limiting, security headers

core/                      # Cognitive core (346 files)
  meta_orchestrator.py     # Mission lifecycle (1973 lines, 12 phases)
  orchestration/           # Confidence policy, memory retrieval, reasoning state
  llm_factory.py           # Provider routing, Ollama circuit breaker
  self_improvement/        # Patch promotion pipeline (sandbox + tests)
  mcp/                     # MCP registry

kernel/                    # Kernel layer (50 files)
  runtime/                 # boot.py, kernel.py — JarvisKernel singleton
  memory/                  # 5-type memory interface + registration slots
  capabilities/            # 19 registered capabilities
  evaluation/, learning/, planning/   # Wired to core via registration slots
  contracts/               # Type definitions

executor/                  # Execution layer
  execution_engine.py      # Task queue (heapq, retry, timeout)
  runner.py                # ActionExecutor (10 action types, whitelist/blacklist)
  supervised_executor.py   # Approval gate wrapping
  capability_dispatch.py   # Native / plugin / MCP routing

agents/                    # Agent crew (36 files)
  crew.py                  # BaseAgent + 9 core agents
  registry.py              # AGENT_CLASSES
  jarvis_team/             # Architect, Coder, Reviewer
  autonomous/              # Devin-like agent

business/                  # Business layer (35 files, scaffolding WIP)
  automation/              # Opportunity scanner (WIRED), product builder (STUB)
  legal/                   # Compliance checker
  revenue/                 # Revenue engine (dataclasses)
  fiscal/                  # Tax optimizer (WIRED)

mcp/                       # MCP sidecars
  hexstrike-ai/            # Legacy monolith (734KB)
  hexstrike_v2/            # Modular refactor WIP (17 stubs)

static/
  app.html                 # Canonical web SPA (French, 973 lines)

jarvismax_app/             # Flutter mobile app (CANONICAL per docs)
mobile/                    # React Native mobile (secondary, WIP)
frontend/                  # React web dashboard (WIP, API mismatch)

tests/                     # 216 test files (802 gate tests pass)
docker/, docker-compose*.yml  # Docker deployment
```

---

## Documentation

- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** — install + first mission
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — real architecture (single source of truth)
- **[docs/API_REFERENCE.md](docs/API_REFERENCE.md)** — all endpoints documented
- **[docs/STATUS.md](docs/STATUS.md)** — honest per-component maturity
- **[docs/CODE_REVIEW.md](docs/CODE_REVIEW.md)** — 2026-04-08 full code audit
- **[CHANGELOG.md](CHANGELOG.md)** — release history

---

## Testing

```bash
# Gate tests (must pass — 802 tests)
python -m pytest tests/test_terminal_state_truth.py \
                 tests/test_canonical_mission_persistence.py \
                 tests/test_hierarchical_planner.py \
                 tests/test_production_hardening_p34.py \
                 tests/test_mission_engine.py \
                 tests/test_capability_routing.py \
                 tests/test_kernel.py \
                 tests/test_self_improvement_engine.py \
                 tests/test_secret_vault.py \
                 tests/test_identity_manager.py \
                 tests/test_evaluation_engine.py \
                 tests/test_economic_cognition.py \
                 tests/test_surgical_hardening.py \
                 tests/test_self_improvement_execution.py \
                 tests/test_cognitive_upgrade.py \
                 tests/test_readiness_endpoint.py \
                 tests/test_access_enforcement.py \
                 tests/test_api_structure.py

# Full suite (non-gated)
python -m pytest tests/ --ignore=tests/smoke
```

Current state: **802/802 gate tests pass**, full suite 4700+ passing with ~170 stale UI test failures (documented in CODE_REVIEW.md).

---

## Contributing

1. Read [docs/STATUS.md](docs/STATUS.md) to understand what is PROVEN vs WIP.
2. Don't delete files marked `# WIP — scaffolding awaiting orchestrator integration`.
3. Gate tests must stay green.
4. New routes need per-route auth (`Depends(require_auth)` or `dependencies=[Depends(require_auth)]` at the router level).
5. No `except Exception: pass` without logging.

---

## License

MIT — see [LICENSE](LICENSE).
