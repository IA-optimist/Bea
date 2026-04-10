# Memory System Consolidation Plan
**Date:** 2026-04-10  
**Status:** APPROVED — Ready for implementation

---

## Problem Statement

JarvisMax currently has **37 memory-related files** across 10+ independent systems:

- `core/memory.py`, `core/memory_facade.py` (facade pattern)
- `memory/vault_memory.py` (long-term storage)
- `core/mission_memory.py` (mission context)
- `core/knowledge_memory.py`, `core/intelligent_memory.py` (knowledge graph)
- `core/improvement_memory.py`, `core/self_improvement/lesson_memory.py` (learning)
- `core/orchestration/memory_system.py`, `core/orchestration/continual_memory.py` (orchestration)
- `core/memory/vector_memory.py`, `memory/vector_memory.py` (2 vector implementations)
- `core/business/mission_memory.py`, `core/finance/finance_memory.py` (domain-specific)
- `memory/agent_memory.py`, `memory/decision_memory.py`, `memory/failure_memory.py` (specialized)

**Issues:**
- No single source of truth
- Overlapping responsibilities
- Impossible to trace where data is stored
- Performance bottlenecks (multiple serialization layers)
- Maintenance nightmare (33% of memory files are legacy/duplicates)

---

## Target Architecture

### Single Unified System: MemoryFacade + PostgreSQL Backend

```
┌─────────────────────────────────────────┐
│  APPLICATION LAYER                      │
│  (core/, api/, agents/)                 │
└─────────────────┬───────────────────────┘
                  │
       ┌──────────▼──────────┐
       │   memory_facade.py  │  ← SINGLE API
       └──────────┬──────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Mission  │ │ Knowledge│ │ Learning │
│ Memory   │ │  Memory  │ │  Memory  │
│ (Postgres│ │ (Postgres│ │ (Postgres│
│  + cache)│ │  + Qdrant│ │  + JSONL)│
└──────────┘ └──────────┘ └──────────┘
```

**Key Principles:**
1. **Single API:** All code imports `from core.memory_facade import get_memory_facade()`
2. **Backend agnostic:** Facade routes to appropriate storage (Postgres/Qdrant/file)
3. **Type-safe:** Pydantic models for all memory entries
4. **Layered caching:** Redis → Postgres → Qdrant (hot → warm → cold)

---

## Migration Path (4 Phases)

### Phase 1: Consolidate Core (Week 1)
**Goal:** Unify mission/knowledge/improvement into memory_facade

**Actions:**
1. ✅ `memory_facade.py` becomes canonical interface
2. Move `mission_memory.py` → `memory_facade._mission_layer`
3. Move `knowledge_memory.py` → `memory_facade._knowledge_layer`
4. Move `improvement_memory.py` → `memory_facade._learning_layer`
5. Deprecate `core/memory.py` (redirect imports to facade)

**Files to merge:** 12 files → 1 facade

**Breaking changes:** None (facade exposes same methods)

---

### Phase 2: PostgreSQL Backend (Week 2)
**Goal:** Replace in-memory stores with PostgreSQL

**Actions:**
1. ✅ Apply migrations 001-003 (schema already created)
2. Implement `PostgresMemoryBackend` class
3. Wire `vault_memory` table (migration 002) to facade
4. Add Redis L1 cache layer
5. Benchmark: target <10ms read, <50ms write

**Files to modify:** 3 (memory_facade, _deps, config)

**Breaking changes:** None (transparent backend swap)

---

### Phase 3: Vector Search (Week 3)
**Goal:** Consolidate 2 vector_memory implementations into Qdrant

**Actions:**
1. Merge `core/memory/vector_memory.py` + `memory/vector_memory.py`
2. Wire to existing Qdrant container (already in docker-compose)
3. Implement semantic search in `memory_facade.search_similar()`
4. Deprecate `core/tools/memory_toolkit.py` (use facade methods)

**Files to merge:** 5 files → 1 backend

**Breaking changes:** None (facade API unchanged)

---

### Phase 4: Cleanup Legacy (Week 4)
**Goal:** Remove redundant/dead code

**Actions:**
1. Archive to `core/_legacy/memory/`:
   - `core/intelligent_memory.py`
   - `core/orchestration/continual_memory.py`
   - `memory/legacy_knowledge_memory.py`
   - `core/memory/vector_memory_legacy.py`
   - `core/tools/memory_toolkit_legacy.py`
