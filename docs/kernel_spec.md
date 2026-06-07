# BeaMax Kernel Specification

> Canonical specification for the BeaMax kernel layer.
> Source of truth: `kernel/contracts/types.py` and `kernel/runtime/`.

---

## Domain Contracts

The kernel defines 13 canonical contract types in `kernel/contracts/types.py`:

| Type | Purpose |
|------|---------|
| `Goal` | Mission goal with description, constraints, metadata |
| `Mission` | Full mission envelope: id, goal, status, plan_id, run_id, timestamps |
| `Plan` | Execution plan with status and ordered steps |
| `PlanStep` | Single step with type, action, agent_hint, dependencies |
| `Action` | Concrete executable action |
| `Decision` | Decision type (approval, routing, policy, etc.) |
| `Observation` | Runtime observation from execution |
| `ExecutionResult` | Structured result (success, output, error, metadata) |
| `PolicyDecision` | Policy verdict (allowed, escalated, reason) |
| `MemoryRecord` | Memory entry (content, type, ttl, metadata) |
| `SystemEvent` | Kernel event emission |

All contracts:
- Are immutable frozen dataclasses
- Expose `validate()` method
- Serialize via `to_dict()` / `from_dict()`
- Pass smoke tests at kernel boot

Enums: `MissionStatus`, `PlanStatus`, `RiskLevel`, `DecisionType`, `StepType`.

---

## Capability Model

The kernel registers **19 canonical capabilities** in `kernel/capabilities/registry.py`:

### Planning
- `plan_generation` — Produce execution plans from goals
- `plan_validation` — Validate plan correctness and feasibility
- `decision_evaluation` — Evaluate decisions against policy

### Execution
- `skill_execution` — Invoke registered skills
- `tool_invocation` — Invoke tools (native / plugin / MCP)
- `code_generation` — Generate code artifacts
- `quality_review` — Review output quality

### Memory
- `memory_write` — Write to typed memory
- `memory_recall` — Query memory (semantic / episodic / execution)

### Policy
- `risk_evaluation` — Evaluate action risk level
- `policy_check` — Check action against policy rules

### Domain intelligence
- `market_intelligence` — Scan markets, competitors, opportunities
- `product_design` — Design product specs
- `financial_reasoning` — Compute financial metrics
- `compliance_reasoning` — Legal/regulatory compliance
- `risk_assessment` — Risk evaluation for ventures
- `venture_planning` — Business venture planning
- `strategy_reasoning` — Strategic decision support
- `artifact_generation` — Generate documents/artifacts

Capabilities are registered at boot via `register(capability)` and discoverable via `list_by_category()`.

---

## Event Model

The kernel emits structured `SystemEvent` records via the event emitter at `kernel/runtime/kernel.py`.

### Event categories

- `kernel.booted` — Emitted after successful kernel boot
- `mission.created`, `mission.planned`, `mission.running`, `mission.done`, `mission.failed`
- `plan.generated`, `plan.validated`, `plan.executed`
- `policy.checked`, `policy.escalated`, `policy.denied`
- `memory.written`, `memory.retrieved`
- `capability.invoked`, `capability.completed`
- `learning.lesson_stored`, `learning.lesson_retrieved`

### Event flow

```
Core module → kernel.events.emit(event) → Subscribers (observability, audit, metrics)
```

Events are fail-open: emission never raises.

---

## Memory Model

The kernel defines **5 memory types** in `kernel/memory/interfaces.py`:

| Type | Purpose | Backend | TTL |
|------|---------|---------|-----|
| `working` | Short-lived context (current mission) | In-memory dict | 200-item limit, TTL eviction |
| `episodic` | Event log (what happened) | MemoryFacade (Qdrant) | Persistent |
| `execution` | Plan history and execution traces | MemoryFacade (Qdrant) | Persistent |
| `procedural` | Learned skills and how-tos | MemoryFacade (Qdrant) | Persistent |
| `semantic` | Facts and knowledge | MemoryFacade (Qdrant) | Persistent |

### Registration slots

The memory interface uses registration slots to avoid circular dependencies with `core/`:

```python
kernel.memory.register_facade_store(core.memory_facade.MemoryFacade.store)
kernel.memory.register_facade_search(core.memory_facade.MemoryFacade.search)
kernel.memory.register_lesson_store(core.orchestration.learning_loop.store_lesson)
kernel.memory.register_lesson_retrieve(core.learning_loop.find_relevant_lessons)
```

