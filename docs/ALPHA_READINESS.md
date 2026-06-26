# Alpha Readiness

This page is retained as historical context for the transition into Developer
Preview / Private Beta 0.1. Current status is controlled by
[STATUS.md](STATUS.md).

PUBLIC_BETA_READY: false
- `smoke_e2e_cycle`: local fixture gate, no LLM required.
- `bea_eval --isolated`: reproducible CI gate. 25/25 pass. Two consecutive runs
  produce the same score (no store pollution). Previously flaky when run without
  `--isolated` against a warm global store. **Now fixed.**
- Provider runtime: outside this PR; this change does not touch providers.
- Code mission artifact gate: added for `needs_actions=True` missions.
- Code execution loop: helper added to strip markdown from Python blocks and
  validate syntax before accepting a materialized artifact.
- Completion truth gate: `validate_coding_report()` wrapper available with
  `.valid` / `.reason` interface alongside existing `.ok` / `.message`.
- Dogfood runtime evidence: `scripts/dogfood_runtime_evidence.py` now ships a
  10-mission pack with `runtime_enforced=false` and per-mission reports.
- `bea_eval --json` is green after ingesting a safe runtime report.

## Current Alpha-To-Private-Beta Position

| Area | Status |
|---|---|
| Core mission runtime | Advanced, covered by quick validation and focused checks |
| Auth principal binding | Advanced, `check_policy_principal_binding.py` passes |
| Mission ID propagation | Advanced, `check_tool_executor_mission_id.py` passes |
| Flutter active `/api/v1` calls | 0 active calls by `check_client_v1_usage.py` |
| Android APK | Partially validated; mission UI and offline/network-failure are HUMAN_REQUIRED |
| Qdrant live memory | Cleanup required; privacy scan found 1 private item |
| Public beta | NO-GO |

## HUMAN_REQUIRED

- HUMAN_REQUIRED: rotate historical/shared secrets if not already proved.
- HUMAN_REQUIRED: clean Qdrant live memory.
- HUMAN_REQUIRED: complete Android mission UI and offline/network-failure tests.
- HUMAN_REQUIRED: use `RedisSessionStore` for multi-process or multi-worker use.

## Dogfood Runtime Evidence

The controlled runtime dogfood pack now proves a real provider/model trail in
10 missions without modifying the router automatically.

Observed result from the current workspace:

- `mode=real`
- `total=10`
- `passed=8`
- `failed=2`
- `skipped=0`
- `matched_advice_count=7`
- `runtime_enforced=false`

Provider breakdown:

- `openrouter`: 7 total, 7 passed
- `ollama`: 3 total, 1 passed, 2 failed

Role breakdown:

- `shadow-advisor`: 4 total, 3 passed, 1 failed
- `forge-builder`: 3 total, 2 passed, 1 failed
- `scout-research`: 3 total, 3 passed

One safe report was ingested successfully:

`workspace/dogfood_runtime_real_reports/forge-builder-sha256.json`

That ingestion produced 4 memories and kept `bea_eval` green on the next run.

## Forge-Builder Readiness

`forge-builder` is only alpha-ready for code when the extraction and syntax
gate are active. It can produce useful implementation text, and it can trigger
a file action, but the SHA256 mission proved that a materialized file can still
be invalid if Markdown leaks into the artifact.

The current PR raises the bar:

- `needs_actions=True` requires a verifiable artifact.
- Declared files must exist.
- Explicit code missions require test evidence and syntax validation.
- Text-only answers cannot be promoted to `COMPLETED`.
- The SHA256 smoke fixture proves source extraction, syntax validation, test
  execution, report generation, ingestion, and memory creation with no
  provider dependency.
- `provider_used` / `model_used` are now present in the SHA256 report fixture.

## Metadata Persistence

**Writer (PR `codex/preserve-provider-model-in-learning-runs`):**
`pipeline_auto.build_learning_run_payload()` now reads `session.metadata` and
preserves `provider_used`, `model_used`, `fallback_used`, `provider_status`,
`mission_type`, `agents_used` when available.  `LearningEngine.record_run()`
passes through whatever it receives.

