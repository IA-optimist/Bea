# Agentic Memory Model — Béa v1

## Memory Tiers

```
┌──────────────────────────────────────────────────────┐
│  Context Window (ephemeral, per-turn)                │
│  → context_for_agent() injects top N memories here  │
├──────────────────────────────────────────────────────┤
│  AgentMemoryStore (in-process, per-session)          │
│  StructuredMemory objects: typed, provenanced        │
├──────────────────────────────────────────────────────┤
│  OperationalMemory / SQLite (persistent, cross-session)│
│  core/memory/operational_memory.py                   │
├──────────────────────────────────────────────────────┤
│  VectorMemory / Qdrant (semantic search)             │
│  core/memory/vector_memory.py → beamax_memory_384   │
└──────────────────────────────────────────────────────┘
```

## StructuredMemory Fields

| Field | Type | Required | Constraint |
|-------|------|----------|-----------|
| memory_type | MemoryType | Yes | see taxonomy below |
| realm | str | Yes | min 2 chars, lowercased |
| source | str | Yes | min 2 chars — who created this |
| confidence | float | Yes | 0.0–1.0 |
| content | str | Yes | 5–4000 chars |
| tags | list[str] | No | lowercased |
| superseded_by | str | No | points to replacement memory_id |

## Memory Types

| Type | Use Case |
|------|---------|
| FACT | Verified fact about code/project |
| DECISION | Architectural / design decision |
| BUG | Known bug or pitfall |
| LESSON | What worked / didn't (from failures and successes) |
| SKILL | Reusable procedure (has tests) |
| RISK | Operational or safety risk |
| RESEARCH_FINDING | Fact from external research |
| DATA_INSIGHT | Finding from data analysis |
| TEST_MAP | Module ↔ test file mapping |
| SECURITY_NOTE | Security observation (surfaced prominently) |

## Recall API

```python
store.recall(
    memory_type=MemoryType.LESSON,  # filter by type
    realm="code",                    # filter by realm
    tags=["failure"],               # filter by tag (OR)
    min_confidence=0.6,             # confidence floor
    exclude_superseded=True,        # exclude replaced entries
    limit=20,                       # max results
)
```

## Audit Trail

- `agent_memory_stored` — logged for every `add()`
- `agent_memory_security_note` — logged when `memory_type in (SECURITY_NOTE, RISK)`
- Secrets never in memory content (security model enforced at agent level)

## CodebaseMemoryService

Wraps `core/coding_agent/repo_map.py` with a stable interface:

```python
svc = CodebaseMemoryService(root="/workspace")
svc.find_symbol("MyClass")         # AST-based symbol search
svc.symbols_in_file("core/api.py") # symbols in a file
svc.grep(r"def \w+_mission")       # regex grep across codebase
svc.invalidate()                    # force snapshot refresh
```

Falls back to lightweight AST scan if repo_map is unavailable.
