# Memory Consolidation Blueprint

**Date:** 2026-04-10  
**Status:** PLANNED (not yet implemented)  
**Priority:** P1 (after P0 security fixes complete)

## Problem Statement

BeaMax has **40 memory-related Python files** with overlapping responsibilities and no single source of truth:

```
core/memory_facade.py              # Unified interface (fail-open)
core/memory.py                     # Old interface
core/mission_memory.py             # Mission-specific storage
core/improvement_memory.py         # Self-improvement lessons
core/knowledge_memory.py           # Knowledge graph
core/orchestration/memory_system.py
core/orchestration/memory_retrieval.py
core/orchestration/continual_memory.py
core/tools/memory_toolkit.py       # Qdrant wrapper
core/business/mission_memory.py
core/economic/strategic_memory.py
core/finance/finance_memory.py
core/execution/strategy_memory.py
core/self_improvement/improvement_memory.py
core/self_improvement/lesson_memory.py
core/memory/vector_memory.py
core/memory/memory_layers.py
memory/memory_bus.py               # Main async memory orchestrator
memory/legacy/project_memory.py
... and 20+ more
```

### Current Issues

1. **Fragmentation**: 40 files, no canonical interface
2. **Duplication**: Same storage operations reimplemented 10+ times
3. **Inconsistent backends**: JSONL, Qdrant, PostgreSQL, in-memory dicts
4. **Silent failures**: All operations fail-open (catch Exception: pass)
5. **No caching**: Every retrieval hits disk/DB (no Redis L1)
6. **Dimensional chaos**: 384-dim, 768-dim, 1536-dim vectors mixed
7. **Write/read mismatch**: Writes go to Qdrant, reads from JSONL (audit finding)

### Audit Score Impact

- **Current score:** Memory operations work (JSONL fallback) but degraded
- **After consolidation:** +0.5 points (9.0 → 9.5/10)
- **Impact:** Better recall, faster retrieval, consistent storage

---

## Target Architecture

### Layer 1: Unified Facade (Single Entry Point)

**File:** `core/memory/unified_memory.py` (new)

```python
class UnifiedMemory:
    """Single canonical memory interface for BeaMax.
    
    All memory operations MUST go through this class.
    Replaces: memory_facade.py, memory.py, memory_bus.py
    """
    
    def __init__(self, settings, redis_client=None):
        self.postgres = PostgreSQLBackend(settings.database_url)
        self.vector = VectorBackend(settings.qdrant_url)
        self.cache = RedisCache(redis_client) if redis_client else None
    
    async def store(self, content: str, content_type: str, 
                    tags: list[str], metadata: dict) -> str:
        """Store with L1 cache + dual persistence (Postgres + Qdrant)."""
        
    async def search(self, query: str, content_type: str = None,
                     top_k: int = 5) -> list[MemoryEntry]:
        """Search with L1 cache lookup → vector similarity → Postgres fallback."""
    
    async def recall(self, mission_id: str = None, 
                     content_type: str = None) -> list[MemoryEntry]:
        """Recall mission history with cache-aside pattern."""
```

### Layer 2: Storage Backends

#### PostgreSQL (Structured Data)

**Table:** `memory_entries`

```sql
CREATE TABLE memory_entries (
    id UUID PRIMARY KEY,
    content TEXT NOT NULL,
    content_type VARCHAR(50) NOT NULL,  -- mission_outcome, failure, decision, etc.
    tags TEXT[],
    metadata JSONB,
    mission_id VARCHAR(16),
    project_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    importance FLOAT DEFAULT 0.5,
    INDEX idx_content_type (content_type),
    INDEX idx_mission_id (mission_id),
    INDEX idx_created_at (created_at DESC)
);
```

**Stores:**
- Mission outcomes (success/failure)
- Decisions (with confidence scores)
- Errors (for improvement loop)
- Strategic plans (from economic engine)
- Business opportunities (from pipeline)

#### Qdrant (Vector Similarity)

**Collection:** `beamax_memory` (384-dim, cosine similarity)

**Stores:**
- Semantic embeddings (all-MiniLM-L6-v2)
- Cross-references to Postgres via `entry_id` payload

**Use cases:**
- "Find similar past missions"
- "Recall solutions to related problems"
- "Discover patterns across failures"

#### Redis (L1 Cache)

**Keys:**
- `memory:mission:{mission_id}` → Recent mission memory (TTL 1h)
- `memory:search:{hash(query)}` → Search results (TTL 5min)
- `memory:hot:{content_type}` → Frequently accessed entries (TTL 1h)

**Eviction:** LRU with 256MB max memory

### Layer 3: Specialized Accessors

Keep domain-specific interfaces but route through UnifiedMemory:

