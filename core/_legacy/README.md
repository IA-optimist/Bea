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

Last updated: 2026-04-07
