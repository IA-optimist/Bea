# Beamax — Contracts map

The repo has **four** `contracts.py` modules. The 2026-05-18 audit (§5.1 P2)
flagged this as fragmentation and recommended centralising. After Sprint 8
investigation we kept them separate because they live at different layers
of the architecture and merging would break the K1 rule (the kernel must
not import from `core/`, `agents/`, `api/`, or `tools/`). This doc
clarifies who owns what and how to navigate the naming collisions.

## Layered ownership

```
┌──────────────────────────────────────────────────────────────┐
│  agents/contracts.py    AgentContract — agent I/O facade     │  upward
│                         AgentStatus,  ReviewResult           │
├──────────────────────────────────────────────────────────────┤
│  core/contracts.py      TaskContract, AgentResult,           │
│                         AgentMessage, ErrorReport,           │
│                         HealthReport, RetryConfig            │
├──────────────────────────────────────────────────────────────┤
│  executor/contracts.py  ExecutionResult — tool/action result │
│                         (success | failed | timeout | …)     │
├──────────────────────────────────────────────────────────────┤
│  kernel/execution/      ExecutionRequest, ExecutionResult,   │  kernel-pure
│  contracts.py           ExecutionHandle, ExecutionStatus     │  (K1 rule)
│                         (CREATED → RUNNING → DONE …)         │
└──────────────────────────────────────────────────────────────┘
```

Rule of thumb when deciding where a new type belongs:

- **It must compile in `kernel/` (no upward imports)?** → `kernel/execution/contracts.py`
- **It's a tool/action result envelope?** → `executor/contracts.py`
- **It's an inter-agent message or task spec?** → `core/contracts.py`
- **It's the structured output of an agent?** → `agents/contracts.py`

## Name collisions (read this before importing)

### `ExecutionStatus` × 2

Two enums with the same name, **different semantics**:

| Module                          | Members                                                                 | Meaning                          |
|---------------------------------|-------------------------------------------------------------------------|----------------------------------|
| `executor.contracts.ExecutionStatus` | `SUCCESS`, `FAILED`, `TIMEOUT`, `SKIPPED`, `PENDING_APPROVAL`           | outcome of a single tool call    |
| `kernel.execution.contracts.ExecutionStatus` | `CREATED`, `RUNNING`, `AWAITING_APPROVAL`, `REVIEW`, `DONE`, `FAILED`, `CANCELLED` | mission-lifecycle state machine  |

When importing, **always disambiguate**:

```python
# Inside the executor layer:
from executor.contracts import ExecutionStatus as ToolOutcome
# Inside the kernel / state machine code:
from kernel.execution.contracts import ExecutionStatus as MissionState
```

Future rename target (out of scope for the audit hardening, file an issue
first): `executor.contracts.ExecutionStatus` → `ResultOutcome` (or
`ToolOutcome`). It would eliminate the clash entirely.

### `ExecutionResult` × 2

Also same name, different shapes:

| Module                          | Owner of  | Fields                                                              |
|---------------------------------|-----------|---------------------------------------------------------------------|
| `executor.contracts.ExecutionResult` | tool call | `execution_id`, `task_id`, `status`, `success`, `error_class`, `error_message`, `retryable`, `started_at`, … |
| `kernel.execution.contracts.ExecutionResult` | mission   | `mission_id`, `status`, `result`, `error`, `metadata`, `goal`, `mode`, `created_at` (plus `get_output(agent)` for `MissionContext` compat) |

Same disambiguation strategy applies — alias on import.

## Why not centralise?

The audit recommendation was to fold the 4 files into one. We rejected
that because:

1. `kernel/execution/contracts.py` must not import from `core/`,
   `executor/`, or `agents/` (K1 rule, audited and enforced by
   `kernel_ci.yml`). A centralised `contracts.py` upstream of all four
   would either break this rule or split into the same 4 layers anyway.
2. Pydantic v2 lives in `core/contracts.py` while `kernel/` uses plain
   `@dataclass`. Mixing them in one file would force one side to bend.
3. The naming collisions are surface-level. The actual abstractions are
   distinct (tool outcome vs mission state). Renaming is cleaner than
   merging.

## Roadmap (not blocking)

- [ ] Rename `executor.contracts.ExecutionStatus` → `ResultOutcome` so the
      string `ExecutionStatus` unambiguously means kernel state machine.
- [ ] Same rename for `executor.contracts.ExecutionResult` →
      `ToolExecutionResult` (or extract to `executor/tool_result.py`).
- [ ] Add a `core/contracts/__init__.py` re-export aggregator if a single
      "import everything I might need" entry-point becomes useful
      (mirrors what `core/registries/` does for the four registries —
      audit S3.C).

Tracked in [issue #16](https://github.com/IA-optimist/Bea/issues/16) under
"Centralise contracts.py".
