# Memory System Files - Quick Reference

Complete inventory of all 26 memory-related files in JarvisMax.

---

## Core Infrastructure (8 files)

### 1. `core/memory_facade.py` ⭐ CANONICAL
- **LOC:** 730
- **Imports:** 19 active references
- **Purpose:** Unified memory interface, routes to backends
- **Backend:** Routes to memory_bus, memory_toolkit, knowledge_memory, decision_memory
- **Dependencies:** memory.memory_bus, core.tools.memory_toolkit, core.knowledge_memory
- **Key Methods:** `store()`, `search()`, `get_recent()`, `health()`
- **Status:** PRIMARY SOURCE OF TRUTH (partially adopted)
- **Action:** KEEP + ENHANCE (add tier logic, quality scoring)

### 2. `memory/memory_bus.py` ⭐ CANONICAL
- **LOC:** 841
- **Imports:** 9 active references
- **Purpose:** Multi-backend router (store, vector, patches, failures)
- **Backend:** Aggregates MemoryStore, VectorMemory, PatchMemory, FailureMemory
- **Key Methods:** `remember()`, `recall()`, `search()`, `remember_patch()`, `get_patch_context()`
- **Status:** BACKEND AGGREGATOR
- **Action:** KEEP (no changes needed)

### 3. `core/orchestration/memory_system.py`
- **LOC:** 655
- **Imports:** 2 active references
- **Purpose:** 3-level memory (working/episodic/semantic) with Qdrant
- **Backend:** Qdrant + Redis + Ollama embeddings
- **Key Features:** TTL-based working memory, importance scoring, episode summarization
- **Key Methods:** `store()`, `retrieve()`, `forget()`, `summarize_episode()`
- **Status:** Sophisticated but underutilized
- **Action:** MERGE tier logic into memory_facade

### 4. `core/orchestration/memory_retrieval.py`
- **LOC:** 329
- **Imports:** Unknown
- **Purpose:** Context-aware retrieval with decay and boosting
- **Backend:** Wraps memory_facade
- **Key Features:** Mission-aware filtering, time decay, importance boost
- **Status:** Active wrapper
- **Action:** MERGE retrieval logic into memory_facade

### 5. `core/orchestration/continual_memory.py`
- **LOC:** 438
- **Imports:** 2 active references
- **Purpose:** Experience replay buffer for catastrophic forgetting
- **Backend:** Qdrant + Ollama embeddings
- **Key Features:** Surprise scoring, prioritized replay, consolidation
- **Key Methods:** `store_experience()`, `replay()`, `consolidate()`
- **Status:** Specialized, minimal adoption
- **Action:** MERGE into memory_system as replay module

### 6. `memory/vector_memory.py` ⭐ CANONICAL
- **LOC:** 533
- **Imports:** 11 active references
- **Purpose:** Local vector store with sentence-transformers
- **Backend:** JSON file + HuggingFace API or local embeddings
- **Key Features:** Cosine similarity, TF-IDF fallback, deduplication
- **Key Methods:** `add()`, `search()`, `clear()`
- **Status:** CORE VECTOR BACKEND
- **Action:** KEEP (stable, widely used)

### 7. `core/memory/memory_schema.py`
- **LOC:** 379
- **Imports:** Unknown
- **Purpose:** Standardized memory entry models (SHORT_TERM/EPISODIC/LONG_TERM)
- **Backend:** SQLite with WAL mode
- **Key Features:** TTL, importance, tier-based limits, integrity checks
- **Key Classes:** `MemoryEntry`, `MemoryStore`
- **Status:** Well-designed, not wired to runtime
- **Action:** INTEGRATE models into memory_facade

### 8. `core/memory/memory_layers.py`
- **LOC:** 229
- **Imports:** Unknown
- **Purpose:** 6 memory types with metadata and relevance scoring
- **Backend:** Wraps memory_schema.MemoryStore
- **Key Features:** Structured types, relevance scoring, safe pruning
- **Status:** Implemented but NOT wired to agent runtime (as of 2026-04-03)
- **Action:** Wire into memory_facade OR deprecate

---

## Specialized Memory Systems (8 files)

### 9. `core/knowledge_memory.py`
- **LOC:** 277
- **Imports:** 11 active references
- **Purpose:** Keyword-based solution memory (max 200 entries)
- **Backend:** JSONL file (`workspace/knowledge_memory.jsonl`)
- **Key Features:** Mission-type matching, Jaccard similarity, LRU eviction
- **Key Methods:** `store_if_useful()`, `query()`, `get_stats()`
- **Status:** Active, keyword-based retrieval
- **Action:** MERGE into memory_facade as knowledge backend

### 10. `memory/decision_memory.py` ⭐ SPECIALIZED
- **LOC:** 282
- **Imports:** 16 active references
- **Purpose:** FIFO decision history (max 1000 entries)
- **Backend:** JSONL file (`workspace/decision_memory.jsonl`)
- **Key Features:** Mission classification, confidence adjustment, outcome tracking
- **Key Methods:** `record()`, `classify_mission_type()`, `get_stats()`, `adjust_confidence()`
- **Status:** Highly specialized, widely used
- **Action:** KEEP as specialized module

