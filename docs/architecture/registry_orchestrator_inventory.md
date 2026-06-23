# Registry & Orchestrator Inventory

> Last verified: 2026-06-23.
> Branch: `kilocode-kimi/import-contract-registry-ratchets`

---

## Summary

- **Registries found:** 23 distinct registry files (excluding `build/` mirrors and test files)
- **Orchestrators found:** 11 orchestrator files (3 in `core/`, 1 in `business/`, 1 in `core/cognition/`, 1 in `orchestrate-cli/` factory, 5 in `orchestrate-cli/` adapters)
- **Canonical orchestrator:** `core/meta_orchestrator.py` — MetaOrchestrator is the single entry point for all missions
- **Key finding — tool registry split:** There are intentionally **two** tool registries (`core/tool_registry.py` = definitions, `tools/tool_registry.py` = executor); they are documented as distinct but have the same class name `ToolRegistry`, creating confusion
- **Key finding — MCP registry duplication:** `core/mcp/mcp_registry.py` and `integrations/mcp/mcp_registry.py` serve similar purposes at different layers
- **Key finding — goal registry duplication:** `core/orchestration/goal_registry.py` (mission autonomy) and `core/self_improvement/goal_registry.py` (improvement goals) have completely different semantics despite the same filename
- **Convergence status:** All core missions funnel through MetaOrchestrator → `core/orchestrator.py` is a deprecated shim, `core/bea_executor.py` and `core/orchestrator_v2.py` are internal delegates never to be called directly

---

## Registries

### `kernel/capabilities/registry.py`

- **Purpose:** Source-of-truth for discrete capabilities the system can perform. Capability-first routing: the orchestrator routes by *what the system can do*, not *which agent does it*.
- **Registers:** 19 `Capability` objects (`plan_generation`, `plan_validation`, `decision_evaluation`, `skill_execution`, `tool_invocation`, `code_generation`, `quality_review`, `memory_write`, `memory_recall`, `risk_evaluation`, `policy_check`, `artifact_generation`, `market_intelligence`, `product_design`, `financial_reasoning`, `compliance_reasoning`, `risk_assessment`, `venture_planning`, `strategy_reasoning`). Categories: planning, execution, memory, policy, economic.
- **Populated by:** Statically at module import time via `KERNEL_CAPABILITIES` dict. `KernelCapabilityRegistry.__init__` copies `KERNEL_CAPABILITIES`. Runtime `register()` can add more; `kernel/runtime/boot.py` calls `get_capability_registry()` on startup.
- **Read by:** `kernel/adapters/capability_adapter.py`, `kernel/convergence/capability_bridge.py`, `kernel/capabilities/identity.py`, `core/economic/strategy_evaluation.py`, `core/self_model/queries.py`, `MetaOrchestrator` (via `kernel.runtime.kernel.run_cognitive_cycle` → capability routing)
- **Status:** canonical
- **Recommendation:** keep — this is the kernel-level authority for capability routing

---

### `agents/registry.py`

- **Purpose:** Agent instantiation catalogue. Maps agent-role strings to agent classes and provides `build_registry()` to hydrate all agents.
- **Registers:** 17 agent roles: core crew (`atlas-director`, `scout-research`, `web-scout`, `map-planner`, `forge-builder`, `lens-reviewer`, `vault-memory`, `shadow-advisor`, `pulse-ops`, `night-worker`) + business layer (`venture-builder`, `offer-designer`, `workflow-architect`, `saas-builder`, `trade-ops`, `meta-builder`, `openhands`).
- **Populated by:** Statically at import time via `AGENT_CLASSES` dict; `build_registry(settings)` instantiates on demand.
- **Read by:** `agents/agent_factory.py` (primary consumer, reads `AGENT_CLASSES` for lazy instantiation), `agents/crew_runtime.py` (registers missing agents at runtime), `core/agent_runner.py` (resolves agent names), `core/extension_registry.py` (enumerates registered agents for extension merge)
- **Status:** canonical
- **Recommendation:** keep — single source of truth for agent roles

---

### `core/tool_registry.py`

- **Purpose:** Tool **definition** registry — metadata layer (descriptions, risk levels, action types, network requirements). Does NOT execute tools.
- **Registers:** `ToolDefinition` objects for built-in tools (`read_file`, `write_file`, `list_directory`, `run_command_safe`, and others). Also exposes `rank_tools_for_task()` and `should_create_tool()` for gap analysis.
- **Populated by:** Statically from `_BASE_TOOLS` list at module load. Runtime extensions can call `register()`.
- **Read by:** Code that needs tool metadata for planning/routing decisions. Canonical import: `from core.tool_registry import get_tool_registry`.
- **Status:** canonical
- **Recommendation:** keep, but rename class from `ToolRegistry` to `ToolDefinitionRegistry` to disambiguate from `tools/tool_registry.py`

