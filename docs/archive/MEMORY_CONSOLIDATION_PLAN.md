# BEA MAX - Memory System Consolidation Plan

**Date:** 2026-04-11  
**Status:** Audit Complete - Ready for Implementation  
**Goal:** Consolidate 26 memory files → 3-5 core modules with clear separation of concerns

---

## Executive Summary

**Current State:** 26 memory-related Python files across 10+ distinct systems  
**Target State:** 3-5 core memory modules with unified interface  
**Primary Issues:**
- Overlapping functionality (4+ vector storage implementations)
- No clear source of truth (memory_facade intended but not fully adopted)
- Domain-specific memories duplicating base functionality
- Inconsistent backends (SQLite, PostgreSQL, Qdrant, JSON, in-memory)

**Recommended Approach:** Facade pattern with 3-tier architecture

---

## Current Architecture Analysis

### Memory System Inventory (26 Files)

#### **Core Infrastructure (8 files)**

1. **`core/memory_facade.py`** (730 LOC, 19 imports) ⭐ **CANONICAL**
   - **Purpose:** Unified memory interface, routes to backends
   - **Dependencies:** memory_bus, memory_toolkit, knowledge_memory, decision_memory
   - **Backend Routing:** Content-type based routing with fallback
   - **Status:** Intended as source of truth, partially adopted
   - **Keep:** YES - Primary facade

2. **`memory/memory_bus.py`** (841 LOC, 9 imports) ⭐ **CANONICAL**
   - **Purpose:** Multi-backend router (store, vector, patches, failures)
   - **Dependencies:** MemoryStore, VectorMemory, PatchMemory, FailureMemory
   - **Features:** Lazy backend init, unified search, patch context
   - **Status:** Active, well-integrated
   - **Keep:** YES - Backend aggregator

3. **`core/orchestration/memory_system.py`** (655 LOC, 2 imports)
   - **Purpose:** 3-level memory (working/episodic/semantic) with Qdrant
   - **Dependencies:** Qdrant, Redis, Ollama embeddings
   - **Features:** TTL-based working memory, importance scoring
   - **Status:** Sophisticated but underutilized
   - **Action:** MERGE into memory_facade as tier handler

4. **`core/orchestration/continual_memory.py`** (438 LOC, 2 imports)
   - **Purpose:** Experience replay buffer for catastrophic forgetting
   - **Dependencies:** Qdrant, Ollama
   - **Features:** Surprise scoring, prioritized replay, consolidation
   - **Status:** Specialized, minimal adoption
   - **Action:** MERGE into memory_system as replay module

5. **`memory/vector_memory.py`** (533 LOC, 11 imports) ⭐ **CANONICAL**
   - **Purpose:** Local vector store with sentence-transformers
   - **Dependencies:** HuggingFace API or local embeddings
   - **Features:** JSON persistence, TF-IDF fallback, deduplication
   - **Status:** Widely used, stable
   - **Keep:** YES - Core vector backend

6. **`core/memory/memory_schema.py`** (379 LOC)
   - **Purpose:** Standardized memory entry models (SHORT_TERM/EPISODIC/LONG_TERM)
   - **Backend:** SQLite with WAL mode
   - **Features:** TTL, importance, tier-based limits
   - **Status:** Well-designed, not wired to runtime
   - **Action:** INTEGRATE into memory_facade

7. **`core/memory/memory_layers.py`** (229 LOC)
   - **Purpose:** 6 memory types with metadata and relevance scoring
   - **Dependencies:** memory_schema.MemoryStore
   - **Status:** Implemented but NOT wired to agent runtime (as of 2026-04-03)
   - **Action:** Wire into memory_facade or deprecate

8. **`core/orchestration/memory_retrieval.py`** (329 LOC)
   - **Purpose:** Context-aware retrieval with decay and boosting
   - **Dependencies:** memory_facade
   - **Status:** Active wrapper around facade
   - **Action:** MERGE retrieval logic into memory_facade

#### **Specialized Memory Systems (8 files)**

9. **`core/knowledge_memory.py`** (277 LOC, 11 imports)
   - **Purpose:** Keyword-based solution memory (max 200 entries)
   - **Backend:** JSONL file
   - **Features:** Mission-type matching, LRU eviction
   - **Action:** MERGE into memory_facade as knowledge backend

10. **`memory/decision_memory.py`** (282 LOC, 16 imports)
    - **Purpose:** FIFO decision history (max 1000 entries)
    - **Backend:** JSONL file
    - **Features:** Mission classification, confidence adjustment
    - **Action:** KEEP as specialized module, simplify interface