**Upstream propagation (this PR `codex/propagate-provider-model-metadata-upstream`):**
Three new injection points feed `session.metadata` before the writer runs:

1. `execution_supervised_runner` — planned routing: `provider_used` from
   `ctx.metadata["routed_provider"]["provider_id"]`, `mission_type` from
   classification, `fallback_used` from capability_routing decisions.
2. `llm_factory.safe_invoke()` — actual runtime: `record_llm_used()` is called
   after every `llm_call_ok` (primary) and `llm_fallback_ok` (fallback).
3. `bea_executor.run()` — post-pipeline: `build_session_metadata_patch()` merges
   actual > planned values into `session.metadata`.  Existing keys are preserved.

The ContextVar bus (`core/executor/session_meta_bus.py`) scopes tracking to the
current async task — no session_id required, no cross-mission bleed.

**Status: COMPLETE** — future runs will have `provider_used` / `model_used`
populated from the first successful LLM call.  Planned routing values appear
even when all LLM calls failed.

Historical runs can still be incomplete:

- older rows may not have `provider_used` / `model_used`
- missing provider/model values are stored as `null` rather than invented
- the reader stays backwards-compatible with the previous minimal run format

**Remaining limits:**
- `model_used` is resolved at llm_factory call time; the specific free-tier
  model returned by OpenRouter may differ from the `model_id` we sent.  We
  record what we sent (no response-level model extraction).
- Sessions that exit via chat fast-path (no crew) only get planned routing
  metadata; actual model is not tracked for that path.
- `agents_used` from the bus reflects the routing plan, not which agents
  actually executed.  The writer overrides this with actual `session.outputs`
  keys when available.

## CI Status

- PR smoke workflow: enforced via `.github/workflows/pr-smoke.yml`
- Enforced commands:
  - `ruff check .`
  - `python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json`
  - `python scripts/bea_eval.py --json`
  - `python scripts/validate_local.py --quick`
- Provider-backed checks remain outside this PR smoke lane.
- No OpenRouter key or Ollama daemon is required for the enforced PR smoke.

## Model-Role Benchmark

**Multi-role available (2026-06-22).** `scripts/benchmark_model_roles.py`
benchmarks three roles (`forge-builder`, `scout-research`, `shadow-advisor`)
against real providers.

**Results (2026-06-22, multi-role run):**

| Role | Provider | Model | Score | Passed |
|------|----------|-------|-------|--------|
| forge-builder | openrouter | gpt-oss-120b:free | 1.0 | ✅ |
| forge-builder | ollama | gemma4:12b | 0.0 | ❌ (artifact_invalid) |
| scout-research | openrouter | gpt-oss-120b:free | 1.0 | ✅ |
| scout-research | ollama | gemma4:12b | 1.0 | ✅ |
| shadow-advisor | openrouter | gpt-oss-120b:free | 1.0 | ✅ |
| shadow-advisor | ollama | gemma4:12b | 0.33 | ❌ (json_invalid) |

**Experimental observations** (not wired into the router):
- forge-builder: OpenRouter required — Ollama misses the `=== file.py ===` format.
- scout-research: both providers pass — gemma4 produces structured output.
- shadow-advisor: OpenRouter required — gemma4 wraps JSON in markdown.

**No auto-integration:** benchmark results are informational only.  The router
is not updated automatically.  See `docs/MODEL_ROUTING.md` for full details.

**Limits:**
- No CI enforcement — benchmark requires live providers, not run in automated tests.
- Ollama results depend on the local model installed and its context window.
- Results may vary across runs for non-deterministic free-tier models.

## Advisory Routing Mode

Béa can now read benchmark results and produce non-prescriptive provider/model
recommendations per role:

```bash
python scripts/model_routing_advice.py \
    --input workspace/model_role_benchmark_multi_role.json --json
```