---

### `tools/tool_registry.py`

- **Purpose:** Tool **executor** registry — holds live tool instances and dispatches `execute()` calls. Runtime "can I run it?" layer.
- **Registers:** Live tool instances auto-registered via `_auto_register()` on first `get_instance()` call. `list_tools()` merges names from both live instances and `core/tool_registry.py` definitions.
- **Populated by:** Lazy at first use; `_auto_register()` scans and loads known tool implementations.
- **Read by:** Pipeline execution code that needs to invoke tools by name. Canonical import: `from tools.tool_registry import get_tool_registry`.
- **Status:** canonical
- **Recommendation:** keep as executor layer, but rename class to `ToolExecutorRegistry` (noted as deferred in the source file itself — this work is tracked). The two-registry split is intentional and should be documented at the API boundary.

---

### `core/tools_operational/tool_registry.py`

- **Purpose:** Registry for external **operational** tools Bea can invoke (business tools loaded from JSON definition files in `business/tools/`). Distinct from `core/tool_registry.py` (Python-native tools).
- **Registers:** `OperationalTool` objects loaded from JSON files in `business/tools/` directory. Supports programmatic `register()` too.
- **Populated by:** Lazily on first `get()` or `list_all()` call via `load_all()` which scans `business/tools/` for JSON files.
- **Read by:** Business layer pipelines needing external tool invocations (HTTP calls, third-party APIs).
- **Status:** canonical
- **Recommendation:** keep — distinct concern from the two tool registries above

---

### `plugins/plugin_registry.py`

- **Purpose:** Central registry for Bea plugins. Plugins are user-installed extensions with explicit metadata, signature verification, health checks, and RBAC-enforced install.
- **Registers:** `PluginMetadata` instances; stores plugin instances, metadata, and runtime status. No auto-discovery — all registrations are explicit `register()` calls.
- **Populated by:** Explicit `register()` calls at startup (application bootstrap). Admin-only write.
- **Read by:** Plugin invocation layer, health endpoints, `core/extension_registry.py` (for unified extension enumeration)
- **Status:** canonical
- **Recommendation:** keep

---

### `core/extension_registry.py`

- **Purpose:** Unified extensibility layer that merges core items (read-only, from code) with user extensions (from JSON, schema-validated). Covers agents, MCP connectors, skills, and tools in one registry. Admin-managed with audit trail and secret masking.
- **Registers:** Four extension types: `agent`, `mcp_connector`, `skill`, `tool`. Core items loaded from code; user extensions loaded from a JSON file on disk.
- **Populated by:** At startup — core items from code paths; user extensions from `workspace/extensions.json`. Admin writes via API.
- **Read by:** API routes for extension management, runtime merge providing the combined catalogue to consumers.
- **Status:** canonical
- **Recommendation:** keep — this is the single admin surface for user-managed extensions

---

### `core/mcp/mcp_registry.py`

- **Purpose:** MCP server integration catalogue with structured metadata, health checking, tool discovery, secret dependency tracking, and trust levels. Extends `ModuleManager`'s MCP layer.
- **Registers:** `MCPServerEntry` objects (includes trust level, transport, required secrets, discovered tools, health status, RBAC info).
- **Populated by:** Explicit registration calls; `kernel/runtime/boot.py` or startup hooks load known servers.
- **Read by:** MCP invocation layer, health endpoints.
- **Status:** canonical
- **Recommendation:** consolidate with `integrations/mcp/mcp_registry.py` (see below) — these two registries cover similar ground at different abstraction levels

---

### `integrations/mcp/mcp_registry.py`

- **Purpose:** Simpler in-memory MCP server + tool registry. Resolves `tool_id → server endpoint` at invocation time. Re-populated on each startup.
- **Registers:** `MCPServer` and `MCPTool` objects; tools indexed by `tool_id` for fast lookup.
- **Populated by:** Explicit `register_server()` calls at startup, then `register_tool()` calls as tools are discovered.
- **Read by:** `MCPAdapter` (resolves tool → server endpoint), health monitor (`update_health()`).
- **Status:** support
- **Recommendation:** consolidate into `core/mcp/mcp_registry.py` — this is a lower-level sibling that duplicates the concept. Migrate callers to use `core/mcp/mcp_registry.py` as the single MCP authority.

---

### `core/capability_routing/registry.py`

- **Purpose:** Runtime provider registry — maps `capability_id → list[ProviderSpec]`. Populated from live runtime sources (capability graph, MCP registry, module manager, tool permissions). Distinct from `kernel/capabilities/registry.py` which is the static definition layer.
- **Registers:** `ProviderSpec` objects keyed by capability ID. Sources: agents, MCP servers, tools, modules.
- **Populated by:** `populate()` called at runtime (on demand or by scheduler). Scans four sources: agents, MCP, tools, modules.
- **Read by:** Routing layer in MetaOrchestrator's cognitive cycle for provider resolution.
- **Status:** canonical
- **Recommendation:** keep — this is the dynamic runtime complement to the static `kernel/capabilities/registry.py`