2. Update all imports to use `memory_facade`
3. Full test suite pass (5573 tests)
4. Benchmark: memory operations <100ms p95

**Files to archive:** 15+ files

**Breaking changes:** Legacy imports removed (no active usage confirmed)

---

## Success Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Memory files | 37 | 8 | -78% |
| Import complexity | 10+ systems | 1 facade | ✓ |
| Write latency (p95) | 200ms+ | <50ms | ✓ |
| Read latency (p95) | 150ms+ | <10ms | ✓ |
| Test coverage | 67% | 85%+ | ✓ |
| LOC (memory code) | ~8,500 | <3,000 | -65% |

---

## Risk Mitigation

**Risk:** Data loss during migration  
**Mitigation:** 
- Phase 2 runs dual-write (in-memory + Postgres) for 1 week
- Automated consistency checker compares both stores
- Rollback script ready

**Risk:** Performance regression  
**Mitigation:**
- Redis L1 cache ensures <10ms reads
- Benchmark suite runs on every commit
- Circuit breaker on Postgres failures (fallback to in-memory)

**Risk:** Breaking existing code  
**Mitigation:**
- Facade maintains backward-compatible API
- Deprecation warnings for 2 weeks before removal
- Full test suite gates every phase

---

## Implementation Schedule

| Week | Phase | Owner | Blocker |
|------|-------|-------|---------|
| 1 | Consolidate Core | Hermes | None |
| 2 | PostgreSQL Backend | Hermes | Phase 1 |
| 3 | Vector Search | Hermes | Phase 2 |
| 4 | Cleanup Legacy | Hermes | Phase 3 |

**Start date:** 2026-04-10  
**Target completion:** 2026-05-08 (28 days)

---

## Rollback Plan

If Phase 2/3 fails:
1. Revert `memory_facade` to in-memory backend
2. Keep dual-write enabled (no data loss)
3. Investigate bottleneck (query time, connection pool, cache miss rate)
4. Retry with optimizations

Rollback window: <5 minutes (environment variable toggle)

---

## Appendix: File Inventory

### Keep (8 files)
- `core/memory_facade.py` — Single API
- `memory/vault_memory.py` — Postgres backend adapter
- `core/mission_memory.py` — Mission context layer
- `core/knowledge_memory.py` — Knowledge graph layer
- `core/improvement_memory.py` — Learning layer
- `memory/memory_bus.py` — Event-driven updates
- `core/memory/memory_schema.py` — Pydantic models
- `core/memory/memory_layers.py` — Layered cache logic

### Archive (15 files)
- `core/memory.py` → Redirect to facade
- `core/intelligent_memory.py` → Unused (0 imports)
- `core/orchestration/continual_memory.py` → Redundant with mission_memory
- `memory/legacy_knowledge_memory.py` → Dead code
- `core/memory/vector_memory_legacy.py` → Superseded by Qdrant
- `core/tools/memory_toolkit_legacy.py` → Dead code
- `memory/agent_memory.py` → Merge into mission_memory
- `memory/decision_memory.py` → Merge into mission_memory
- `memory/failure_memory.py` → Merge into improvement_memory
- `memory/patch_memory.py` → Merge into improvement_memory
- `memory/project_memory.py` → Merge into mission_memory
- `core/business/mission_memory.py` → Duplicate of core/mission_memory
- `core/finance/finance_memory.py` → Keep (domain-specific, used by finance agent)
- `core/orchestration/memory_system.py` → Merge into memory_facade
- `core/orchestration/memory_retrieval.py` → Merge into memory_facade

### Delete (8 files — tests/backups)
- `core/memory/vector_memory.py` → Duplicate
- `memory/vector_memory.py` → Keep (wire to Qdrant)
- `core/execution/strategy_memory.py` → Unused
- `core/economic/strategic_memory.py` → Unused
- `core/planning/execution_memory.py` → Unused
- `core/planning/learning_memory.py` → Duplicate
- `core/knowledge/memory_quality.py` → Test utility, keep
- `core/self_improvement/lesson_memory.py` → Keep (specialized)

---

**Approval:** UniTy (Maxence)  
**Next step:** Execute Phase 1 (consolidate core)
