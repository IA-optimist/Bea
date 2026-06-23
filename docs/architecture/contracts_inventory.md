# Execution Contracts Inventory

> Last verified: 2026-06-23. Maintained in `docs/architecture/contracts_inventory.md`.

## Summary

The codebase contains **three distinct families of `ExecutionResult`** (executor, kernel/types, kernel/execution) plus several satellite result types (`ActionResult`, `MissionResult`, `AgentResult`, `CapabilityResult`, `ConnectorResult`, `KernelAgentResult`). The clearest duplication concern is the three-way `ExecutionResult` split: `executor/contracts.py` (the package-level canonical claim), `kernel/contracts/types.py` (minimal kernel domain type), and `kernel/execution/contracts.py` (API-facing kernel shell result). There is also a legacy alias (`executor/runner.py: ExecutionResult = ActionResult`) and two independent `MissionResult` definitions with different purposes. In total, **18 execution-outcome contract types** are documented below across 9 source files.

---

## Contract Types

### `ExecutionResult` — executor/contracts.py (declared canonical)

- **Location:** `executor/contracts.py:39`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `execution_id` | `str` | Auto-generated short UUID |
| `task_id` | `str` | Caller-provided task reference |
| `status` | `ExecutionStatus` | Enum: SUCCESS / FAILED / TIMEOUT / SKIPPED / PENDING_APPROVAL |
| `success` | `bool` | Shortcut flag |
| `error_class` | `ErrorClass` | Structured error taxonomy (12 values) |
| `error_message` | `str` | Human-readable error |
| `retryable` | `bool` | Whether caller should retry |
| `started_at` / `finished_at` | `float` | Unix timestamps |
| `duration_ms` | `int` | Wall-clock ms |
| `tool_used` | `str` | Name of tool that produced this result |
| `risk_level` | `str` | low / medium / high |
| `confidence` | `float` | 0.0–1.0 |
| `raw_output` | `str` | Truncated to 500 chars in `to_dict()` |
| `normalized_output` | `str` | Truncated to 500 chars in `to_dict()` |
| `validation_status` | `str` | validated / invalid / unvalidated |
| `attempt` | `int` | Current retry attempt number |
| `max_retries` | `int` | Max allowed retries |

- **Key methods:** `.complete(success, output, error)` — finalize; `.to_dict()` — serialize
- **Produced by:** `executor/execution_engine.py`, `executor/task_model.py` (re-exported), `executor/handlers/*`
- **Consumed by:** `executor/__init__.py` (re-exported as package public API), `tests/test_e2e_final.py`, `tests/test_elite_pillars.py`, `tests/test_pillar_integration.py`, `executor/task_model.py`
- **Status:** **Declared canonical** by package docstring — `executor/__init__.py` imports and re-exports it as `executor.ExecutionResult`. The comment "THE one result model" appears in `executor/__init__.py:6`.
- **Recommendation:** **Keep as canonical for tool/task execution layer.** All executor-layer code should import from `executor.contracts` or the `executor` package directly.

---

### `ExecutionResult` — kernel/contracts/types.py (kernel domain type)

- **Location:** `kernel/contracts/types.py:376`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `ok` | `bool` | Success flag |
| `output` | `dict` | Structured output dict |
| `error` | `str` | Error message |
| `duration_ms` | `float` | Execution time in ms |
| `artifacts` | `list[str]` | Paths to produced artifacts |
| `step_id` | `str` | Associated plan step |
| `mission_id` | `str` | Associated mission |

- **Produced by:** `kernel/adapters/result_adapter.py:tool_result_to_kernel()` (converts dict → this type)
- **Consumed by:** `kernel/contracts/__init__.py` (re-exported), `kernel/adapters/result_adapter.py`, tests in `tests/test_integration_kernel_security_business.py`
- **Status:** **Domain contract** — this is the kernel's internal language for what happened after a step executed. Intentionally minimal (no timing IDs, no retry metadata). Different scope from `executor/contracts.py`.
- **Recommendation:** **Keep, but rename to `StepExecutionResult`** to disambiguate from the API-facing `kernel/execution/contracts.py:ExecutionResult`. The name collision between these two is the most confusing point in the codebase.