11. **`memory/vault_memory.py`** (364 LOC, 11 imports)
    - **Purpose:** Multi-tier cache (L1 in-memory, L2 PostgreSQL, L3 JSON)
    - **Backend:** PostgreSQL + Redis + JSON
    - **Features:** Unified entry model, safe fallback
    - **Action:** MERGE caching layer into memory_facade

12. **`core/improvement_memory.py`** (333 LOC, 10 imports)
    - **Purpose:** Agent improvement tracking (score_before/after)
    - **Backend:** SQLite primary, asyncpg upgrade path
    - **Features:** Agent stats, top feedback retrieval
    - **Action:** KEEP as specialized module (distinct from self_improvement)

13. **`core/mission_memory.py`** (292 LOC, 10 imports)
    - **Purpose:** Mission execution results and lessons
    - **Backend:** JSONL file
    - **Features:** Mission lookup, recent results
    - **Action:** MERGE into memory_facade as mission content type

14. **`core/business/mission_memory.py`** (193 LOC)
    - **Purpose:** Business mission execution traces
    - **Backend:** JSON file
    - **Overlap:** Duplicates core/mission_memory.py
    - **Action:** MERGE into core/mission_memory.py

15. **`core/self_improvement/improvement_memory.py`** (198 LOC)
    - **Purpose:** Self-improvement pipeline history
    - **Backend:** JSON file (workspace/self_improvement/history.json)
    - **Distinction:** Pipeline attempts vs agent scoring (different concerns)
    - **Action:** KEEP as specialized module

16. **`memory/agent_memory.py`** (202 LOC)
    - **Purpose:** Agent-level memory (unclear usage)
    - **Action:** AUDIT imports → merge or deprecate

#### **Domain-Specific Memory (6 files)**

17. **`core/economic/strategic_memory.py`** (262 LOC)
    - **Purpose:** Strategic business decisions
    - **Backend:** JSONL
    - **Action:** MERGE into memory_facade as strategic content type

18. **`core/execution/strategy_memory.py`** (226 LOC)
    - **Purpose:** Execution strategy comparison
    - **Backend:** JSONL
    - **Action:** MERGE into memory_facade as strategy content type

19. **`core/finance/finance_memory.py`** (213 LOC)
    - **Purpose:** Financial events (safe, no sensitive data)
    - **Backend:** JSONL
    - **Action:** KEEP as specialized module (compliance boundary)

20. **`core/planning/execution_memory.py`** (173 LOC)
    - **Purpose:** Plan execution history
    - **Backend:** JSON
    - **Action:** MERGE into memory_facade as execution content type

21. **`core/planning/learning_memory.py`** (213 LOC)
    - **Purpose:** Learning pattern tracking
    - **Backend:** JSON
    - **Action:** MERGE into memory_facade as learning content type

22. **`core/self_improvement/lesson_memory.py`** (103 LOC)
    - **Purpose:** Self-improvement lessons
    - **Backend:** JSON
    - **Action:** MERGE into self_improvement/improvement_memory.py

#### **Legacy/Utility Files (4 files)**

23. **`core/memory.py`** (76 LOC)
    - **Purpose:** Simple JSON memory bank (RAG-lite)
    - **Status:** Early implementation, superseded
    - **Action:** DEPRECATE (functionality in memory_facade)

24. **`core/memory/vector_memory.py`** (2 LOC)
    - **Purpose:** Empty import stub
    - **Action:** DELETE

25. **`core/tools/memory_toolkit.py`** (2 LOC)
    - **Purpose:** Re-export from legacy toolkit
    - **Action:** AUDIT imports → inline or delete

26. **`core/knowledge/memory_quality.py`** (320 LOC)
    - **Purpose:** Memory quality scoring
    - **Action:** MERGE into memory_facade as quality module

---

## Proposed Unified Architecture

### **3-Tier Facade Pattern**

```
┌─────────────────────────────────────────────────────────────────┐
│                   UNIFIED MEMORY INTERFACE                      │
│                    (MemoryFacade v2.0)                          │
│  • Single entry point for all memory operations                │
│  • Content-type routing                                        │
│  • Backend abstraction                                         │
│  • Health monitoring                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  CORE BACKENDS   │  │ SPECIALIZED      │  │ LEGACY ADAPTERS  │
│                  │  │ SYSTEMS          │  │                  │
│ • MemoryBus      │  │ • DecisionMemory │  │ • memory_toolkit │
│ • VectorMemory   │  │ • ImprovementMem │  │ • knowledge_mem  │
│ • MemorySystem   │  │ • FinanceMemory  │  │ (compatibility)  │
│ • VaultMemory    │  │ • SelfImproveMem │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      STORAGE LAYER                              │
│  • PostgreSQL (structured, transactional)                       │
│  • Qdrant (vector search, embeddings)                          │
│  • Redis (cache, working memory)                               │
│  • SQLite (local persistence)                                  │
│  • JSONL (fallback, portability)                               │
└─────────────────────────────────────────────────────────────────┘
```