---

### `core/skills/skill_registry.py`

- **Purpose:** Persistent skill store. Skills are discoverable capabilities Bea acquires from mission successes. JSONL-backed for grep-friendliness and no DB dependency.
- **Registers:** `Skill` objects, persisted to `workspace/skills.jsonl`. Loaded into memory on init.
- **Populated by:** At init (loads from JSONL); runtime `save()` calls when new skills are discovered (by the improvement/learning loop).
- **Read by:** Mission planner when selecting execution strategies; improvement daemon.
- **Status:** canonical
- **Recommendation:** keep

---

### `core/execution/strategy_registry.py`

- **Purpose:** Execution strategy catalogue with auto-promotion. Named strategies (`StrategyProfile`) with model preferences, budget modes, and template configs. Promotes better strategies when they outperform the current default.
- **Registers:** `StrategyProfile` objects. Persisted to `workspace/strategies.json`.
- **Populated by:** Default strategies defined in code; runtime strategies promoted via `promote()` when outperforming thresholds (`MIN_SAMPLES=5`, `MIN_IMPROVEMENT=5%`).
- **Read by:** Execution pipeline when selecting model/budget strategy for a task type.
- **Status:** canonical
- **Recommendation:** keep

---

### `core/tool_config_registry.py`

- **Purpose:** Makes tool/module dependencies on secrets and configs explicit. Each module declares `DependencyDeclaration` (required and optional secrets/configs). Used to compute `DependencyStatus` (ready / needs_setup / degraded).
- **Registers:** `DependencyDeclaration` objects keyed by `module_id`.
- **Populated by:** Explicit `declare()` calls when modules/tools register themselves (startup hooks). Integrates with Vault for secret existence checks (never stores raw secrets).
- **Read by:** Health endpoints, `ModuleManager` (marks module status as `needs_setup` when dependencies missing).
- **Status:** canonical
- **Recommendation:** keep

---

### `core/orchestration/goal_registry.py`

- **Purpose:** Persistent proactive goal store — tracks Bea's ongoing autonomous objectives (not improvement goals). Goals have a horizon (`immediate`/`weekly`/`monthly`/`permanent`), priority, progress, and next action. Backed by JSONL.
- **Registers:** `ProactiveGoal` objects with staleness tracking.
- **Populated by:** At init (loads from JSONL); runtime goal creation and progress updates.
- **Read by:** Proactive loop (`core/orchestration/proactive_loop.py`), autonomy routes.
- **Status:** canonical
- **Recommendation:** keep. Note: name collision with `core/self_improvement/goal_registry.py` — these are unrelated.

---

### `core/self_improvement/goal_registry.py`

- **Purpose:** Defines what "better" means for the self-improvement daemon. Immutable `ImprovementGoal` objects with metric name, baseline, target direction, safety impact, and allowed change scope.
- **Registers:** `ImprovementGoal` frozen dataclass instances. Default v1 goals hardcoded.
- **Populated by:** Statically in code (default goals); `ImprovementGoalRegistry.add()` at runtime for custom goals.
- **Read by:** `core/improvement_daemon.py` (reads active goals to decide which metrics to chase), improvement cycle.
- **Status:** canonical
- **Recommendation:** keep. Consider renaming to `improvement_goal_registry.py` to disambiguate from `core/orchestration/goal_registry.py`.

---

### `core/agents/agent_registry.py`

- **Purpose:** Multi-agent coordination registry. Extends `role_definitions.py` with inter-agent messaging protocol, task routing by role + performance, availability tracking, and coordination history. Works alongside `agents/agent_factory.py`, does not replace it.
- **Registers:** `AgentStatus` entries (availability, task counts, latency, error streak) keyed by agent name. Built on `core/agents/role_definitions.ROLE_DEFINITIONS`.
- **Populated by:** At runtime when agents are activated; `AgentCoordinationRegistry.register_agent()` called by the crew dispatcher.
- **Read by:** `agents/crew_runtime.py`, multi-agent coordination layer.
- **Status:** canonical
- **Recommendation:** keep

---

### `memory/capability_registry.py`

- **Purpose:** Lightweight agent-capability scoring registry derived from `decision_memory.jsonl`. Computes `AgentCapabilityScore` per agent from historical mission data. No persistence of its own — reconstructed on demand.
- **Registers:** `AgentCapabilityScore` objects in memory, computed from `DecisionMemory` (at most 1000 entries, O(n)).
- **Populated by:** On-demand when queried; reads `decision_memory.jsonl` and aggregates.
- **Read by:** Task router, planner logic for recommending agents based on historical performance.
- **Status:** support
- **Recommendation:** keep as a performance-scoring complement to `agents/registry.py`

