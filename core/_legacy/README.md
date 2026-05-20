# Core Legacy Components

This directory contains deprecated components that have been superseded by newer implementations.

## Mission Stores
- ~~`mission_persistence.py`~~ — MOVED back to `core/mission_persistence.py` audit S8 (2026-05-20). The "replaced by api/mission_store.py" hint was misleading : MissionStateStore (api/) is a different abstraction (per-process mission state) ; MissionPersistenceStore (core/) is the durable JSON journal that ~30 call sites in api/routes/, core/meta_orchestrator.py, core/orchestration/execution_supervisor.py, and tests/ depend on.

## Orchestrators
- ~~`orchestrator_v2.py`~~ — MOVED back to `core/orchestrator_v2.py` audit S8 (2026-05-20). It was mis-classified as legacy : MetaOrchestrator actively lazy-imports it for budget/DAG missions.

## Policy Engines
- `policy_engine_v2.py` - Old PolicyEngine (replaced by kernel/policy/engine.py KernelPolicyEngine)

## Self-Improvement
- `self_improvement_v1.py` - V1 monolithic self-improvement (replaced by core/self_improvement/)
- ~~`self_improvement_engine_v2.py`~~ — REMOVED audit S8 (2026-05-20). Callers migrated to `core/self_improvement/engine.py`.
- `self_improvement_loop_v2.py` - V2 loop (replaced by core/self_improvement/improvement_loop.py)

## Status
All files in this directory are kept for historical reference only and should NOT be imported by active code.

## Migration debt (audit Sprint 3 P1, tracked 2026-05-19)

The audit flagged five shim files in `core/` that still re-export from this
directory, blocking the simple `rm -rf core/_legacy/`. 3/5 have been
addressed in audit S8 (2026-05-20):

| Shim in core/                         | Re-exports from core/_legacy/                   | Status   |
|---------------------------------------|-------------------------------------------------|----------|
| ~~`core/mission_persistence.py`~~     | ~~`mission_persistence.py`~~                    | **promoted S8** (file moved out of legacy) |
| ~~`core/orchestrator_v2.py`~~         | ~~`orchestrator_v2.py`~~                        | **promoted S8** (file moved out of legacy) |
| `core/policy_engine.py`               | `policy_engine_LEGACY_20260407.py`              | open     |
| ~~`core/self_improvement_engine.py`~~ | ~~`self_improvement_engine_v2.py`~~             | **migrated S8** (callers updated) |
| `core/self_improvement_loop.py`       | `self_improvement_loop_v2.py`                   | open     |

**Migration plan** (a dedicated PR, not bundled with the hardening pass):
1. Find every caller of each shim (`grep -rn 'core\\.mission_persistence\\|core\\.orchestrator_v2\\|...'`).
2. Replace with the canonical implementation (e.g. `api/mission_store.MissionStateStore`).
3. Drop the shim file, then `git rm -rf core/_legacy/`.

Until this is done, **DO NOT** add new imports to `core._legacy.*`. Treat
this directory as frozen.

Last updated: 2026-05-20
