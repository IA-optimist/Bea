# Jarvismax — Architecture & Top-Level Layout

This document is intentionally short. It exists to remove a single source of
confusion flagged by the audit (Sprint 3 §3.1): the parallel `business/` and
`core/business/` namespaces. If you are adding new code, read this first.

## Layered design

The code is organised in four layers, importing from bottom to top:

```
   ┌───────────────────────────────────────────┐
   │  main.py / scripts / entrypoints          │
   ├───────────────────────────────────────────┤
   │  api/          ← FastAPI surface          │
   ├───────────────────────────────────────────┤
   │  core/         ← orchestration, mission   │
   │                  engine, registries       │
   ├───────────────────────────────────────────┤
   │  kernel/       ← pure evaluation/policy   │
   │                  (no imports from core)   │
   └───────────────────────────────────────────┘
```

Kernel rule (load-bearing): `kernel/` has **zero** imports from `core/`,
`api/`, `agents/`, or `tools/`. Registration of optional enrichments is
done via inverted slots at boot (`kernel.evaluation.scorer.register_*`).

## `business/` vs `core/business/`

Both exist and both are kept on purpose. The audit asked us to write this
section so newcomers don't conflate them.

### `business/` — Autonomous SaaS engine
*Mission: generate revenue from automated micro-products.*

| Sub-package          | Role                                           |
|----------------------|------------------------------------------------|
| `business/automation/`  | Product discovery, builder loop, deployment |
| `business/finance/`     | Stripe / payment integration                |
| `business/fiscal/`      | Tax + accounting                            |
| `business/legal/`       | Compliance checks (RGPD, ToS, etc.)         |
| `business/meta_builder/`| Template-driven SaaS scaffolding            |
| `business/offer/`       | Pricing & offers                            |
| `business/playbooks/`   | Repeatable revenue playbooks                |
| `business/business_engine.py` | Orchestrator for the above            |

Think of `business/` as a vertical slice: it owns its own engine
(`business_engine.py`) and uses `core/` purely as a library.

### `core/business/` — Mission engine for builder missions
*Mission: execute the "build me this app" mission contract.*

| File                         | Role                                       |
|------------------------------|--------------------------------------------|
| `mission_engine.py`          | Mission lifecycle controller               |
| `mission_runner.py`          | Step-by-step runner                        |
| `mission_schema.py`          | Pydantic models for a mission              |
| `mission_templates.py`       | Stock templates                            |
| `mission_audit.py`           | Audit trail of a mission                   |
| `mission_memory.py`          | Persistent memory per mission              |
| `feasibility_analyzer.py`    | Pre-flight check on a mission              |
| `mvp_generator.py`           | Scaffold the initial MVP                   |
| `deploy_manager.py`          | Wire to deployment targets                 |
| `github_automation.py`       | Repo creation, push, PR                    |
| `portfolio_manager.py`       | Roll-up across active missions             |

Think of `core/business/` as the engine that `business/` (or any other
caller) drives to actually *build* something. It is upstream of `business/`,
not a duplicate.

### Rule of thumb

- "I want to ship a new SaaS / playbook / revenue stream." → `business/`.
- "I want to extend how a builder mission runs." → `core/business/`.
- "I'm tempted to put it in *both*." → pick one and import across.

## Other notable top-level packages

- `kernel/` — pure evaluation, policy, no upward imports. The single source
  of truth for mission outcomes (`KernelEvaluator`).
- `core/` — orchestration, agents glue, registries. Imports `kernel/`.
- `core/orchestration/` — the state machine and reasoning glue.
- `core/registries/` — canonical re-export of the 4 registries (audit S3.C).
  *Always* import from here; do not reach into the underlying modules.
- `agents/` — agent definitions and the multi-agent crew.
- `tools/` — live tool executors (paired with `core/tool_registry` definitions).
- `executor/` — sandbox (`desktop_env/sandbox.py`) and runner whitelist.
- `interfaces/` — adapters to external surfaces (Telegram, mobile, web).
- `monitoring/` — Prometheus/Grafana stack (compose + dashboards).
- `mcp/` — MCP server bridges (the vendored `hexstrike-ai/` copy was
  removed by audit S3.A; capabilities still registered upstream-only).
- `agent_marketplace/` — **removed** by audit S3.A (was 21 KB, 0 imports).

## Deprecated zones (do not import from these)

- `core/_legacy/` — see [core/_legacy/README.md](core/_legacy/README.md) for
  the migration plan. Five shims in `core/` still re-export from here,
  blocking outright deletion.

## Next architectural chantiers (audit Sprint 3-4, deferred)

These each need their own PR:

- **Split `core/meta_orchestrator.py`** (2965 lines). Extract the state
  machine into `core/orchestration/state_machine.py`. Audit §3.1 P0.
- **Split `api/main.py`** (1070 lines, 61 routers). Extract v1 legacy
  aliases, static mount, and decision-memory wiring.
- **Split `agents/crew.py`** (1390 lines, 10+ classes) per-agent files.
- **Replace ~110 `print()` calls** in `core/orchestration/` with `structlog`.
- ~~**Centralise the `contracts.py` schemas** (currently fragmented across
  `agents/`, `core/`, `executor/`, `kernel/execution/`).~~ — Sprint 9.2:
  the 4 files are layered, not duplicated. Centralising would break the
  K1 rule on `kernel/`. Documented the boundaries + name collisions in
  [`docs/CONTRACTS.md`](docs/CONTRACTS.md) instead. Two rename candidates
  noted for a future PR (`executor.ExecutionStatus` → `ResultOutcome`,
  `executor.ExecutionResult` → `ToolExecutionResult`).
- **Multi-stage Dockerfile** — done in audit S4.A.