---

### `api/router_registry.py`

- **Purpose:** FastAPI router registration and health tracking. Provides structured `register_router()` and `get_registry_status()` for all API routers in BeaMax, replacing silent try/except with explicit logging.
- **Registers:** `RouterEntry` objects (router instance + prefix, tags, route count, load status).
- **Populated by:** Startup (`api/main.py` lifespan) — each router module registers itself.
- **Read by:** `/system/status` health endpoint, `api/main.py` for router mounting.
- **Status:** canonical
- **Recommendation:** keep

---

### `agents/bea_team/tools/_registry.py`

- **Purpose:** Static access control matrix mapping agent roles to permitted tool names. Defines `AGENT_TOOL_ACCESS` dict — which agent can call which tools.
- **Registers:** No class — pure data. Dict of `{agent_role: set[tool_name]}` for roles: `bea-architect`, `bea-coder`, `bea-reviewer`, `bea-qa`, `bea-devops` (and more).
- **Populated by:** Statically in code (hardcoded access matrix).
- **Read by:** Tool invocation gate — checked before allowing an agent to call a tool.
- **Status:** canonical
- **Recommendation:** keep

---

### `mcp/hexstrike_v2/registry.py`

- **Purpose:** Security tool registry for the HexStrike security module (cyber/pentest tools). Modeled after the hermes-agent pattern. Separate from the main tool registries.
- **Registers:** `ToolDefinition` objects with security-specific fields: `category` (recon, scanning, exploitation, web, network, reporting), `risk_level`, `requires_approval`, `requires_env`, `check_fn`.
- **Populated by:** Explicit `register()` calls within `mcp/hexstrike_v2/` module setup.
- **Read by:** HexStrike tool invocation layer.
- **Status:** experimental
- **Recommendation:** keep isolated in its module; do not merge with `core/tool_registry.py`

---

### `orchestrate-cli/src/utils/tool_registry.py`

- **Purpose:** Tool registry for the standalone `orchestrate-cli` sub-project. Manages cross-framework tool registration, discovery, categorization, and dynamic loading for LangChain/AutoGen/CrewAI frameworks.
- **Registers:** Framework-agnostic tool definitions (web_search, etc.) with per-framework tagging.
- **Populated by:** `_register_default_tools()` at init; dynamic loading from module paths.
- **Read by:** `orchestrate-cli` orchestrators (LangChain, AutoGen, CrewAI, LlamaIndex, Haystack adapters).
- **Status:** support (scoped to `orchestrate-cli` sub-project)
- **Recommendation:** keep isolated in `orchestrate-cli/` — this is an independent CLI tool, not part of the main Bea runtime

---

### `core/capabilities/registry.py`

- **Purpose:** Tool execution policy registry — a **different concern** from `kernel/capabilities/registry.py`. Where the kernel registry maps capability IDs to routing metadata, this registry answers the question "is this tool allowed to run, and under what conditions?" All tools must be registered here; unregistered tools are rejected at the executor level. HIGH-risk tools (`shell_execute`, `code_execute`) require operator approval before execution.
- **Registers:** `Capability` objects (from `core/capabilities/schema.py`) keyed by tool name. 16 built-in tools across two groups — core tools (`web_search`, `web_fetch`, `shell_execute`, `file_write`, `file_read`, `memory_write`, `memory_read`, `api_call`, `code_execute`, `browser_navigate`) and business tools (`email_send`, `http_request`, `http_test`, `markdown_generate`, `html_generate`, `json_schema_generate`). Each entry declares `risk_level` (LOW/MEDIUM/HIGH), `requires_approval`, and `timeout_seconds`.
- **Class:** `CapabilityRegistry` with `check_permission(tool_name, agent_name)`, `list_by_risk()`, and `stats()`. Singleton via `get_capability_registry()`.
- **Populated by:** Statically from `_CORE_CAPABILITIES` list at init; runtime `register()` can add more.
- **Read by:** `ToolExecutor` pre-execution gate (rejects unregistered tools, pauses for approval on HIGH-risk ones). `api/routes/action_console.py` reads the registry for displaying the capability catalogue.
- **Status:** canonical
- **Recommendation:** keep — this is the tool execution gatekeeper; do not confuse with `kernel/capabilities/registry.py` which is a routing/routing-metadata registry, or with `core/tool_permissions.py` which handles the approval lifecycle

---

### `core/tool_permissions.py`

