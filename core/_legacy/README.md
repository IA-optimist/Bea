# Core Legacy Components

This directory contains deprecated components that have been superseded by newer implementations.

## Mission Stores
- `mission_persistence.py` - Old MissionPersistenceStore (replaced by api/mission_store.py MissionStateStore)

## Orchestrators  
- `orchestrator_v2.py` - OrchestratorV2 (replaced by core/meta_orchestrator.py MetaOrchestrator)

## Policy Engines
- `policy_engine_v2.py` - Old PolicyEngine (replaced by kernel/policy/engine.py KernelPolicyEngine)

## Self-Improvement
- `self_improvement_v1.py` - V1 monolithic self-improvement (replaced by core/self_improvement/)
- `self_improvement_engine_v2.py` - V2 engine (replaced by core/self_improvement/engine.py)
- `self_improvement_loop_v2.py` - V2 loop (replaced by core/self_improvement/improvement_loop.py)

## Status
All files in this directory are kept for historical reference only and should NOT be imported by active code.

## Migration debt (audit Sprint 3 P1, tracked 2026-05-19)

The audit flagged five shim files in `core/` that still re-export from this
directory, blocking the simple `rm -rf core/_legacy/`:

| Shim in core/                         | Re-exports from core/_legacy/                   |
|---------------------------------------|-------------------------------------------------|
| `core/mission_persistence.py`         | `mission_persistence.py`                        |
| `core/orchestrator_v2.py`             | `orchestrator_v2.py`                            |
| `core/policy_engine.py`               | `policy_engine_LEGACY_20260407.py`              |
| `core/self_improvement_engine.py`     | `self_improvement_engine_v2.py`                 |
| `core/self_improvement_loop.py`       | `self_improvement_loop_v2.py`                   |

**Migration plan** (a dedicated PR, not bundled with the hardening pass):
1. Find every caller of each shim (`grep -rn 'core\\.mission_persistence\\|core\\.orchestrator_v2\\|...'`).
2. Replace with the canonical implementation (e.g. `api/mission_store.MissionStateStore`).
3. Drop the shim file, then `git rm -rf core/_legacy/`.

Until this is done, **DO NOT** add new imports to `core._legacy.*`. Treat
this directory as frozen.

Last updated: 2026-05-19
