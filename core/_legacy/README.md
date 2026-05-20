# Core Legacy Components

This directory contains deprecated components that have been superseded by newer implementations.

## Mission Stores
- ~~`mission_persistence.py`~~ — MOVED back to `core/mission_persistence.py` audit S8 (2026-05-20). The "replaced by api/mission_store.py" hint was misleading : MissionStateStore (api/) is a different abstraction (per-process mission state) ; MissionPersistenceStore (core/) is the durable JSON journal that ~30 call sites in api/routes/, core/meta_orchestrator.py, core/orchestration/execution_supervisor.py, and tests/ depend on.

## Orchestrators
- ~~`orchestrator_v2.py`~~ — MOVED back to `core/orchestrator_v2.py` audit S8 (2026-05-20). It was mis-classified as legacy : MetaOrchestrator actively lazy-imports it for budget/DAG missions.

## Policy Engines
- ~~`policy_engine_v2.py`~~ ~~`policy_engine_LEGACY_20260407.py`~~ — MOVED back to `core/policy_engine.py` audit S8 (2026-05-20). The migration guide in the header pointed to `core/policy/policy_engine.py` (Economic Policy Engine) but that file was never actually created — the 3 production call sites (main.py, kernel/adapters/policy_adapter.py, core/jarvis_executor.py) all still depend on this Constitution-based engine.

## Self-Improvement
- `self_improvement_v1.py` - V1 monolithic self-improvement (replaced by core/self_improvement/)
- ~~`self_improvement_engine_v2.py`~~ — REMOVED audit S8 (2026-05-20). Callers migrated to `core/self_improvement/engine.py`.
- `self_improvement_loop_v2.py` - V2 loop (replaced by core/self_improvement/improvement_loop.py)

## Status
All files in this directory are kept for historical reference only and should NOT be imported by active code.

## Migration debt (audit Sprint 3 P1, tracked 2026-05-19)

The audit flagged five shim files in `core/` that still re-export from this
directory, blocking the simple `rm -rf core/_legacy/`. **All 5 done in
audit S8 (2026-05-20). Issue #15 closed.**

| Shim in core/                         | Re-exports from core/_legacy/                   | Status   |
|---------------------------------------|-------------------------------------------------|----------|
| ~~`core/mission_persistence.py`~~     | ~~`mission_persistence.py`~~                    | **promoted S8** |
| ~~`core/orchestrator_v2.py`~~         | ~~`orchestrator_v2.py`~~                        | **promoted S8** |
| ~~`core/policy_engine.py`~~           | ~~`policy_engine_LEGACY_20260407.py`~~          | **promoted S8** |
| ~~`core/self_improvement_engine.py`~~ | ~~`self_improvement_engine_v2.py`~~             | **migrated S8** |
| ~~`core/self_improvement_loop.py`~~   | ~~`self_improvement_loop_v2.py`~~               | **promoted S8** |

## What remains under core/_legacy/

After **S9 (2026-05-20)** the `memory/` subdir is gone too :

- ~~`core/_legacy/memory/intelligent_memory.py`~~ — DELETED (orphan, 0
  callers, header said "placeholder to allow test collection").
- ~~`core/_legacy/memory/memory_toolkit_legacy.py`~~ — DELETED (423 LOC
  orphan ; the actual `core.tools.memory_toolkit_legacy` is a different
  33 LOC stub that lives at `core/tools/memory_toolkit_legacy.py`).
- ~~`core/_legacy/memory/legacy_knowledge_memory.py`~~ — MOVED to
  `memory/legacy_knowledge_memory.py` (restores the silently-disabled
  `from memory.legacy_knowledge_memory import …` calls in agents/crew.py
  and memory/memory_bus.py).
- ~~`core/_legacy/memory/vector_memory_legacy.py`~~ — MOVED to
  `core/memory/vector_memory_legacy.py` (restores the broken shim
  `core/memory/vector_memory.py` that imports it).

The `core/_legacy/` directory now contains only this README.md and an
`__init__.py` with a deprecation docstring. Both can be removed in a
follow-up — they no longer guard any code.

### Historical orphans deleted along the way

- `core/_legacy/policy_engine_v2.py` (Sprint 8.5) — 0 callers, predated
  the `policy_engine_LEGACY_20260407` rename.

**Migration plan** (a dedicated PR, not bundled with the hardening pass):
1. Find every caller of each shim (`grep -rn 'core\\.mission_persistence\\|core\\.orchestrator_v2\\|...'`).
2. Replace with the canonical implementation (e.g. `api/mission_store.MissionStateStore`).
3. Drop the shim file, then `git rm -rf core/_legacy/`.

Until this is done, **DO NOT** add new imports to `core._legacy.*`. Treat
this directory as frozen.

Last updated: 2026-05-20