- **Purpose:** Declarative per-tool approval gating registry — manages the **lifecycle** of approval requests for high-risk tool executions. Distinct from `core/capabilities/registry.py` which defines whether approval is needed; this module manages the approval workflow itself (create → approve/deny → expire). Includes secret scrubbing for safe display of approval payloads.
- **Registers:** `ToolPermission` objects (declarative gate declarations) keyed by tool name. 10 default gated tools: shell/code execution (`shell_command`, `execute_code`), destructive file ops (`file_delete_safe`, `replace_in_file`), git with side effects (`git_push`, `git_commit`), Docker lifecycle (`docker_restart`, `docker_compose_down`, `docker_compose_up`, `docker_compose_build`). Also tracks `ApprovalRequest` instances in memory.
- **Class:** `ToolPermissionRegistry` with `check(tool_name, params, mission_id, agent_id)` (creates `ApprovalRequest` on gate trigger), `approve(request_id)`, `deny(request_id)`, `get_pending()`, `get_history()`. Singleton via `get_tool_permissions()`.
- **Populated by:** Statically from `_DEFAULT_GATED_TOOLS` dict at init; runtime `register()` for custom gates.
- **Read by:** `api/routes/action_console.py` (displays pending approvals, handles approve/deny), `ToolExecutor` pre-execution flow, `ApprovalNotifier` (push notification).
- **Status:** canonical
- **Recommendation:** keep — this is the approval-lifecycle layer; complements `core/capabilities/registry.py` (policy definition) and `agents/bea_team/tools/_registry.py` (access control matrix)

---

## Orchestrators

### `core/meta_orchestrator.py` — MetaOrchestrator

- **Role:** Facade and single entry point for the entire mission lifecycle. Owns the state machine (`CREATED → PLANNED → RUNNING → REVIEW → DONE / FAILED`), emits state-change events, persists state to disk, and delegates actual execution to `BeaOrchestrator` (standard missions) or `OrchestratorV2` (budget/DAG missions). Also runs the kernel cognitive cycle (classification, planning, capability routing) before delegating.
- **Entry point:** `MetaOrchestrator.run_mission(goal, mode, ...)` — the canonical call for all new missions. Also exposes `get_mission()`, `run()` (legacy alias), and custom handler registration via `register_custom_handler()`.
- **Called by:** `api/main.py`, `api/lifespan.py`, `api/mission_approval.py`, `api/routes/autonomy.py`, `api/routes/convergence.py`, `api/routes/system_readiness.py`, `api/_deps.py`, `beamax_cli.py`. All entry points go through `get_meta_orchestrator()` singleton accessor.
- **Internal structure:** Composed of five mixins: `RoutingMixin` (agent/provider selection), `ExecutionMixin` (delegate calls + circuit breaker), `OutcomeMixin` (result finalization + reporting), `LearningMixin` (post-mission learning), `CustomMissionHandlerMixin` (user-defined mission type handlers, from `core/meta_custom_handlers.py` — provides `register_custom_handler()`). Circuit breaker (`MissionCircuitBreaker`) opens after 5 consecutive delegate failures (resets after 60s).
- **Status:** canonical
- **Recommendation:** keep — do not bypass; all new code must enter through `get_meta_orchestrator()`

---

### `core/bea_executor.py` — BeaOrchestrator

- **Role:** Internal execution delegate for MetaOrchestrator. Receives a `BeaSession`, dispatches to the appropriate pipeline mixin based on mode, and returns a populated session. All heavy logic lives in executor mixins under `core/executor/`: `LazyComponentsMixin`, `PipelineAutoMixin`, `PipelineModesMixin`, `ReportingMixin`.
- **Entry point:** `BeaOrchestrator.run(user_input, mode, session_id, callback)` — called only by MetaOrchestrator, never directly.
- **Called by:** `MetaOrchestrator.bea` lazy property (MetaOrchestrator only). `OrchestratorV2` also calls `BeaOrchestrator.run()` internally.
- **Mode dispatch:** `auto/code/business/plan/research` → `PipelineAutoMixin._run_auto`; `chat` → `_run_chat`; `night` → `_run_night`; `improve` → `_run_improve`; `workflow` → `_run_workflow`
- **Status:** active-delegate
- **Recommendation:** keep as internal delegate — do not instantiate directly in new code

---

### `core/orchestrator_v2.py` — OrchestratorV2

- **Role:** Budget/DAG delegate used by MetaOrchestrator when `use_budget=True`. Adds three capabilities on top of BeaOrchestrator: `BudgetGuard` (max_tokens / max_time_s / max_cost_usd enforcement), `TaskDAG` (topological-sort parallel execution), `CheckpointStore` (resume interrupted DAGs via asyncpg + SQLite fallback).
- **Entry point:** `OrchestratorV2.run(user_input, mode, session_id, budget)` — wraps `BeaOrchestrator.run()` with budget enforcement.
- **Called by:** `MetaOrchestrator.v2` lazy property when `use_budget=True`. Never directly in external code.
- **Status:** active-delegate
- **Recommendation:** keep — the budget/DAG layer is a well-defined extension point

---

### `core/orchestrator.py` — (deprecated shim)