### **3-5 Core Modules (Target State)**

#### **1. `core/memory_facade.py`** (Enhanced) ⭐ **PRIMARY INTERFACE**
**Responsibilities:**
- Single entry point for all memory operations
- Content-type routing (solution, error, patch, decision, knowledge, etc.)
- Backend selection and fallback
- Cross-backend search aggregation
- Health monitoring

**Interface:**
```python
facade = get_memory_facade()
facade.store(content, content_type, tags, metadata)
facade.search(query, content_type, top_k)
facade.get_recent(content_type, n)
facade.health()
```

**Enhancements:**
- Integrate memory_system tier logic (SHORT_TERM/EPISODIC/LONG_TERM)
- Add memory_schema models for type safety
- Embed memory_retrieval scoring logic
- Add quality scoring from memory_quality.py

#### **2. `memory/memory_bus.py`** (Current) ⭐ **BACKEND AGGREGATOR**
**Responsibilities:**
- Multi-backend coordination
- Lazy backend initialization
- Patch context assembly
- Unified recall interface

**Keep As-Is:** Already well-designed, no changes needed

#### **3. `memory/vector_memory.py`** (Current) ⭐ **VECTOR BACKEND**
**Responsibilities:**
- Embedding generation (local or HuggingFace)
- Cosine similarity search
- JSON persistence
- TF-IDF fallback

**Keep As-Is:** Core dependency, stable

#### **4. `memory/specialized_memory.py`** (New) ⭐ **DOMAIN SYSTEMS**
**Responsibilities:**
- DecisionMemory (mission classification, confidence adjustment)
- ImprovementMemory (agent scoring, feedback tracking)
- FinanceMemory (safe financial event logging)
- SelfImprovementMemory (pipeline history)

**Consolidates:**
- `memory/decision_memory.py`
- `core/improvement_memory.py`
- `core/finance/finance_memory.py`
- `core/self_improvement/improvement_memory.py`

**Interface:**
```python
from memory.specialized_memory import (
    DecisionMemory,
    ImprovementMemory,
    FinanceMemory,
    SelfImprovementMemory
)
```

#### **5. `memory/storage_backends.py`** (New - Optional)
**Responsibilities:**
- Unified storage abstractions
- PostgreSQL, SQLite, Qdrant, Redis adapters
- Connection pooling
- Health checks

**Consolidates:**
- `memory/vault_memory.py` (caching layer)
- `core/memory/memory_schema.py` (SQLite backend)
- PostgreSQL/Redis logic from various modules

---

## Overlapping Functionality Analysis

### **1. Vector Storage (4 implementations)**

| Module | Backend | Embeddings | Persistence | Status |
|--------|---------|-----------|-------------|--------|
| `memory/vector_memory.py` | In-memory | HF API or local | JSON | ⭐ KEEP |
| `memory_bus.pgvector` | PostgreSQL | Memory embeddings | PostgreSQL | INTEGRATE |
| `memory_system.py` Qdrant | Qdrant | Ollama nomic-embed | Qdrant | INTEGRATE |
| `continual_memory.py` Qdrant | Qdrant | Ollama nomic-embed | Qdrant | MERGE |

**Decision:** Keep `memory/vector_memory.py` as primary. Add Qdrant and pgvector as optional backends in memory_facade.

### **2. Mission Memory (3 implementations)**

| Module | Purpose | Backend | Status |
|--------|---------|---------|--------|
| `core/mission_memory.py` | General mission results | JSONL | ⭐ KEEP |
| `core/business/mission_memory.py` | Business mission traces | JSON | MERGE |
| `planning/execution_memory.py` | Plan execution history | JSON | MERGE |

**Decision:** Consolidate into `core/mission_memory.py` with type field (business, planning, general).

### **3. Improvement Memory (2 implementations)**

| Module | Purpose | Backend | Status |
|--------|---------|---------|--------|
| `core/improvement_memory.py` | Agent scoring (before/after) | SQLite/asyncpg | ⭐ KEEP |
| `self_improvement/improvement_memory.py` | Pipeline history | JSON | ⭐ KEEP |

