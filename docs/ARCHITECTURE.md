# JarvisMax — Architecture Reality (Post-Cleanup 2026-04-06)

## Overview

JarvisMax is a multi-agent AI system with a Python backend (FastAPI), Flutter mobile app, and Docker infrastructure.

```
User → Flutter App → FastAPI (api/) → MetaOrchestrator → Agents → Tools → LLM
                        ↓                    ↓
                   WebSocket              Memory Facade
                   (real-time)            (multi-backend)
```

## Core Execution Path

The **canonical** mission execution path:

```
1. API receives mission    → api/routes/missions.py
2. Kernel boots context    → kernel/runtime/boot.py
3. MetaOrchestrator routes → core/meta_orchestrator.py (CANONICAL)
   ├── Simple missions     → direct agent dispatch
   ├── Complex missions    → OrchestratorV2 (DAG + budget)
   └── LangGraph missions  → core/orchestrator_lg/ (optional)
4. Planning                → core/planning/plan_runner.py
5. Agent execution         → agents/agent_factory.py → BaseAgent subclasses
6. Tool execution          → core/tool_executor.py → core/tools/*
7. Memory storage          → core/memory_facade.py (unified interface)
8. Response                → WebSocket + REST
```

## Key Components

### Orchestration (3833 lines, 3 levels)
| Component | File | Role | Status |
|-----------|------|------|--------|
| **MetaOrchestrator** | `core/meta_orchestrator.py` | **CANONICAL** — routes all missions | ✅ Active |
| OrchestratorV2 | `core/orchestrator_v2.py` | Budget/DAG for complex missions (used BY meta) | ✅ Active |
| JarvisOrchestrator | `core/orchestrator.py` | **DEPRECATED** — legacy, inner delegate of V2 | ⚠️ Legacy |
| LangGraph flow | `core/orchestrator_lg/` | Optional LangGraph-based execution | ⚠️ Optional |

### Memory (multi-backend)
| Backend | File(s) | Purpose |
|---------|---------|---------|
| **Memory Facade** | `core/memory_facade.py` | **CANONICAL** — unified query surface | 
| Memory Bus | `memory/memory_bus.py` | Multi-backend router |
| Vector Memory | `memory/vector_memory.py` | Qdrant-based semantic search |
| Vault Memory | `memory/vault_memory.py` | Persistent key-value store |
| Decision Memory | `memory/decision_memory.py` | Decision pattern tracking |
| SQLite | `core/db.py` | Local fallback (4 tables) |
| PostgreSQL | `docker/postgres/init.sql` | Production store (aligned) |

### Agents (36 files in agents/)
| Type | Key Files | Count |
|------|-----------|-------|
| Base classes | `agents/crew.py` (BaseAgent ABC), `agents/agent_factory.py` | 2 |
| Jarvis Team | `agents/jarvis_team/` (git-aware agents) | ~10 |
| Business | `business_agents/` (content, quotes, support) | ~12 |
| Autonomous | `agents/autonomous/` (DevinAgent, OpenHands) | 2 |
| Specialized | debug, evaluator, monitoring, web_scout, etc. | ~20 |

### API (74 files)
- **50+ routers** mounted with try/except (fail-open)
- **Auth**: JWT tokens via `/auth/token` + `/auth/refresh`
- **WebSocket**: `/ws/stream` for real-time updates
- **Readiness**: `/api/v3/system/readiness` (runtime introspection)

### Infrastructure
| Service | Purpose | Usage Level |
|---------|---------|-------------|
| PostgreSQL 16 | Primary DB (production) | Medium (5 modules) |
| Redis 7 | Rate limiting | Low (1 module) |
| Qdrant | Vector search | High (194 references) |
| Ollama | Local LLM inference | Optional |
| n8n | Workflow automation | Optional |
| Caddy | Reverse proxy + TLS | Active |

### Flutter App (`jarvismax_app/`)
- JWT auth with refresh tokens
- WebSocket for real-time mission updates
- Multiple connection profiles (emulator, local, tailscale, production)
- API service targeting `/api/v3/missions`

## Database Architecture

**Dual-DB design** (see `docs/DB_RECONCILIATION_PLAN.md`):
- **SQLite** (`workspace/jarvismax.db`): dev fallback, 4 tables
- **PostgreSQL**: production, 8+ tables (aligned with SQLite as of 2026-04-06)
- **Qdrant**: vector embeddings for semantic search

## Self-Improvement System

```
core/self_improvement/          ← V3 CANONICAL package
├── engine.py                   ← SelfImprovementEngine (main)
├── improvement_planner.py      ← Plans improvements
├── failure_collector.py        ← Collects failures for learning
├── lesson_memory.py            ← Stores lessons learned
└── legacy_adapter.py           ← Compat with V1/V2

core/self_improvement_loop.py   ← V3 loop implementation
core/self_improvement_engine.py ← Deprecated re-export shim
core/improvement_daemon.py      ← Background improvement process
core/improvement_memory.py      ← Improvement tracking (SQLite+PG)
core/improvement_detector.py    ← Detects improvement opportunities
core/improvement_proposals.py   ← Proposal store
```

## Test Coverage

- **233 test files** with `def test_` functions
- **8 files in CI** (360+ tests): terminal_state, mission_persistence, 
  hierarchical_planner, production_hardening, build_recovery, 
  mission_engine, capability_routing, execution_layer
- **Integration tests**: nightly with live stack + LLM

## Known Technical Debt

1. **orchestrator.py** (1184 lines): deprecated but still used as V2's inner delegate
2. **Dual BaseAgent**: `agents/crew.py` (ABC) vs `agents/agent_factory.py` (fallback)
3. **11 agent files with `pass` stubs**: method bodies not implemented
4. **50 routers fail-open**: silent degradation if a router crashes at import
5. **Redis underutilized**: only rate_limiter.py, despite Docker service running
6. **DATABASE_URL not set by default**: Postgres is configured but not connected
7. **capability_intelligence chain**: 2918 lines (3 files) with single-importeur chains

## File Count by Directory

```
core/          359 files   (orchestration, tools, planning, memory, etc.)
tests/         238 files   (unit + integration)
api/            74 files   (routes, middleware, auth)
kernel/         50 files   (runtime, policy, improvement)
agents/         36 files   (base, team, autonomous)
business/       29 files   (business logic)
executor/       25 files   (execution engine, supervisor)
memory/         15 files   (stores, bus, embeddings)
business_agents/ 12 files  (content, quotes, support)
tools/          11 files   (CLI tools, scripts)
```

**Total: 921 Python files** (down from 953 after cleanup)