- **Role:** Import compatibility shim only. Re-exports everything from `core/bea_executor.py` via `from core.bea_executor import *`. Emits `DeprecationWarning` on import.
- **Entry point:** None — purely a re-export shim.
- **Called by:** Legacy code that has not yet migrated to `core.bea_executor` or `core.meta_orchestrator`. Search for `from core.orchestrator import` to find remaining call sites.
- **Status:** deprecated-shim
- **Recommendation:** migrate all remaining importers, then remove. Priority: medium.

---

### `core/orchestration_bridge.py` — OrchestrationBridge

- **Role:** Safe migration layer routing `MissionSystem` calls through MetaOrchestrator as canonical authority. Preserves `MissionSystem` as importable facade with no breaking changes. Feature-flagged: active when `BEA_USE_CANONICAL_ORCHESTRATOR=1` (default true).
- **Entry point:** `submit_mission(goal)`, `get_mission_canonical(mission_id)`, `approve_mission()`, `reject_mission()` — module-level functions backed by `OrchestrationBridge` singleton.
- **Called by:** API routes and internal code that previously used `MissionSystem` directly; the bridge transparently reroutes to MetaOrchestrator.
- **Status:** active-delegate
- **Recommendation:** keep until `MissionSystem` is fully deprecated; once all call sites use MetaOrchestrator directly, remove the bridge

---

### `core/orchestration_guard.py` — OrchestrationGuard

- **Role:** Retry policy and fallback agent supervisor for pulse-ops style tasks. Wraps task execution with max retries (default 3), per-attempt timeout (default 60s), ordered fallback agent list, and persistent log (`workspace/orchestration_log.jsonl`). Works alongside the orchestrator, does not replace it.
- **Entry point:** `OrchestrationGuard.run_guarded(task_id, agent_id, task_fn)` — async wrapper that applies retry + fallback policy.
- **Called by:** Execution pipeline when running guarded tasks (typically pulse-ops or high-stakes operations).
- **Status:** canonical
- **Recommendation:** keep as a support utility

---

### `core/orchestration_intelligence.py` — (stub)

- **Role:** Placeholder stub for an intelligence routing module. Contains `CapabilityDispatcher.dispatch()` (always returns `CONVERSATION/0.5/fallback=True`) and `MissionPlanner.create_plan()` / `validate_plan()` (return empty). Present for test collection compatibility.
- **Entry point:** `CapabilityDispatcher.dispatch(query)`, `MissionPlanner.create_plan()`
- **Called by:** Tests only (import for type checking); not wired into production pipeline.
- **Status:** stub
- **Recommendation:** implement or remove — currently dead code in production. If `kernel/capabilities/registry.py` covers the dispatch use case, this stub can be deleted.

---

### `core/cognition/orchestrator.py` — CognitionOrchestrator

- **Role:** Integrates AGI-like cognition patterns for mission execution: Tree of Thought (ToT), self-confidence scoring, auto-correction, performance tracking, skill discovery, and business engine integration. Coordinates these sub-systems into a unified `execute()` flow.
- **Entry point:** `CognitionOrchestrator.execute(mission)` — takes a mission dict, optionally applies ToT, scores output confidence, auto-corrects on low confidence.
- **Called by:** Advanced pipeline paths that opt into ToT/confidence augmentation. Not wired into MetaOrchestrator's core path by default; used by agents or mission modes that need deep cognition.
- **Status:** experimental
- **Recommendation:** keep experimental — integrate more tightly with MetaOrchestrator's cognitive cycle pass or promote to an `ExecutionMixin`

---

### `business/business_orchestrator.py` — BusinessOrchestrator

- **Role:** Orchestrates the full business lifecycle for Bea's autonomous ventures: Discover → Build → Launch → Operate. Manages `Business` state machines with human approval gates at every major decision point. Phases: `DISCOVERY`, `BUILD`, `LAUNCH`, `OPERATE`, `PAUSED`, `FAILED`.
- **Entry point:** `BusinessOrchestrator.start_business(opportunity)`, `advance_phase(business_id)`, `submit_approval(business_id, decision)`.
- **Called by:** Business layer missions and the `business/` module when Bea runs autonomous business operations. Invoked via MetaOrchestrator in `business` mode (dispatched through `BeaOrchestrator._run_auto` with `forge-builder`/`meta-builder` agents).
- **Status:** canonical
- **Recommendation:** keep — domain-specific orchestrator properly scoped to business lifecycle; does not need to merge with MetaOrchestrator

---

### `orchestrate-cli/src/orchestrators/orchestrator_factory.py` — OrchestratorFactory