**Decision:** Both have distinct purposes. Keep separate.

### **4. Memory Schema/Store (2 implementations)**

| Module | Purpose | Backend | Status |
|--------|---------|---------|--------|
| `memory/memory_schema.py` | Tier-based entry models | SQLite | INTEGRATE |
| `memory/vault_memory.py` | Multi-tier caching | PostgreSQL/Redis/JSON | INTEGRATE |

**Decision:** Merge into unified storage backend in memory_facade.

---

## Migration Steps

### **Phase 1: Foundation (Week 1-2)**

1. **Enhance `core/memory_facade.py`**
   - Integrate tier logic from `memory_system.py`
   - Add typed models from `memory_schema.py`
   - Embed quality scoring from `memory_quality.py`
   - Add retrieval scoring from `memory_retrieval.py`

2. **Create `memory/specialized_memory.py`**
   - Extract DecisionMemory → unchanged interface
   - Extract ImprovementMemory → unchanged interface
   - Extract FinanceMemory → unchanged interface
   - Extract SelfImprovementMemory → unchanged interface

3. **Add Qdrant Backend to Memory Facade**
   - Integrate `memory_system.py` Qdrant logic as optional backend
   - Add `continual_memory.py` replay buffer as method
   - Maintain backward compatibility

### **Phase 2: Domain Consolidation (Week 3-4)**

4. **Merge Mission Memory Variants**
   - Consolidate `business/mission_memory.py` → `core/mission_memory.py`
   - Add type field: "business", "planning", "general"
   - Migrate existing data

5. **Merge Strategy/Execution Memory**
   - Add content types to memory_facade: "strategy", "execution"
   - Migrate data from dedicated files to unified backend

6. **Integrate Knowledge Systems**
   - Migrate `knowledge_memory.py` patterns to memory_facade routing
   - Keep backward compatibility layer

### **Phase 3: Cleanup (Week 5)**

7. **Deprecate Legacy Files**
   - `core/memory.py` → add deprecation warning
   - `core/memory/vector_memory.py` → delete (empty stub)
   - `core/tools/memory_toolkit.py` → inline or redirect

8. **Wire `memory_layers.py` to Runtime**
   - Connect MemoryLayer to ParallelExecutor/AgentCrew
   - OR deprecate if redundant with facade

9. **Update All Import Paths**
   - Update 206 import statements across codebase
   - Add compatibility imports where needed
   - Run test suite

### **Phase 4: Validation (Week 6)**

10. **Testing**
    - Run full test suite
    - Validate backward compatibility
    - Performance benchmarking

11. **Documentation**
    - Update API docs
    - Create migration guide
    - Update architecture diagrams

12. **Metrics**
    - Monitor memory search latency
    - Track facade cache hit rates
    - Measure storage backend health

---

## Files to Keep/Merge/Delete

### **✅ KEEP (5 core files)**

1. `core/memory_facade.py` → Enhanced as primary interface
2. `memory/memory_bus.py` → Backend aggregator
3. `memory/vector_memory.py` → Core vector backend
4. `memory/specialized_memory.py` → New, consolidates domain systems
5. `memory/decision_memory.py` → Keep separate (highly specialized)

### **🔀 MERGE (17 files)**

**Merge into `core/memory_facade.py`:**
- `core/orchestration/memory_system.py` (tier logic)
- `core/orchestration/memory_retrieval.py` (retrieval scoring)
- `core/knowledge/memory_quality.py` (quality scoring)
- `core/memory/memory_schema.py` (typed models)
- `core/memory/memory_layers.py` (layer abstraction)
- `memory/vault_memory.py` (caching layer)
- `core/orchestration/continual_memory.py` (replay buffer)

**Merge into `core/mission_memory.py`:**
- `core/business/mission_memory.py`
- `core/planning/execution_memory.py`

**Merge into `memory/specialized_memory.py`:**
- `core/improvement_memory.py`
- `core/self_improvement/improvement_memory.py`
- `core/finance/finance_memory.py`

**Merge into `core/memory_facade.py` as content types:**
- `core/knowledge_memory.py`
- `core/economic/strategic_memory.py`
- `core/execution/strategy_memory.py`
- `core/planning/learning_memory.py`
- `core/self_improvement/lesson_memory.py`

### **🗑️ DELETE (4 files)**

1. `core/memory.py` → Superseded by memory_facade
2. `core/memory/vector_memory.py` → Empty stub
3. `core/tools/memory_toolkit.py` → Redirect to facade (if only re-export)
4. `memory/agent_memory.py` → Audit first, likely unused