**The router is not updated automatically.** Advisory output is informational only
and requires human review before any routing change is applied.

Providers actually tested (2026-06-22):
- OpenRouter `openai/gpt-oss-120b:free` — passed all 3 roles (forge-builder, scout-research, shadow-advisor)
- Ollama `gemma4:12b` — passed scout-research only; failed artifact/JSON for the other two

Remaining limits:
- No automatic CI enforcement for the real benchmark
- Confidence stays `"low"` until multiple independent runs confirm results
- Advisory does not change runtime provider selection

## Remaining Risks

- The validator checks artifact presence and test evidence, not semantic code
  correctness by itself.
- A report can document a test command without this smoke executing that exact
  command.
- Runtime provider behavior remains covered by provider and alpha cycle gates,
  not by this PR.
- Existing historical mission records may still show optimistic statuses until
  re-run through the stricter gate.
- older `learning_runs.json` entries may still lack provider/model until they
  are regenerated through the current executor path.

## Dogfooding — Routing Advice Evidence Pack

**Status: fixture mode available**

`scripts/dogfood_routing_advice.py` generates a structured evidence report
comparing dogfood mission outcomes against the current advisory recommendations.

- Mode: `fixture` — pre-defined results, not live LLM calls.
- 5 missions across forge-builder, scout-research, shadow-advisor.
- 4/5 passed, 5/5 matched_advice (advice_match_rate=100%).
- `runtime_enforced=false` — the router is NOT updated automatically.

**Limits**:
- Fixture mode only — not a live benchmark.
- No CI enforcement of the benchmark.
- Results depend on the advisory which depends on one benchmark run.
- Router automatic modification: **NOT done**.

See `docs/DOGFOODING_REPORT.md` for the full evidence pack details.

## Public Beta Memory Hygiene

**Status: public seed is public-safe**

- `scripts/seed_bea_memory.py` supports `--profile public` (default) and `--profile dev-private`.
- The **public** profile contains only neutral project facts, architecture decisions, and risk rules.
- The **dev-private** profile additionally includes personal fun facts and private jokes (dev-only, never for release).
- `python scripts/seed_bea_memory.py --report --profile public` returns `public_safe: true`.
- `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` detects privacy risks non-destructively.
- `--apply` always aborts (exit 2) — no hidden bypass.

**Limits:**
- `bea_eval` may timeout on very large local stores (100k+ items). For CI and public testing, use a fresh store or the public seed fixture.
- Destructive memory cleanup (`--apply`) is deferred to a future PR with explicit backup support.
- The `.venv-c4-prep/` directory (site-packages) triggers false positives in the except/pass ratchet; this is pre-existing and unrelated to source code.

## Runtime Observability (PR beta-runtime-observability-lite)

**Status: available**

- `core/observability/redactor.py` — privacy-safe redaction for structured logs.
  - Redacts: API keys (`sk-*`), Bearer tokens, bea-tokens, emails, long opaque strings (40+ chars).
  - Preserves: `mission_id`, `provider_used`, `model_used`, `error_category`, `score`, etc.
  - Callable without importing executor (no circular imports).
- `core/observability/mission_event.py` — `MissionEvent` dataclass.
  - Fields: `mission_id`, `mission_type`, `status`, `provider_used`, `model_used`, `agent_used`,
    `duration_ms`, `error_category`, `artifact_status`, `validation_status`, `rate_limited`, `fallback_used`.
  - `.complete(status=, error_category=)` sets duration automatically.
  - `.to_log_dict()` returns redacted dict safe for structured logging.
- `scripts/mission_status_report.py` — local observability report from `workspace/learning_runs.json`.
  - `python scripts/mission_status_report.py --json` outputs JSON summary.
  - Prompts and LLM responses never appear in output.
- 26 tests: `tests/core/observability/` — redactor, MissionEvent, report logic.

**No external services.** No Sentry, OTEL, Datadog, or Prometheus.