```python
# core/mission_memory.py (simplified)
class MissionMemory:
    def __init__(self, unified: UnifiedMemory):
        self.unified = unified
    
    async def store_outcome(self, mission_id: str, result: str, 
                            status: str, confidence: float):
        return await self.unified.store(
            content=result,
            content_type="mission_outcome",
            tags=[status],
            metadata={"mission_id": mission_id, "confidence": confidence}
        )
```

**Keep (as thin wrappers):**
- `MissionMemory` → mission outcomes
- `ImprovementMemory` → failures/lessons
- `StrategicMemory` → business/economic plans

**Delete (merge into UnifiedMemory):**
- `memory_facade.py` (replaced)
- `memory_bus.py` (too complex, replaced)
- `memory_toolkit.py` (Qdrant wrapper moved to VectorBackend)
- All files in `core/_legacy/memory/`
- `memory/legacy/project_memory.py`

---

## Migration Plan

### Phase 1: Bootstrap UnifiedMemory (2-3 hours)

1. Create `core/memory/unified_memory.py`
2. Implement PostgreSQL backend (use existing schema)
3. Implement Qdrant backend (384-dim collection)
4. Implement Redis cache (optional, fail-open)
5. Add tests: store → retrieve → assert content match

### Phase 2: Migrate Core Operations (3-4 hours)

1. Update `MetaOrchestrator` to use UnifiedMemory
2. Update `ImprovementMemory` to wrap UnifiedMemory
3. Update `MissionMemory` to wrap UnifiedMemory
4. Run existing tests → fix failures

### Phase 3: Cleanup Legacy (1-2 hours)

1. Move `core/_legacy/memory/` to `archive/`
2. Delete `memory_facade.py` (replaced by unified_memory.py)
3. Delete `memory_bus.py` (replaced by unified_memory.py)
4. Update imports across codebase
5. Remove unused backends from routing

### Phase 4: Validation (1 hour)

1. Run full test suite (target: 90%+ pass)
2. Smoke test: create mission → store outcome → recall
3. Performance test: 1000 entries → search <100ms with cache

---

## Implementation Checklist

- [ ] Create `core/memory/unified_memory.py`
- [ ] Create `core/memory/backends/postgres.py`
- [ ] Create `core/memory/backends/vector.py`
- [ ] Create `core/memory/backends/redis_cache.py`
- [ ] Write tests: `tests/memory/test_unified_memory.py`
- [ ] Update `MetaOrchestrator._handle_success_outcome()`
- [ ] Update `MetaOrchestrator._handle_failed_outcome()`
- [ ] Update `ImprovementMemory` wrapper
- [ ] Update `MissionMemory` wrapper
- [ ] Delete `core/memory_facade.py`
- [ ] Delete `memory/memory_bus.py`
- [ ] Archive `core/_legacy/memory/`
- [ ] Update imports in 10+ affected files
- [ ] Run test suite: target 90%+ pass
- [ ] Smoke test E2E mission flow
- [ ] Performance benchmark: <100ms cached search

---

## Expected Outcomes

### Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Memory files | 40 | 8-10 | 75% reduction |
| Storage backends | JSONL, Qdrant, Postgres, in-memory | Postgres + Qdrant + Redis L1 | Unified stack |
| Recall latency | 50-200ms (disk I/O) | 1-5ms (Redis) / 20-50ms (miss) | 10-40x faster |
| Dimensional consistency | Mixed (384/768/1536) | 384-dim (all-MiniLM-L6-v2) | Consistent |
| Silent failures | Every operation fail-open | Fail-fast on write, fail-open on read | Better observability |
| Test coverage | ~60% (fragmented) | 85%+ (unified) | Better reliability |

### Business Value

- **Faster retrieval** → Better mission context → Higher success rate
- **Consistent storage** → Reliable recall → Better learning loop
- **Unified interface** → Easier to extend → Faster feature velocity
- **Reduced complexity** → Fewer bugs → Lower maintenance cost

---

## Risks & Mitigations

### Risk 1: Breaking Existing Code

**Mitigation:**
- Keep old interfaces as deprecated wrappers for 1 release
- Gradual migration: core → tools → legacy
- Comprehensive test coverage before deletion

### Risk 2: Performance Regression

**Mitigation:**
- Redis L1 cache (sub-ms hot reads)
- Benchmark before/after (1000 entry corpus)
- Rollback plan: keep old code in git tags

### Risk 3: Data Loss During Migration

**Mitigation:**
- Read-only migration first (dual-write to old + new)
- Verification: compare old vs new retrieval results
- Backup: export existing JSONL/Qdrant to archive

---

## Next Steps

1. **Review this blueprint** with team/stakeholders
2. **Approve scope** (estimated 8-10 hours work)
3. **Schedule migration** (after P0 security fixes complete)
4. **Assign owner** (AI agent + human review)
5. **Execute phases** 1-4 sequentially
6. **Deploy + monitor** for 1 week before cleanup

---

**Status:** Ready for execution (pending approval)  
**Owner:** TBD  
**Estimated effort:** 8-10 hours  
**Expected completion:** 1 week from approval