---

## Source of Truth Designation

### **Primary Source of Truth: `core/memory_facade.py`**

**Rationale:**
- Already designed as unified interface
- Content-type routing eliminates ambiguity
- Backend abstraction prevents tight coupling
- 19 active imports show partial adoption
- Fail-open design ensures reliability

**Requirements:**
1. ✅ Comprehensive content type support (solution, error, patch, decision, knowledge, etc.)
2. ✅ Multi-backend routing with fallback
3. ✅ Health monitoring
4. ⚠️ **MISSING:** Tier-based TTL (add from memory_system)
5. ⚠️ **MISSING:** Quality scoring (add from memory_quality)
6. ⚠️ **MISSING:** Retrieval relevance (add from memory_retrieval)

### **Secondary Source of Truth: `memory/memory_bus.py`**

**Rationale:**
- Backend aggregator (store, vector, patches, failures)
- Well-adopted (9 imports)
- Lazy initialization
- Unified recall interface

**Role:** Backend coordinator, not public API

---

## Risk Assessment

### **High Risk**

1. **Import Path Changes (206 imports)**
   - Mitigation: Phased rollout with compatibility layer
   - Testing: Automated import verification

2. **Data Migration**
   - Mitigation: Keep old backends active during transition
   - Testing: Validate data integrity after migration

### **Medium Risk**

3. **Performance Impact**
   - Mitigation: Benchmark before/after, cache optimization
   - Testing: Load testing with realistic workloads

4. **Backward Compatibility**
   - Mitigation: Keep legacy imports as aliases
   - Testing: Run full test suite after each phase

### **Low Risk**

5. **Domain-Specific Logic**
   - Mitigation: Extract interfaces, keep implementations separate
   - Testing: Unit tests for specialized modules

---

## Success Metrics

### **Code Metrics**
- **Before:** 26 memory files, ~6,000 LOC
- **Target:** 5-7 memory files, ~3,500 LOC
- **Reduction:** ~40% code reduction

### **Import Complexity**
- **Before:** 206 imports across 10+ modules
- **Target:** 80% of imports to memory_facade
- **Reduction:** 60% reduction in import paths

### **Backend Health**
- **Metric:** 95%+ uptime for primary backends
- **Monitoring:** Health check endpoint in memory_facade
- **Alerting:** Log warnings on backend degradation

### **Performance**
- **Search Latency:** <100ms p95 (cross-backend)
- **Storage Latency:** <50ms p95 (single backend)
- **Cache Hit Rate:** >80% for L1 memory

---

## Open Questions

1. **Should `memory_layers.py` be wired into runtime or deprecated?**
   - Current status: Implemented but not active (as of 2026-04-03)
   - Recommendation: Wire into facade OR deprecate in Phase 3

2. **What to do with `memory/agent_memory.py`?**
   - Action: Audit imports to determine usage
   - If unused: deprecate. If active: merge into specialized_memory

3. **Should Qdrant be primary vector backend?**
   - Current: `vector_memory.py` (JSON) is primary
   - Alternative: Make Qdrant primary with JSON fallback
   - Recommendation: Keep JSON primary for simplicity, add Qdrant as optional upgrade

4. **How to handle PostgreSQL/Redis dependencies in consolidated system?**
   - Recommendation: Make optional with graceful degradation
   - Fallback: SQLite + JSON if PostgreSQL/Redis unavailable

---

## Appendix: File Size Summary

| Category | Files | Total LOC |
|----------|-------|-----------|
| Core Infrastructure | 8 | 3,932 |
| Specialized Systems | 8 | 2,059 |
| Domain-Specific | 6 | 1,227 |
| Legacy/Utility | 4 | 521 |
| **TOTAL** | **26** | **~7,739** |

**Target After Consolidation:** 5-7 files, ~3,500-4,000 LOC

---

## Next Steps

1. **Get Stakeholder Approval**
   - Review consolidation plan with team
   - Prioritize phases based on business needs

2. **Create Implementation Tickets**
   - Break down each phase into tasks
   - Assign owners and timelines

3. **Setup Monitoring**
   - Add memory_facade health dashboard
   - Create alerts for backend failures

4. **Begin Phase 1**
   - Enhance memory_facade with tier logic
   - Create specialized_memory module
   - Write migration scripts

---

**Document Version:** 1.0  
**Author:** Hermes Agent (BeaMax Audit)  
**Last Updated:** 2026-04-11
