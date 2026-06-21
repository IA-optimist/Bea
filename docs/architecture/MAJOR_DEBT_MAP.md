# Major Architecture Debt Map

This file tracks the MAJOR audit items M1 and M5 so refactors can happen incrementally instead of as a big-bang rewrite.

## M1 Monoliths To Split First

| File | Current role | First extraction boundary |
|---|---|---|
| `core/meta_orchestrator.py` | High-level orchestration facade and mission execution state machine | State compatibility now lives in `core/meta_orchestrator_state.py`; chat fast-path policy now lives in `core/meta_chat_fast_path.py`; custom mission handlers now live in `core/meta_custom_handlers.py`. Next split: `_execute_supervised` phases into execution policy/context helpers. |
| `core/orchestration/execution_mixin.py` | ✅ REFACTORED 2026-06-13 — split into 5 focused modules: `execution_goal_builder.py`, `execution_memory_injector.py`, `execution_policy_gate.py`, `execution_supervised_runner.py`, `execution_result_validator.py`. Now < 800 lines (coordinator only). | Done. |
| `core/connectors/_base.py` | Connector registry plus concrete Tier 1/Tier 2 implementations | Contracts are now in `core/connectors/contracts.py`; business/workflow/scrape/export connectors are now in `core/connectors/business.py`; runtime execution helpers are now in `core/connectors/runtime.py`. Next split: Tier 1/Tier 2 concrete implementations. |
| `core/mission_system.py` | Mission lifecycle with legacy compatibility exports | Analysis helpers are now in `core/mission_analysis.py`; dataclasses are now in `core/mission_models.py`; MissionSystem v1 persistence helpers are now in `core/mission_persistence.py`. Next split: state transitions or action creation. |
| `api/routes/missions.py` | HTTP routes plus mission orchestration glue | Request schemas are now in `api/schemas_missions.py`; agent output extraction is now in `api/mission_outputs.py`; mission response assembly is now in `api/mission_response.py`; agent list/trigger helpers are now in `api/mission_agents.py`; task/mission approvals are now in `api/mission_approval.py`; system mode helpers are now in `api/mission_system_mode.py`; legacy aliases are now in `api/mission_legacy.py`; next split should move task submission orchestration. |
| `agents/crew.py` | Agent base class, concrete agents, legacy facades | AgentSelector is now in `agents/selector.py`; AgentCrew registry/dispatch is now in `agents/crew_runtime.py`; next split should move BaseAgent or concrete prompt agents. |
| `core/bea_executor.py` | Execution facade and operational helpers | Extract command policy and execution result normalization. |
| `core/operating_primitives.py` | Primitive definitions plus behavior | Split data contracts from runtime execution helpers. |
| `core/workflow_runtime.py` | Workflow execution and persistence concerns | Extract runner, state store, and error normalization. |
| `api/main.py` | App factory, middleware, auth routes, router registration | Extract auth routes and router registration registry. |

## M5 Canonical Module Ownership

| Concept | Canonical module | Notes |
|---|---|---|
| Agent | `agents/crew.py` for legacy runtime agents; `agents/selector.py` owns agent selection; `agents/crew_runtime.py` owns AgentCrew registry/dispatch. New code should avoid adding more `agent.py` files. | `AgentSelector` and `AgentCrew` have been split with compatibility exports from `agents.crew`; next step: split `BaseAgent` or concrete prompt agents. |
| Registry | `api/router_registry.py` for API router registration; domain registries must document their scope in module docstrings. | Avoid adding generic `registry.py` without a scoped package owner. |
| Contracts | `agents/contracts.py` for agent handoff contracts; API schemas should stay route-local or move to `api/schemas/`. | Do not centralize all Pydantic contracts blindly; map ownership first. |
| Main entrypoints | `api/main.py` for FastAPI app; package-local `main.py` files must be CLI/demo entrypoints only. | New service entrypoints need explicit README notes. |
| Base classes | Prefer package-local `base.py` only when the package has more than one implementation. | Avoid cross-package imports from a generic `base.py`. |

## Hyphenated Sub-Projects

`orchestrate-cli/` is a standalone sub-project (non-importable as a Python package). Keep it excluded from repo-wide Python lint/type assumptions unless migrated into a normal package name. Any shared code must move through a properly named package before being imported by `api/`, `core/`, or `agents/`.

`mobile/` (React Native/Expo) and `orchestrate-mobile/` (Flutter sub-projects doublon) were deleted 2026-06-21 — the active Flutter app is `beamax_app/`.

## M1 Secondary Large Files (acknowledged, ratchet downward)

These files cross the 800-line threshold but are not the headline monoliths to split first. They are tracked so `tests/test_architecture_size_gate.py` can enforce the rule: any file in `api/`, `core/`, or `kernel/` over 800 lines must appear in this document. Aim to bring each down via the same incremental-extraction approach used for M1.

| File | Lines (audit 2026-05-28) | Suggested split direction |
|---|---|---|
| `core/self_improvement_loop.py` | ~1166 | Separate loop scheduling from candidate generation/scoring. |
| `core/tool_executor.py` | ~1080 | Extract tool dispatch from result normalization and error handling. |
| `core/capability_intelligence.py` | ~1074 | Split capability scoring from registry/lookup helpers. |
| `core/orchestration/reasoning_engine.py` | ~1038 | Extract step planner from output validators. |
| `api/routes/performance.py` | ~1027 | Move computation helpers out of the HTTP route module. |
| `core/orchestration/creative_engine.py` | ~1007 | Extract idea-generation prompts and scorer from the engine loop. |
| `api/routes/opportunities.py` | ~970 | Move pipeline glue and schemas out of the route module. |
| `core/self_improvement/promotion_pipeline.py` | ~933 | Split candidate selection from promotion side-effects. |
| `core/improvement_daemon.py` | ~916 | Extract scheduler from improvement-step execution. |
| `core/agent_specialization.py` | ~887 | Split scoring policy from registry/lookup. |
| `core/runtime_introspection.py` | ~844 | Extract probes from aggregators/reporters. |
| `core/modules/module_manager.py` | ~839 | Separate manifest parsing from runtime activation. |
| `core/llm_factory.py` | ~831 | Extract provider config from instantiation logic. |
| `core/evaluation_engine.py` | ~801 | Crossed the 800-line threshold after the M3 silent-swallow migration expanded the per-call `log.warning(...)` payload. Trim by extracting the per-metric helpers (approval_rate, timeout_rate, cost, error_count, patch_success_rate) into a small `core/evaluation_metrics.py`. |
| `core/business_actions.py` | ~814 | Grew past 800 lines after the revenue-launch sprint (2026-06-13) added autonomous business execution helpers and revenue routing. Extract `BusinessRevenueActions` into `core/business_revenue.py` and `BusinessMonitorActions` into `core/business_monitor.py` to bring the main file back under threshold. |

## Ratchet Rules

- No new file in `api/`, `core/`, or `kernel/` should exceed 800 lines without an architecture note in this document.
- No new generic `agent.py`, `registry.py`, `contracts.py`, `base.py`, or `main.py` should be added without updating this map.
- Refactors must preserve public imports first, then move callers in follow-up commits.
- `tests/test_architecture_size_gate.py` enforces the 800-line rule at CI time.