---

### `ExecutionResult` — kernel/execution/contracts.py (API shell / kernel output)

- **Location:** `kernel/execution/contracts.py:57`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `mission_id` | `str` | Required |
| `status` | `ExecutionStatus` | Enum: CREATED / RUNNING / AWAITING_APPROVAL / REVIEW / DONE / FAILED / CANCELLED |
| `result` | `str` | Final report string |
| `error` | `Optional[str]` | Error if failed |
| `metadata` | `dict` | Arbitrary extra data |
| `goal` | `str` | Original goal (truncated) |
| `mode` | `str` | Execution mode |
| `created_at` | `float` | Timestamp |

- **Key methods:** `.get_output(agent)` — backward-compat with `BeaSession`; `.final_report` property; `.is_terminal()`; `.from_context(ctx)` classmethod (factory from `MissionContext` or dict)
- **Produced by:** `kernel/runtime/kernel.py:BeaKernel.execute()` — wraps raw `MetaOrchestrator` output
- **Consumed by:** `kernel/runtime/kernel.py`, `kernel/execution/__init__.py` (re-exported), `interfaces/kernel_adapter.py`, `tests/unit/test_imports.py`
- **Status:** **API boundary type** — this is what `BeaKernel.execute()` returns to callers (API routes, interfaces). It wraps whatever the orchestrator returns into a stable contract. Serves a different purpose from the other two `ExecutionResult` types.
- **Recommendation:** **Keep, but rename to `KernelExecutionResult`** to end the three-way collision. All three `ExecutionResult` types have legitimate roles; the problem is the shared name.

---

### `ActionResult` — executor/runner.py (shell/file action result)

- **Location:** `executor/runner.py:145`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Required |
| `action_type` | `str` | Required — e.g. "read_file", "write_file", "shell" |
| `target` | `str` | Required — path or command target |
| `output` | `str` | Required — stdout/content |
| `error` | `str | None` | Error message |
| `backup_path` | `str | None` | Path to backup before write |
| `duration_ms` | `int` | Execution duration |