- **Role:** Factory for the standalone `orchestrate-cli` tool. Creates framework-specific orchestrators (LangChain, AutoGen, CrewAI, LlamaIndex, Haystack) and CLI agents (Gemini, Codex, Claude Code, GitHub Copilot, Aider, OpenCode, OpenHands, Cursor). Independent from the main Bea runtime.
- **Entry point:** `OrchestratorFactory(config)` — then `factory.get_orchestrator('langchain')` etc.
- **Called by:** `orchestrate-cli` CLI entrypoint. Completely isolated from Bea's `core/` namespace.
- **Status:** canonical (within `orchestrate-cli` scope)
- **Recommendation:** keep isolated in `orchestrate-cli/` — this is a separate CLI tool

---

### `orchestrate-cli/src/frameworks/*.py` — Framework Adapters

Files: `langchain_orchestrator.py`, `autogen_orchestrator.py`, `crewai_orchestrator.py`, `llamaindex_orchestrator.py`, `haystack_orchestrator.py`

- **Role:** Thin adapters wrapping third-party AI frameworks (LangChain, AutoGen, CrewAI, LlamaIndex, Haystack) with a uniform interface for the `orchestrate-cli` tool.
- **Entry point:** Each implements `.run(task)` or equivalent framework-specific method.
- **Called by:** `OrchestratorFactory` only.
- **Status:** canonical (within `orchestrate-cli` scope)
- **Recommendation:** keep isolated

---

## Convergence Recommendation

### Registry convergence

The registries cover distinct concerns and should **not** be merged into a single monolith. The recommended clean architecture is:

```
kernel/capabilities/registry.py     ← static capability definitions / routing metadata (what can be done)
core/capabilities/registry.py       ← tool execution policy (is this tool allowed to run?)  ← DIFFERENT from above
core/capability_routing/registry.py ← runtime provider mapping (who does it, right now)
agents/registry.py                  ← agent class catalogue (instantiation)
core/agents/agent_registry.py       ← runtime agent coordination (availability, performance)
memory/capability_registry.py       ← historical scoring (who has done it best)

core/tool_registry.py               ← tool metadata/definitions
tools/tool_registry.py              ← tool execution (live instances)
core/tools_operational/tool_registry.py ← operational/external tools (JSON-defined)
core/tool_permissions.py            ← per-tool approval lifecycle (gating + approve/deny workflow)
agents/bea_team/tools/_registry.py  ← access control matrix (who can call what)

core/mcp/mcp_registry.py            ← MCP server metadata + trust + health
integrations/mcp/mcp_registry.py    ← MCP tool routing (can consolidate into core/mcp/)

plugins/plugin_registry.py          ← plugin lifecycle
core/extension_registry.py          ← unified admin surface (agents + skills + tools + MCP)
api/router_registry.py              ← FastAPI router mounting

core/skills/skill_registry.py       ← persistent skill store
core/execution/strategy_registry.py ← execution strategy auto-promotion
core/tool_config_registry.py        ← secret/config dependency declarations

core/orchestration/goal_registry.py    ← proactive mission goals (rename for clarity)
core/self_improvement/goal_registry.py ← improvement metric goals (rename for clarity)
```

**Note on the two capability registries:** `kernel/capabilities/registry.py` (`KernelCapabilityRegistry`) and `core/capabilities/registry.py` (`CapabilityRegistry`) are intentionally distinct and should **not** be merged. The kernel registry is a routing table — it answers "what abstract capabilities exist and which agent roles provide them?" The core registry is an execution gate — it answers "is this concrete tool name permitted to execute, and at what risk level?" They use different `Capability` schemas (kernel's from `kernel/capabilities/` vs core's from `core/capabilities/schema.py`) and are consumed at different points in the pipeline.

**One concrete consolidation to do:** merge `integrations/mcp/mcp_registry.py` into `core/mcp/mcp_registry.py`. They serve the same purpose at adjacent layers.

### Orchestrator call graph

```
API / CLI (api/main.py, beamax_cli.py, Telegram bot)
    └─► get_meta_orchestrator()                        [core/meta_orchestrator.py]
            │
            ├─ _run_kernel_cognitive_cycle()           [kernel.runtime.kernel]
            │       └─► kernel/capabilities/registry  [capability routing]
            │       └─► core/capability_routing/registry [provider resolution]
            │
            ├─► MetaOrchestrator.bea                   [lazy: core/bea_executor.py]
            │       └─► BeaOrchestrator.run()
            │               ├─► PipelineAutoMixin._run_auto   (default)
            │               ├─► PipelineModesMixin._run_chat
            │               ├─► PipelineModesMixin._run_night
            │               ├─► PipelineModesMixin._run_improve
            │               └─► PipelineModesMixin._run_workflow
            │
            └─► MetaOrchestrator.v2  (use_budget=True) [lazy: core/orchestrator_v2.py]
                    └─► OrchestratorV2.run()
                            └─► BeaOrchestrator.run()  [inner delegate]

Side-paths (not bypassing MetaOrchestrator):
    core/orchestration_bridge.py  ──► submit_mission() → MetaOrchestrator
    business/business_orchestrator.py ─► called by MetaOrchestrator in 'business' mode
    core/orchestration_guard.py  ──► wraps individual tasks within pipeline
    core/cognition/orchestrator.py ─► called by advanced pipeline paths (opt-in)
```

