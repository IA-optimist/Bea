# Major Architecture Debt Map

This file tracks the MAJOR audit items M1 and M5 so refactors can happen incrementally instead of as a big-bang rewrite.

## M1 Monoliths To Split First

| File | Current role | First extraction boundary |
|---|---|---|
| `core/meta_orchestrator.py` | High-level orchestration, routing, fallback behavior | Extract routing policy, execution state, and fallback decisions into focused modules. |
| `core/connectors/_base.py` | Connector contracts plus runtime helpers | Split protocol contracts from concrete lifecycle/runtime helpers. |
| `core/mission_system.py` | Mission lifecycle, classification, persistence glue | Extract mission classification and state transitions first. |
| `api/routes/missions.py` | HTTP routes plus mission orchestration glue | Move request/response schemas and service calls out of the route module. |
| `agents/crew.py` | Agent base class, concrete agents, legacy facades | AgentSelector is now in `agents/selector.py`; AgentCrew registry/dispatch is now in `agents/crew_runtime.py`; next split should move BaseAgent or concrete prompt agents. |
| `core/jarvis_executor.py` | Execution facade and operational helpers | Extract command policy and execution result normalization. |
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

`orchestrate-cli/` and `orchestrate-mobile/` are standalone sub-projects, non-importable as Python packages. Keep them excluded from repo-wide Python lint/type assumptions unless they are migrated into normal package names. Any shared code must move through a properly named package before being imported by `api/`, `core/`, or `agents/`.

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

## Ratchet Rules

- No new file in `api/`, `core/`, or `kernel/` should exceed 800 lines without an architecture note in this document.
- No new generic `agent.py`, `registry.py`, `contracts.py`, `base.py`, or `main.py` should be added without updating this map.
- Refactors must preserve public imports first, then move callers in follow-up commits.
- `tests/test_architecture_size_gate.py` enforces the 800-line rule at CI time.
