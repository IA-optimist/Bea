# Current Memory Architecture - Visual Map

## System Dependency Graph

```
                    ┌─────────────────────────────────────────┐
                    │        AGENT RUNTIME                    │
                    │  (orchestrator, mission_system, etc.)   │
                    └─────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
        ┌────────────────────┐ ┌────────────────┐ ┌────────────────┐
        │  memory_facade.py  │ │  memory_bus.py │ │ Direct Imports │
        │   (19 imports)     │ │  (9 imports)   │ │  (scattered)   │
        └────────────────────┘ └────────────────┘ └────────────────┘
                    │                 │                 │
        ┌───────────┼─────────────────┼─────────────────┘
        │           │                 │
        ▼           ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ vector_memory│ │knowledge_mem │ │decision_mem  │ │improvement   │
│  (533 LOC)   │ │  (277 LOC)   │ │  (282 LOC)   │ │_memory       │
│  11 imports  │ │  11 imports  │ │  16 imports  │ │  (333 LOC)   │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
        │                 │                 │
        ▼                 ▼                 ▼
┌────────────────────────────────────────────────────────────────┐
│                    STORAGE BACKENDS                            │
│  PostgreSQL │ Qdrant │ Redis │ SQLite │ JSON/JSONL            │
└────────────────────────────────────────────────────────────────┘
```

## Parallel Systems (No Coordination)

### Vector Storage Implementations
```
┌─────────────────────────────────────────────────────────────────┐
│                    VECTOR STORAGE (4 parallel)                  │
├─────────────────────────────────────────────────────────────────┤
│ 1. memory/vector_memory.py     → JSON + HuggingFace embeddings │
│ 2. memory_bus.pgvector         → PostgreSQL pgvector extension │
│ 3. memory_system.py (Qdrant)   → Qdrant + Ollama embeddings    │
│ 4. continual_memory.py (Qdrant)→ Qdrant + experience replay    │
└─────────────────────────────────────────────────────────────────┘
```

### Mission Memory Variants
```
┌─────────────────────────────────────────────────────────────────┐
│                  MISSION MEMORY (3 parallel)                    │
├─────────────────────────────────────────────────────────────────┤
│ 1. core/mission_memory.py           → General mission results  │
│ 2. core/business/mission_memory.py  → Business mission traces  │
│ 3. core/planning/execution_memory.py→ Plan execution history   │
└─────────────────────────────────────────────────────────────────┘
```

### Improvement Memory Systems
```
┌─────────────────────────────────────────────────────────────────┐
│               IMPROVEMENT MEMORY (2 separate)                   │
├─────────────────────────────────────────────────────────────────┤
│ 1. core/improvement_memory.py               (agent scoring)    │
│ 2. core/self_improvement/improvement_memory (pipeline history) │
│    → Different purposes, intentionally separate                │
└─────────────────────────────────────────────────────────────────┘
```

## Active Import Counts (by module)

```
memory_facade       ████████████████████ 19
decision_memory     ████████████████ 16
knowledge_memory    ███████████ 11
vector_memory       ███████████ 11
vault_memory        ███████████ 11
mission_memory      ██████████ 10
improvement_memory  ██████████ 10
memory_bus          █████████ 9
memory_system       ██ 2
continual_memory    ██ 2
```

## File Categorization by Status

### ⭐ CANONICAL (Must Keep - 3 files)
```
1. core/memory_facade.py    (730 LOC, primary interface)
2. memory/memory_bus.py     (841 LOC, backend aggregator)
3. memory/vector_memory.py  (533 LOC, vector backend)
```

### 🔧 SPECIALIZED (Keep Separate - 4 files)
```
4. memory/decision_memory.py                    (282 LOC)
5. core/improvement_memory.py                   (333 LOC)
6. core/self_improvement/improvement_memory.py  (198 LOC)
7. core/finance/finance_memory.py               (213 LOC)
```