- **Key methods:** `.to_dict()`, `.format_output()` (human-readable), `.is_rejected_by_whitelist()`
- **Note:** Line 185 also defines `ExecutionResult = ActionResult` as a local alias to support callers that used the old name.
- **Produced by:** `executor/runner.py:ActionExecutor._read_file()`, `._write_file()`, `._backup_action()`, and related methods
- **Consumed by:** `api/routes/system.py` (imports `ActionExecutor`), `core/autonomy/__init__.py` (re-exports this type from `core/autonomy/daemon.py`'s own copy — see below)
- **Status:** **Legitimate specialized type** for file/shell operations. Fields (`action_type`, `target`, `backup_path`) are specific to file executor concerns not present in generic `ExecutionResult`. The local `ExecutionResult = ActionResult` alias is a **legacy artifact** that should be cleaned up.
- **Recommendation:** **Keep `ActionResult`, remove the `ExecutionResult` alias** at line 185. The alias creates confusion with `executor/contracts.py:ExecutionResult`.

---

### `ActionResult` — core/autonomy/daemon.py (autonomy loop result)

- **Location:** `core/autonomy/daemon.py:80`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Required |
| `confidence` | `float` | 0.0–1.0 |
| `actual_tokens` | `int` | Token usage |
| `actual_usd` | `float` | Cost estimate |
| `output` | `Any` | Arbitrary output |
| `error` | `str` | Error message |

- **Produced by:** `core/autonomy/daemon.py`, `core/autonomy/runners.py`
- **Consumed by:** `core/autonomy/__init__.py` (re-exported as `ActionResult` from this module), `core/autonomy/runners.py`
- **Status:** **Duplicate name, distinct purpose** — this `ActionResult` tracks token/cost metadata for the autonomy budget loop. It overlaps in name with `executor/runner.py:ActionResult` but has different fields (`confidence`, `actual_tokens`, `actual_usd`). Consumers of the two types are entirely separate subsystems.
- **Recommendation:** **Rename to `AutonomyActionResult`** or `BudgetedActionResult` to avoid ambiguity with the executor layer type.

---

### `ActionResult` — core/browser/browser_actions.py (browser action result)

- **Location:** `core/browser/browser_actions.py:16`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Required |
| `action` | `str` | Browser action name |
| `data` | `dict` | Action output data |
| `error` | `str` | Error message |
| `screenshot_path` | `str` | Path to screenshot if taken |
| `needs_approval` | `bool` | Whether human approval required |
| `approval_request` | `dict | None` | Approval request payload |

- **Produced by:** `core/browser/browser_agent.py` (navigate, click, fill, etc.)
- **Consumed by:** `core/browser/browser_agent.py`
- **Status:** **Distinct type, local to browser subsystem.** Has browser-specific fields (`screenshot_path`, `needs_approval`, `approval_request`) not present in other `ActionResult` types.
- **Recommendation:** **Rename to `BrowserActionResult`** to eliminate the three-way `ActionResult` name collision.

---

### `MissionResult` — core/memory/mission_result.py (memory recording)

- **Location:** `core/memory/mission_result.py:21`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `mission_id` | `str` | Required |
| `run_id` | `str` | Required |
| `task_type` | `str` | Required |
| `files_changed` | `list[str]` | Required |
| `tests_run` | `list[str]` | Required |
| `success` | `bool` | Required |
| `failure_reason` | `str` | Error description |
| `model_used` | `str` | LLM model name |
| `model_class` | `str` | Model category |
| `duration_ms` | `int` | Duration |
| `cost_estimate` | `float | None` | Cost in USD |
| `lessons_learned` | `str` | Text for memory storage |
| `created_skill` | `str | None` | Skill ID if reusable pattern found |
| `summary` | `str` | Human-readable summary |

- **Produced by:** `core/evals/bea_eval.py`, callers of `MissionResultRecorder.record()`
- **Consumed by:** `MissionResultRecorder` (writes to `OperationalMemoryStore`), `core/evals/bea_eval.py`, `core/memory/__init__.py` (re-exported), `tests/core/memory/test_mission_result.py`
- **Status:** **Distinct purpose** — this is a **memory artifact payload**, not a mission control type. It feeds the operational memory system (eval_result, model_result, bug_memory, skill, test_map entries).
- **Recommendation:** **Keep as-is.** Rename candidate: `MissionMemoryPayload` to clarify it is a memory write DTO, not a mission state object.

---

### `MissionResult` — core/mission_models.py (mission lifecycle model)

- **Location:** `core/mission_models.py:32`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `mission_id` | `str` | Required |
| `user_input` | `str` | Required |
| `intent` | `str` | Required |
| `status` | `str` | Required |
| `plan_summary` | `str` | Plan description |
| `plan_steps` | `list[dict]` | Execution plan |
| `plan_risk` | `str` | Risk level |
| `advisory_score` | `float` | Advisory evaluation score |
| `advisory_decision` | `str` | GO / IMPROVE / NO-GO |
| `advisory_issues` | `list[dict]` | Issues flagged by advisor |
| `advisory_risks` | `list[dict]` | Risks flagged |
| `advisory_text` | `str` | Advisor narrative |
| `action_ids` | `list[str]` | Generated action IDs |
| `risk_score` | `int` | 0-10 numeric score |
| `complexity` | `str` | low / medium / high |
| `execution_trace` | `list[dict]` | Per-agent execution trace |
| `decision_trace` | `dict` | Unified decision trace |

- **Produced by:** `core/mission_system.py`, `core/mission_persistence.py`
- **Consumed by:** `core/mission_persistence.py`, `core/mission_system.py`, tests
- **Status:** **Duplicate name, different purpose** — this is the full lifecycle state of a mission (planning through execution), not a memory DTO. Has more fields than `core/memory/mission_result.py:MissionResult` and serves a completely different role.
- **Recommendation:** **Rename to `MissionState`** or `MissionRecord` to eliminate the name collision with the memory DTO.

---

### `AgentResult` — core/contracts.py (Pydantic inter-agent result)

- **Location:** `core/contracts.py:114`
- **Type:** Pydantic `BaseModel`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `task_id` | `str` | Task reference |
| `agent` | `str` | Required — agent name |
| `success` | `bool` | Required |
| `content` | `str` | Main output (markdown/JSON string) |
| `error` | `str` | Error if failed |
| `duration_ms` | `int` | Duration |
| `retry_count` | `int` | How many retries were done |
| `metadata` | `dict` | Arbitrary metadata |
| `created_at` | `float` | Timestamp |
| `correlation_id` | `str` | Trace correlation |

- **Produced by:** Agents via `session.set_typed_output(agent_name, result)` pattern (documented in module docstring)
- **Consumed by:** No confirmed external consumers import `AgentResult` from `core.contracts`. `agents/debug_agent.py` imports only `ErrorReport`; `executor/task_queue.py` imports only `TaskContract, TaskState`; `agents/monitoring_agent.py` imports only `ComponentHealth, HealthReport, HealthStatus`. The only import of `AgentResult` from `core.contracts` found in the codebase is the self-referential usage inside `core/contracts.py` itself (module docstring example). **This type may be unused externally.**
- **Status:** **Legitimate Pydantic model for agent-to-agent communication.** Distinct from `core/autonomy/daemon.py:ActionResult` (different purpose, different framework). Note: name collision with `agents/parallel_executor.py:AgentResult` — see section below.
- **Recommendation:** **Keep, but verify actual usage.** If genuinely unused externally, consider deprecating or consolidating with `agents/parallel_executor.py:AgentResult`. This is the correct contract for typed output passing between agents via the session bus.

---

### `AgentResult` — agents/parallel_executor.py (parallel execution result)

- **Location:** `agents/parallel_executor.py:116`
- **Type:** Plain class with `__slots__` (not a dataclass, not Pydantic)
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `agent` | `str` | Agent name |
| `task` | `str` | Task description |
| `output` | `str` | Agent output (default: `""`) |
| `success` | `bool` | Whether the agent succeeded (default: `True`) |
| `error` | `str` | Error message (default: `""`) |
| `duration_ms` | `int` | Execution duration (default: `0`) |
| `agent_output` | `AgentOutput \| None` | Typed structured output (default: `None`) |
| `trace` | `AgentTrace \| None` | Execution trace (default: `None`) |

- **Produced by:** `agents/parallel_executor.py:ParallelExecutor._run_single_agent()` — created inline for every individual agent invocation in a parallel run
- **Consumed by:** `agents/parallel_executor.py:ParallelExecutor.run_parallel()` (aggregates results into `dict[str, AgentResult]`), `agents/agent_output.py` (converts to `AgentOutput` — documented in comment at line 170), internal parallel executor machinery
- **Status:** **Name collision with `core/contracts.py:AgentResult`** — two entirely different types with the same name, different frameworks (slots class vs Pydantic), different fields (`task`/`agent_output`/`trace` vs `task_id`/`content`/`correlation_id`), and different scopes (parallel executor internal vs session bus contract).
- **Recommendation:** **Rename to `ParallelAgentResult`** to eliminate the collision with `core/contracts.py:AgentResult`. The two types are used in completely separate contexts and should not share a name.

---

### `ExecutionResultSchema` — core/contracts.py (Pydantic schema for file/shell results)

- **Location:** `core/contracts.py:250`
- **Type:** Pydantic `BaseModel`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Required |
| `action_type` | `str` | Required |
| `target` | `str` | Required |
| `output` | `str` | Output string |
| `error` | `str` | Error string |
| `backup_path` | `str` | Backup location |
| `duration_ms` | `int` | Duration |
| `risk` | `str` | LOW/MEDIUM/HIGH |
| `session_id` | `str` | Session reference |
| `agent` | `str` | Producing agent name |
| `correlation_id` | `str` | Trace ID |
| `timestamp` | `float` | Creation time |

- **Produced by:** Unclear — the module has no direct producer wiring; likely intended as a validation schema wrapper over `executor/runner.py:ActionResult`
- **Consumed by:** `agents/debug_agent.py` (imports from `core.contracts`), indirect usage via session contracts
- **Status:** **Partial duplicate of `executor/runner.py:ActionResult`** — same fields (success, action_type, target, output, error, backup_path, duration_ms) plus extra tracking fields (risk, session_id, agent, correlation_id). This is a Pydantic-validated version of the same shape, suggesting it was added to bring type safety to existing dict results without refactoring the dataclass.
- **Recommendation:** **Consolidate or formalize the relationship.** Either: (a) make `ActionResult` Pydantic and drop `ExecutionResultSchema`, or (b) document this as the canonical validated wire format and add a `.from_action_result()` factory.

---

### `KernelAgentResult` — kernel/contracts/agent.py

- **Location:** `kernel/contracts/agent.py:82`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `agent_id` | `str` | Agent identifier |
| `task_id` | `str` | Auto-generated if empty |
| `mission_id` | `str` | Associated mission |
| `status` | `KernelAgentStatus` | SUCCESS / FAILED / PARTIAL / SKIPPED |
| `output` | `str` | Human-readable result |
| `confidence` | `float` | 0.0–1.0 (clamped in `__post_init__`) |
| `reasoning` | `str` | Brief reasoning trace |
| `metadata` | `dict` | Extra data |
| `error` | `Optional[str]` | Error if failed |
| `started_at` | `float` | Start timestamp |
| `finished_at` | `float` | Finish timestamp |

- **Computed:** `duration_ms` property
- **Produced by:** `agents/kernel_bridge.py` (primary producer — wraps cognitive outputs into this type)
- **Consumed by:** `agents/kernel_bridge.py`, `api/routes/kernel.py`, `core/orchestration/execution_mixin.py`, `kernel/contracts/__init__.py` (re-exported)
- **Status:** **Canonical kernel-layer agent output.** Complements `AgentResult` (Pydantic, session-bus level) at the kernel level. Distinct purpose.
- **Recommendation:** **Keep.** No consolidation needed.

---

### `CapabilityResult` — executor/capability_contracts.py

- **Location:** `executor/capability_contracts.py:51`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `ok` | `bool` | Success flag |
| `capability_type` | `CapabilityType` | NATIVE_TOOL / PLUGIN / MCP_TOOL |
| `capability_id` | `str` | Tool/plugin/MCP ID |
| `result` | `Any` | Raw result |
| `error` | `Optional[str]` | Error message |
| `execution_ms` | `int` | Duration |
| `used_skill_ids` | `list[str]` | Skills used |
| `metadata` | `dict` | Extra data |

- **Class methods:** `.success(...)` and `.failure(...)` factory constructors
- **Produced by:** `executor/capability_dispatch.py`
- **Consumed by:** `executor/capability_dispatch.py`, multiple test files
- **Status:** **Distinct, well-scoped type** — represents the unified result of any capability invocation (native tool, plugin, MCP). Different abstraction level from `ExecutionResult`.
- **Recommendation:** **Keep.** This is the right contract for the capability routing layer.

---

### `ConnectorResult` — core/connectors/contracts.py

- **Location:** `core/connectors/contracts.py:32`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Default: False |
| `data` | `Any` | Raw connector output |
| `error` | `str` | Error message |
| `latency_ms` | `float` | Execution time |
| `connector` | `str` | Connector name |

- **Note:** `to_dict()` exposes both `ok` and `success` keys for compat.
- **Produced by:** `core/connectors/_base.py`, `core/connectors/business.py`, `core/connectors/hexstrike.py`, `core/connectors/runtime.py`
- **Consumed by:** All connector implementations, `tests/test_connectors_contracts_extraction.py`
- **Status:** **Legitimate, well-scoped type** for the connector abstraction layer.
- **Recommendation:** **Keep.**

---

### `ExecutionResult` — core/self_improvement/safe_executor.py (SI-specific)

- **Location:** `core/self_improvement/safe_executor.py:29`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Default: False |
| `output` | `str` | Execution output |
| `error` | `str` | Error message |
| `applied_change` | `str` | Description of change applied |
| `changed_file` | `str` | Path to modified file |
| `rollback_triggered` | `bool` | Whether rollback occurred |
| `backup_text` | `str | None` | Original content before change |

- **Produced by:** `core/self_improvement/safe_executor.py:SafeSelfImprovementExecutor.execute()`
- **Consumed by:** `core/self_improvement/engine.py`, `api/routes/self_improvement.py`, `core/self_improvement/research_loop.py`, `scripts/run_telegram_bea.py`
- **Status:** **Local type within the self-improvement subsystem.** The name `ExecutionResult` is misleading — this is specifically a *self-improvement patch application result*, not a general execution result. The file actually defines **two** types: (a) `ExecutionResult` (line 29) — the legacy type with fields `success`, `output`, `error`, `applied_change`, `changed_file`, `rollback_triggered`, `backup_text`; and (b) `PatchResult` (line 42) — a newer, richer type with fields `success`, `applied_change`, `rollback_triggered`, `error`, `confidence` (0.0–1.0), `risk_level` (low/medium/high), `diff_summary`, `revert_path`. The `SafeSelfImprovementExecutor.execute()` method returns the legacy `ExecutionResult`. `tests/test_hardening_v3.py` imports the newer type for backward compatibility (`from core.self_improvement.safe_executor import PatchResult as ExecutionResult`) — `PatchResult` is the intended forward-looking name, and the test aliases it to `ExecutionResult` for legacy test compat, not the reverse. A comment at line 311 of the file confirms: `# Legacy alias removed — use PatchResult directly or executor.contracts.ExecutionResult`.
- **Recommendation:** **Migrate `SafeSelfImprovementExecutor.execute()` to return `PatchResult`** and rename `PatchResult` to `PatchApplicationResult`. The legacy `ExecutionResult` class in this file can then be removed. Update `core/self_improvement/engine.py`, `api/routes/self_improvement.py`, `core/self_improvement/research_loop.py`, `scripts/run_telegram_bea.py` accordingly. The test import in `test_hardening_v3.py` can then be simplified.

---

### `SandboxResult` — core/self_improvement_loop.py (SI sandbox)

- **Location:** `core/self_improvement_loop.py:517`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `passed` | `bool` | Overall pass |
| `tests_passed` | `int` | Count of passing tests |
| `tests_failed` | `int` | Count of failing tests |
| `tests_total` | `int` | Total tests run |
| `lint_ok` | `bool` | Lint result |
| `errors` | `list[str]` | Error messages |
| `duration_ms` | `float` | Duration |

- **Produced by:** `SandboxRunner.run()` in the same file (syntax-only validation fallback)
- **Consumed by:** `PatchValidator` in the same file
- **Status:** **Local to the self-improvement loop module.** Also has a parallel class in `core/self_improvement/sandbox_executor.py:SandboxResult` (separate definition, similar shape).
- **Recommendation:** **Consolidate the two `SandboxResult` types.** `core/self_improvement/sandbox_executor.py` has the more complete implementation.

---

### `ValidationResult` — core/self_improvement_loop.py (SI patch validation)

- **Location:** `core/self_improvement_loop.py:587`
- **Type:** `@dataclass`
- **Fields:**

| Field | Type | Description |
|---|---|---|
| `decision` | `str` | REJECTED / STORED_FOR_REVIEW / APPLIED_STAGING / APPLIED_PRODUCTION |
| `reason` | `str` | Explanation |
| `requires_approval` | `bool` | Whether human approval needed |

- **Produced by:** `PatchValidator` in the same file
- **Consumed by:** `ImprovementOrchestrator` in the same file
- **Status:** **Local to self-improvement module.** Grep confirms exactly 4 `class ValidationResult` definitions in the codebase: `core/self_improvement_loop.py:587` (this one), `core/learning/knowledge_validator.py:35`, `core/planning/output_enforcer.py:35`, and `executor/output_validator.py:32`. Note: `core/planning/self_review.py` defines `ReviewResult` (not `ValidationResult`) — it is **not** part of this collision.
- **Recommendation:** **Scope with a prefix** — rename to `PatchValidationResult` for the SI module case (`core/self_improvement_loop.py`); consider `KnowledgeValidationResult` for `core/learning/knowledge_validator.py`, `OutputValidationResult` for `core/planning/output_enforcer.py`, and `ExecutorValidationResult` for `executor/output_validator.py`.

---

## `contracts.py` Files

| File | Purpose | Key Types |
|---|---|---|
| `executor/contracts.py` | **Declared canonical** executor result. "No ambiguity. No fake success." | `ExecutionResult`, `ExecutionStatus`, `ErrorClass`, `classify_error()`, `is_retryable()` |
| `executor/capability_contracts.py` | Capability routing contract (native/plugin/MCP invocations) | `CapabilityRequest`, `CapabilityResult`, `CapabilityType` |
| `kernel/contracts/types.py` | Kernel domain types — full system vocabulary (Mission, Plan, Action, etc.) | `ExecutionResult`, `PolicyDecision`, `MemoryRecord`, `SystemEvent`, `Goal`, `Mission`, `Plan`, `PlanStep`, `Action` |
| `kernel/execution/contracts.py` | Kernel execution shell types — what `BeaKernel.execute()` returns | `ExecutionRequest`, `ExecutionResult`, `ExecutionHandle`, `ExecutionStatus` |
| `kernel/contracts/agent.py` | Kernel-native agent I/O types | `KernelAgentContract`, `KernelAgentResult`, `KernelAgentTask`, `KernelAgentRegistry` |
| `kernel/contracts/mission_runner.py` | Mission runner protocol | `MissionRunner`, `MissionCallback` |
| `agents/contracts.py` | Agent-layer I/O schema (Phase 3) | `AgentContract`, `ReviewResult`, `AgentStatus`, `DELEGATION_MAP` |
| `core/contracts.py` | Pydantic inter-agent contracts | `AgentResult`, `ExecutionResultSchema`, `TaskContract`, `RetryConfig`, `AgentMessage`, `MissionTransition` |
| `core/connectors/contracts.py` | Connector abstraction types | `ConnectorSpec`, `ConnectorResult` |

---

## Duplication Map

| Type Name | Instances | Overlap | Primary Conflict |
|---|---|---|---|
| `ExecutionResult` | 3 independent definitions | All claim to represent "the result of execution" | `executor/contracts.py` vs `kernel/contracts/types.py` vs `kernel/execution/contracts.py` |
| `ActionResult` | 3 independent definitions | All have `success: bool` + `error: str` | `executor/runner.py` vs `core/autonomy/daemon.py` vs `core/browser/browser_actions.py` |
| `AgentResult` | 2 independent definitions | Both have `agent`, `success`, `error`, `duration_ms` | `core/contracts.py` (Pydantic, session-bus) vs `agents/parallel_executor.py` (slots class, parallel executor internal) |
| `MissionResult` | 2 independent definitions | Both have `mission_id`, `success` | `core/memory/mission_result.py` (memory DTO) vs `core/mission_models.py` (lifecycle state) |
| `ValidationResult` | 4 definitions | All have pass/fail semantics | `core/self_improvement_loop.py`, `core/learning/knowledge_validator.py`, `core/planning/output_enforcer.py`, `executor/output_validator.py` (note: `core/planning/self_review.py` defines `ReviewResult`, not `ValidationResult`) |
| `SandboxResult` | 2 definitions | Both track test pass/fail counts | `core/self_improvement_loop.py` vs `core/self_improvement/sandbox_executor.py` |

---

## Recommended Canonical Paths

| Domain | Canonical Module | Type |
|---|---|---|
| Tool/task execution (executor layer) | `executor.contracts.ExecutionResult` | `@dataclass` — keep as-is |
| Kernel step result (plan step output) | `kernel.contracts.types.ExecutionResult` → rename `StepExecutionResult` | `@dataclass` |
| Kernel API shell (BeaKernel.execute() return) | `kernel.execution.contracts.ExecutionResult` → rename `KernelExecutionResult` | `@dataclass` |
| File/shell action results | `executor.runner.ActionResult` | `@dataclass` — keep, drop local `ExecutionResult` alias |
| Autonomy loop results | `core.autonomy.daemon.ActionResult` → rename `AutonomyActionResult` | `@dataclass` |
| Browser action results | `core.browser.browser_actions.ActionResult` → rename `BrowserActionResult` | `@dataclass` |
| Mission lifecycle state | `core.mission_models.MissionResult` → rename `MissionState` | `@dataclass` |
| Mission memory write payload | `core.memory.mission_result.MissionResult` → rename `MissionMemoryPayload` | `@dataclass` |
| Inter-agent typed output | `core.contracts.AgentResult` | Pydantic — keep as-is |
| Kernel-native agent output | `kernel.contracts.agent.KernelAgentResult` | `@dataclass` — keep as-is |
| Capability invocation result | `executor.capability_contracts.CapabilityResult` | `@dataclass` — keep as-is |
| Connector result | `core.connectors.contracts.ConnectorResult` | `@dataclass` — keep as-is |
| SI patch application | `core.self_improvement.safe_executor.ExecutionResult` → rename `PatchApplicationResult` | `@dataclass` |
| SI sandbox result | consolidate `core.self_improvement.sandbox_executor.SandboxResult` as canonical | `@dataclass` |
| Agent structured output (agents layer) | `agents.contracts.AgentContract` | `@dataclass` — keep as-is |

---

## Migration Notes

The following migrations should be done in dependency order (dependents after definitions):

1. **`executor/runner.py` alias removal** — Delete line 185 (`ExecutionResult = ActionResult`). Update any callers that imported `ExecutionResult` from `executor.runner` to import `ActionResult` instead. Only one known caller pattern via `api/routes/system.py:ActionExecutor`.

2. **`kernel/contracts/types.py:ExecutionResult` → `StepExecutionResult`** — Update `kernel/contracts/__init__.py`, `kernel/adapters/result_adapter.py`, and all test imports. The adapter is the main producer; `kernel/__init__.py` is the main re-export.

3. **`kernel/execution/contracts.py:ExecutionResult` → `KernelExecutionResult`** — Update `kernel/runtime/kernel.py`, `kernel/execution/__init__.py`, `interfaces/kernel_adapter.py`, `tests/unit/test_imports.py`.

4. **`core/autonomy/daemon.py:ActionResult` → `AutonomyActionResult`** — Update `core/autonomy/runners.py`, `core/autonomy/__init__.py` exports. Isolated within the autonomy subsystem.

5. **`core/browser/browser_actions.py:ActionResult` → `BrowserActionResult`** — Update `core/browser/browser_agent.py`. Isolated within the browser subsystem.

6. **`core/mission_models.py:MissionResult` → `MissionState`** — Update `core/mission_system.py`, `core/mission_persistence.py`, and test files.

7. **`core/self_improvement/safe_executor.py:ExecutionResult` → `PatchApplicationResult`** — Update `core/self_improvement/engine.py`, `api/routes/self_improvement.py`, `core/self_improvement/research_loop.py`, `scripts/run_telegram_bea.py`. Note: `tests/test_hardening_v3.py` already imports it as `PatchResult` via alias — that test import can be simplified.

8. **`SandboxResult` consolidation** — Point `core/self_improvement_loop.py` to import `SandboxResult` from `core/self_improvement/sandbox_executor.py` and remove the duplicate definition.

9. **`ExecutionResultSchema` in `core/contracts.py`** — Formalize relationship with `executor/runner.py:ActionResult`. Either add a `from_action_result()` classmethod or replace with direct `ActionResult` usage and annotate the Pydantic schema as the wire format.

> **Priority order for immediate impact:** Items 1, 7, and 2 (in that order) eliminate the most confusing name collisions with the least downstream risk.