Registrations happen at startup in `main.py`.

### Memory operations

- `write_working(key, value, ttl_s)` — Store in working memory with TTL
- `read_working(key)` — Fetch from working memory (None if expired)
- `store(record)` — Store MemoryRecord (delegates to facade)
- `search(query, content_type, top_k)` — Semantic search (delegates to facade)
- `retrieve_lessons(goal, task_type, max_results)` — Lesson retrieval for planning

All memory operations are fail-open: errors log warnings but don't raise.

---

## Policy Model

Policy is registered from `core/` at boot via:

```python
kernel.adapters.policy_adapter.register_core_policy_fn(core.policy_engine.PolicyEngine.check_action)
```

### Policy check flow

```
action → kernel.policy.check_action(action_type, risk_level, context)
        → registered core.policy_engine.PolicyEngine.check_action()
        → returns PolicyDecision(allowed, escalated, reason, metadata)
```

### Policy decision fields

| Field | Type | Purpose |
|-------|------|---------|
| `allowed` | bool | Whether the action may proceed |
| `escalated` | bool | Whether approval is required |
| `reason` | str | Human-readable explanation |
| `risk_level` | str | Assessed risk (low/medium/high/critical) |
| `entry_id` | str | Audit trail reference |

### Enforcement

Policy checks are called from `core/meta_orchestrator.py:run_mission()` before execution. When `escalated=True` or `allowed=False`, the mission is routed to the approval queue (via `needs_approval=True` flag).

Policy engine is **fail-open**: if unavailable, actions proceed with logged warning. Production deployments should monitor `policy_unavailable` warnings.

---

## Boot Sequence

Kernel boot in `kernel/runtime/boot.py:boot_kernel()`:

1. Validate contracts via smoke tests (instantiate Goal/Mission/Plan/etc.)
2. Load capability registry (19 capabilities)
3. Initialize policy engine (with registration slots)
4. Initialize memory interface (5 types, registration slots)
5. Initialize event emitter
6. Initialize performance store (load from `data/kernel_performance.json`)
7. Emit `kernel.booted` event
8. Return `KernelRuntime` singleton

The `KernelRuntime` handle exposes: `capabilities`, `memory`, `events`, `policy`, `risk`, `approval`, `version`, `uptime_seconds`.

---

## Execution Path

```
api/routes/missions.py → MetaOrchestrator.run_mission()
                      → kernel.submit(goal, mode, session_id)
                      → kernel._orchestrator_fn(goal, ...)   # registered at boot
                      → BeaOrchestrator.run()             # delegate
                      → agents.crew (LLM calls via llm_factory)
                      → executor.runner.ActionExecutor       # side effects
                      → kernel.learn(score, lesson)          # feedback
```

Every step uses registration slots — kernel never imports `core/` directly.

---

## Registration Slots

All core → kernel bridges use registration functions (called at boot from `main.py`):

| Slot | Registers | From |
|------|-----------|------|
| Policy | `check_action` | `core.policy_engine.PolicyEngine` |
| Planner | `build_plan` | `core.planner` |
| Orchestrator | `run_mission` | `core.meta_orchestrator.MetaOrchestrator` |
| Classifier | `classify` | `core.orchestration.mission_classifier` |
| Reflection | `reflect` | `core.orchestration.reflection` |
| Critique | `critique_output` | `core.orchestration.reasoning_engine` |
| Lesson store | `store_lesson` | `core.orchestration.learning_loop` |
| Lesson retrieval | `find_relevant_lessons` | `core.learning_loop` |
| Memory facade store | `store` | `core.memory_facade.MemoryFacade` |
| Memory facade search | `search` (K1 wrapper) | `core.memory_facade.MemoryFacade` |
| Capability router | `route_mission` | `core.capability_routing.router` |
| Evaluator | `evaluate_result` | `core.evaluation_engine.EvaluationEngine` |
| Execution persist | `persist_execution_record` | `core.execution_memory` |

This inversion-of-control pattern is the core of the kernel architecture: **kernel defines contracts, core provides implementations**.

---

## Version

Current kernel version: `1.0.0`

See `kernel/runtime/kernel.py:VERSION` for runtime version.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system architecture.