### Which orchestrator is the authority?

`MetaOrchestrator` is the **sole** authority for mission lifecycle. It owns:
- State transitions (CREATED → PLANNED → RUNNING → REVIEW → DONE/FAILED)
- Event emission on state changes
- Persistence of mission state to disk
- Circuit breaker for delegate failures
- The cognitive cycle (kernel classification + plan + routing)

`BeaOrchestrator` and `OrchestratorV2` are **execution engines** — they have no authority over mission lifecycle state. They receive work and return results; MetaOrchestrator handles everything else.

---

## What NOT to do

1. **Never instantiate `BeaOrchestrator` or `OrchestratorV2` directly** in new code. Always use `get_meta_orchestrator()`. These delegates are internal implementation details.

2. **Never import from `core.orchestrator`** — it is a deprecated shim that emits `DeprecationWarning`. Use `core.meta_orchestrator` (for the facade) or `core.bea_executor` (if you legitimately need the executor, which you almost certainly don't).

3. **Do not bypass the orchestration bridge** — when legacy code uses `MissionSystem`, the bridge (`core/orchestration_bridge.py`) transparently routes to MetaOrchestrator. Do not add direct `MissionSystem` calls that circumvent this.

4. **Do not confuse the two tool registries.** `core/tool_registry.py` is for metadata/discovery. `tools/tool_registry.py` is for execution. Importing the wrong one will either silently skip execution (metadata only) or miss planning context (executor only).

5. **Do not confuse the two goal registries.** `core/orchestration/goal_registry.py` tracks Bea's autonomous mission objectives (proactive work items). `core/self_improvement/goal_registry.py` tracks metric targets for the improvement daemon. They are completely unrelated.

6. **Do not add MCP servers to `integrations/mcp/mcp_registry.py` for new work.** Prefer `core/mcp/mcp_registry.py` which has richer metadata, trust levels, and health tracking. The integrations registry is a candidate for consolidation.

7. **Do not add new agents to `core/agents/agent_registry.py` thinking it is the agent catalogue.** That file is the runtime coordination/messaging layer. New agent classes go into `agents/registry.py` (`AGENT_CLASSES` dict).

8. **Do not call `CognitionOrchestrator` or `BusinessOrchestrator` from outside their modules** — both are invoked through MetaOrchestrator's execution path. Direct instantiation skips state machine tracking, event emission, and the circuit breaker.

---

## ToolExecutor Advisory Layers — Fail-open notes

`core/tool_executor.py` applies **three advisory layers** before the hard policy gate.
All three are fail-open: if the advisory module crashes, execution continues.
The hard blockers that can never be bypassed are listed separately.

### Advisory layers (fail-open)

| Layer | Module | Behaviour on failure |
|-------|--------|---------------------|
| Capability registry check | `core/capabilities/registry.py` via `get_capability_registry()` | Logs `capability_check_skipped`, execution continues |
| Per-tool permission gate | `core/tool_permissions.py` via `get_tool_permissions()` | Logs `tool_permission_check_skipped`, execution continues |
| ExecutionPolicy advisory | `core/execution_policy.py` via `get_execution_policy()` | Logs `policy_check_failed_open`, execution continues |

**Implication:** these three layers provide defense-in-depth and audit visibility, but they cannot be relied on alone for hard blocking. Any tool that is fail-open through all three layers will still be stopped by the hard gates below.

### Hard blockers (fail-closed)

| Gate | Module | Behaviour |
|------|--------|-----------|
| PolicyEngine.evaluate_tool() | `core/policy_engine.py` via `get_policy_engine()` | HIGH-risk tools always blocked; session limits enforced when `mission_id` is propagated; falls back fail-CLOSED for execute/high-risk when unavailable |
| RiskEngine.analyze() | `executor/supervised_executor.py` | Exception → classified HIGH → blocked (no dry-run bypass) |
| SupervisedExecutor | `executor/supervised_executor.py` | Enforces approval gate; approval workflow managed by `core/tool_permissions.py` |
| Kill switch | `BEA_EXECUTION_DISABLED=1` env var | Blocks all tool execution process-wide |
| Circuit breaker | `core/resilience` via `get_circuit_breaker()` | Blocks tools in open state (fail-CLOSED) |

**Policy singleton discipline:** `ToolExecutor` must always call `get_policy_engine()` (the shared singleton) — never `PolicyEngine(None)` directly. Constructing a fresh instance bypasses session tracking and makes economic limits invisible across orchestrator calls. This is verified by `tests/test_tool_executor_singleton.py`.