### 🔀 MERGE INTO FACADE (8 files)
```
→ core/orchestration/memory_system.py      (655 LOC, tier logic)
→ core/orchestration/memory_retrieval.py   (329 LOC, scoring)
→ core/orchestration/continual_memory.py   (438 LOC, replay)
→ core/memory/memory_schema.py             (379 LOC, models)
→ core/memory/memory_layers.py             (229 LOC, layers)
→ memory/vault_memory.py                   (364 LOC, caching)
→ core/knowledge/memory_quality.py         (320 LOC, quality)
→ core/knowledge_memory.py                 (277 LOC, patterns)
```

### 🔀 MERGE INTO MISSION_MEMORY (2 files)
```
→ core/business/mission_memory.py     (193 LOC)
→ core/planning/execution_memory.py   (173 LOC)
```

### 🔀 MERGE AS CONTENT TYPES (4 files)
```
→ core/economic/strategic_memory.py    (262 LOC)
→ core/execution/strategy_memory.py    (226 LOC)
→ core/planning/learning_memory.py     (213 LOC)
→ core/self_improvement/lesson_memory.py (103 LOC)
```

### 🗑️ DELETE (4 files)
```
✗ core/memory.py                    (76 LOC, superseded)
✗ core/memory/vector_memory.py      (2 LOC, empty stub)
✗ core/tools/memory_toolkit.py      (2 LOC, re-export)
✗ memory/agent_memory.py            (202 LOC, audit needed)
```

## Backend Distribution

| Backend | Files Using | Purpose |
|---------|-------------|---------|
| **JSONL** | 12 files | Append-only logs, decision history |
| **JSON** | 8 files | Structured persistence, config |
| **SQLite** | 3 files | Transactional storage, improvement tracking |
| **PostgreSQL** | 3 files | Distributed storage, vault backend |
| **Qdrant** | 2 files | Vector search, embeddings |
| **Redis** | 2 files | Working memory, cache L0 |
| **In-Memory** | 3 files | Temporary caches, fast access |

## Content Type Coverage

### Currently Supported (memory_facade)
```
✓ solution          → memory_toolkit, memory_bus
✓ error             → memory_toolkit, memory_bus
✓ patch             → memory_bus_patches, memory_toolkit
✓ decision          → decision_memory, knowledge_jsonl
✓ pattern           → knowledge_memory, knowledge_jsonl
✓ objective         → objective_store
✓ mission_outcome   → knowledge_jsonl
✓ knowledge         → knowledge_memory, memory_bus
✓ failure           → knowledge_jsonl, memory_bus
✓ general           → memory_bus, memory_toolkit
```

### Missing (need to add)
```
✗ strategy          → execution/strategy_memory.py
✗ execution         → planning/execution_memory.py
✗ learning          → planning/learning_memory.py
✗ improvement       → improvement tracking
✗ financial         → finance/finance_memory.py
✗ business_mission  → business/mission_memory.py
```

## Import Hotspots (files with most memory imports)

```
core/mission_system.py        → 8 memory imports
core/memory_facade.py         → 6 memory imports
core/orchestration/...        → 5 memory imports
core/action_executor.py       → 3 memory imports
core/tool_executor.py         → 3 memory imports
```

## Critical Paths (most used memory systems)

### Path 1: Mission Execution
```
mission_system → memory_facade → memory_bus → vector_memory
                                           → decision_memory
                                           → mission_memory
```

### Path 2: Agent Learning
```
learning_loop → improvement_memory → SQLite
              → memory_facade → knowledge_memory
```

### Path 3: Tool Execution
```
tool_executor → memory_toolkit → memory_facade → memory_bus
```

## Summary Statistics

| Metric | Value |
|--------|-------|
| **Total Memory Files** | 26 |
| **Total Lines of Code** | ~7,739 |
| **Total Import References** | 206 |
| **Backend Technologies** | 7 |
| **Overlapping Systems** | 9 (vector: 4, mission: 3, improvement: 2) |
| **Target File Count** | 5-7 |
| **Expected LOC Reduction** | ~40% |
| **Expected Import Reduction** | ~60% |

---

**Generated:** 2026-04-11  
**Audit Status:** Complete  
**Next Action:** Review MEMORY_CONSOLIDATION_PLAN.md