### 11. `memory/vault_memory.py`
- **LOC:** 364
- **Imports:** 11 active references
- **Purpose:** Multi-tier cache (L1 in-memory, L2 PostgreSQL, L3 JSON)
- **Backend:** PostgreSQL + Redis + JSON
- **Key Features:** 3-tier caching, safe fallback, unified entry model
- **Key Methods:** `store()`, `retrieve()`, `search()`, `batch_store()`
- **Status:** Active caching layer
- **Action:** MERGE caching logic into memory_facade

### 12. `core/improvement_memory.py` ⭐ SPECIALIZED
- **LOC:** 333
- **Imports:** 10 active references
- **Purpose:** Agent improvement tracking (score_before/after)
- **Backend:** SQLite primary, asyncpg upgrade path
- **Key Features:** Agent stats, top feedback retrieval, delta tracking
- **Key Methods:** `record_improvement()`, `get_agent_stats()`, `get_top_feedback()`
- **Status:** Active, distinct from self_improvement/improvement_memory
- **Action:** KEEP as specialized module

### 13. `core/mission_memory.py`
- **LOC:** 292
- **Imports:** 10 active references
- **Purpose:** Mission execution results and lessons
- **Backend:** JSONL file (`workspace/mission_memory.jsonl`)
- **Key Features:** Mission lookup, recent results, lessons learned
- **Key Methods:** `store_mission()`, `get_mission()`, `get_recent()`
- **Status:** Core mission tracking
- **Action:** KEEP + merge variants into this

### 14. `core/business/mission_memory.py`
- **LOC:** 193
- **Imports:** Unknown
- **Purpose:** Business mission execution traces
- **Backend:** JSON file (`workspace/business_mission_memory.json`)
- **Key Features:** Business-specific mission tracking, duration, steps
- **Status:** Overlaps with core/mission_memory.py
- **Action:** MERGE into core/mission_memory.py (add type="business")

### 15. `core/self_improvement/improvement_memory.py` ⭐ SPECIALIZED
- **LOC:** 198
- **Imports:** Unknown
- **Purpose:** Self-improvement pipeline history
- **Backend:** JSON file (`workspace/self_improvement/history.json`)
- **Key Features:** Pipeline attempts, candidate types, outcomes
- **Status:** Distinct from core/improvement_memory.py (different concerns)
- **Action:** KEEP as specialized module

### 16. `memory/agent_memory.py`
- **LOC:** 202
- **Imports:** Unknown
- **Purpose:** Agent-level memory (unclear usage)
- **Backend:** Unknown
- **Status:** Unclear adoption
- **Action:** AUDIT imports → merge or deprecate

---

## Domain-Specific Memory (6 files)

### 17. `core/economic/strategic_memory.py`
- **LOC:** 262
- **Imports:** Unknown
- **Purpose:** Strategic business decisions
- **Backend:** JSONL file (`workspace/strategic_memory.jsonl`)
- **Key Features:** Strategic records, company tracking, decision history
- **Status:** Domain-specific
- **Action:** MERGE into memory_facade as "strategic" content type

### 18. `core/execution/strategy_memory.py`
- **LOC:** 226
- **Imports:** Unknown
- **Purpose:** Execution strategy comparison
- **Backend:** JSONL file (`workspace/strategy_memory.jsonl`)
- **Key Features:** Strategy records, cost/quality comparison, feedback tracking
- **Status:** Domain-specific
- **Action:** MERGE into memory_facade as "strategy" content type

### 19. `core/finance/finance_memory.py` ⭐ SPECIALIZED
- **LOC:** 213
- **Imports:** Unknown
- **Purpose:** Financial events (safe, no sensitive data)
- **Backend:** JSON file (`workspace/finance_memory.json`)
- **Key Features:** Safe financial logging (no card numbers, addresses, secrets)
- **Status:** Compliance boundary
- **Action:** KEEP as specialized module

### 20. `core/planning/execution_memory.py`
- **LOC:** 173
- **Imports:** Unknown
- **Purpose:** Plan execution history
- **Backend:** JSON file (`workspace/execution_history.json`)
- **Key Features:** Execution records, plan tracking, tool usage
- **Status:** Overlaps with mission_memory
- **Action:** MERGE into core/mission_memory.py (add type="planning")

### 21. `core/planning/learning_memory.py`
- **LOC:** 213
- **Imports:** Unknown
- **Purpose:** Learning pattern tracking
- **Backend:** JSON file (`workspace/learning_memory.json`)
- **Key Features:** Learning records, pattern tracking, feedback loop
- **Status:** Domain-specific
- **Action:** MERGE into memory_facade as "learning" content type

### 22. `core/self_improvement/lesson_memory.py`
- **LOC:** 103
- **Imports:** Unknown
- **Purpose:** Self-improvement lessons
- **Backend:** JSON file (`workspace/self_improvement/lessons.json`)
- **Key Features:** Lesson tracking, success patterns
- **Status:** Small module, overlaps with self_improvement/improvement_memory
- **Action:** MERGE into self_improvement/improvement_memory.py

---

## Legacy/Utility Files (4 files)

### 23. `core/memory.py`
- **LOC:** 76
- **Imports:** Unknown (superseded)
- **Purpose:** Simple JSON memory bank (RAG-lite)
- **Backend:** JSON file (`workspace/.jarvis_memory.json`)
- **Key Features:** Basic lesson storage, Jaccard query
- **Status:** Early implementation, superseded by memory_facade
- **Action:** DEPRECATE (add warning, redirect to memory_facade)

### 24. `core/memory/vector_memory.py`
- **LOC:** 2
- **Imports:** Unknown
- **Purpose:** Empty import stub
- **Backend:** None
- **Status:** Dead code
- **Action:** DELETE

### 25. `core/tools/memory_toolkit.py`
- **LOC:** 2
- **Imports:** Unknown
- **Purpose:** Re-export from legacy toolkit
- **Backend:** Wraps core/tools/memory_toolkit_legacy.py
- **Status:** Compatibility layer
- **Action:** AUDIT imports → inline or delete

### 26. `core/knowledge/memory_quality.py`
- **LOC:** 320
- **Imports:** Unknown
- **Purpose:** Memory quality scoring
- **Backend:** None (scoring logic only)
- **Key Features:** Quality metrics, confidence scoring, relevance decay
- **Status:** Standalone quality module
- **Action:** MERGE quality scoring into memory_facade

---

## Summary by Action

### ✅ KEEP (7 files)
1. `core/memory_facade.py` (enhance)
2. `memory/memory_bus.py` (no changes)
3. `memory/vector_memory.py` (no changes)
4. `memory/decision_memory.py` (specialized)
5. `core/improvement_memory.py` (specialized)
6. `core/self_improvement/improvement_memory.py` (specialized)
7. `core/finance/finance_memory.py` (compliance boundary)

### 🔀 MERGE INTO FACADE (8 files)
- `core/orchestration/memory_system.py`
- `core/orchestration/memory_retrieval.py`
- `core/orchestration/continual_memory.py`
- `core/memory/memory_schema.py`
- `core/memory/memory_layers.py`
- `memory/vault_memory.py`
- `core/knowledge/memory_quality.py`
- `core/knowledge_memory.py`

### 🔀 MERGE INTO MISSION_MEMORY (2 files)
- `core/business/mission_memory.py`
- `core/planning/execution_memory.py`

### 🔀 MERGE AS CONTENT TYPES (4 files)
- `core/economic/strategic_memory.py`
- `core/execution/strategy_memory.py`
- `core/planning/learning_memory.py`
- `core/self_improvement/lesson_memory.py`

### 🗑️ DELETE (4 files)
- `core/memory.py` (superseded)
- `core/memory/vector_memory.py` (empty stub)
- `core/tools/memory_toolkit.py` (re-export)
- `memory/agent_memory.py` (audit first)

### ❓ AUDIT (1 file)
- `memory/agent_memory.py` (determine usage)

---

## Backend Storage Paths

| File | Backend | Storage Path |
|------|---------|--------------|
| memory_facade | Multi-backend | `workspace/memory_facade_store.jsonl` |
| vector_memory | JSON | `workspace/vector_store.json` |
| knowledge_memory | JSONL | `workspace/knowledge_memory.jsonl` |
| decision_memory | JSONL | `workspace/decision_memory.jsonl` |
| mission_memory | JSONL | `workspace/mission_memory.jsonl` |
| improvement_memory | SQLite/PostgreSQL | `workspace/improvements.db` or database_url |
| vault_memory | PostgreSQL/JSON | `~/.hermes/vault_memory.json` |
| memory_schema | SQLite | `workspace/memory.db` |
| strategic_memory | JSONL | `workspace/strategic_memory.jsonl` |
| strategy_memory | JSONL | `workspace/strategy_memory.jsonl` |
| execution_memory | JSON | `workspace/execution_history.json` |
| learning_memory | JSON | `workspace/learning_memory.json` |
| finance_memory | JSON | `workspace/finance_memory.json` |
| business/mission_memory | JSON | `workspace/business_mission_memory.json` |
| self_improvement/improvement_memory | JSON | `workspace/self_improvement/history.json` |
| self_improvement/lesson_memory | JSON | `workspace/self_improvement/lessons.json` |
| continual_memory | Qdrant | Collection: `jarvis_continual_memory` |
| memory_system | Qdrant + Redis | Collections: `jarvis_episodes`, `jarvis_semantic` |

---

**Generated:** 2026-04-11  
**Purpose:** Quick reference for consolidation implementation  
**Next:** See MEMORY_CONSOLIDATION_PLAN.md for migration steps
