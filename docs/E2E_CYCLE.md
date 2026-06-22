# Bea E2E Mission Learning Cycle

This document describes the local smoke gate that proves the full Bea mission
learning cycle without requiring OpenRouter, Ollama, or a live LLM.

## Cycle

The smoke cycle is:

1. Generate or read a coding-agent `report.json`.
2. Validate the report contract required by the coding-agent handoff.
3. For code missions, materialize code from the agent response, run a syntax
   check, and run a targeted test command.
4. Run `scripts/ingest_mission_report.py --json` against the report.
5. Store mission-learning memories in an isolated operational memory DB.
6. Verify expected memory types were created.
7. Run `scripts/bea_eval.py --json` and require a green result.

The default command runs both a successful fixture and a failing fixture:

```bash
python scripts/smoke_e2e_cycle.py
```

For machine-readable output:

```bash
python scripts/smoke_e2e_cycle.py --json
```

To run a single built-in fixture:

```bash
python scripts/smoke_e2e_cycle.py --fixture success
python scripts/smoke_e2e_cycle.py --fixture failure
python scripts/smoke_e2e_cycle.py --fixture sha256
```

To run against an existing coding-agent report:

```bash
python scripts/smoke_e2e_cycle.py --report path/to/report.json
```

## What Is Verified

The report must contain these fields:

- `mission_id`
- `goal`
- `mission_type`
- `success`
- `agents_used`
- `tools_used`
- `plan_steps`
- `complexity`
- `error_category`
- `duration_s`
- `provider_used` for code missions
- `model_used` for code missions
- `artifacts` for code missions
- `files_created` for code missions
- `tests_run` for code missions
- `test_result` for code missions
- `report_path`

After ingestion, the smoke requires:

- `eval_result` for every report
- `model_result` when `model_used` is present
- `skill` for successful reports with lessons
- `bug_memory` for failing reports
- `test_map` when tests are present

Mission reports and learning runs should keep `provider_used` and `model_used`
whenever they are known. Those fields let the learner correlate successful
artifacts with the provider/model pair that produced them, which matters for
future routing and regressions. When that information is not available, the
report should keep the field explicit as `null` instead of inventing a value.

## Provider / Model Propagation Path

`provider_used` and `model_used` flow through the pipeline in two stages:

**Stage 1 — Planned routing (before any LLM call):**
`execution_supervised_runner.run_execution()` reads `ctx.metadata["routed_provider"]`
and `ctx.metadata["classification"]["task_type"]` immediately before starting the
mission.  It calls `session_meta_bus.set_initial_meta()` with the routing intent
(provider_id, mission_type, fallback_used from capability decisions).

**Stage 2 — Actual runtime (during LLM calls):**
`llm_factory.safe_invoke()` calls `session_meta_bus.record_llm_used()` after each
successful LLM call (`llm_call_ok` or `llm_fallback_ok`).  Fallback calls set
`fallback=True` so `is_fallback_used()` returns True even when the primary failed.

**Stage 3 — Session metadata injection (after pipeline):**
`bea_executor.run()` calls `session_meta_bus.build_session_metadata_patch()` at
the end of each session.  Actual runtime values take precedence over planned
routing; planned values are used when no LLM call happened (e.g. immediate
failure or chat fast-path).  Existing `session.metadata` keys are never
overwritten.

**Stage 4 — Learning record writer:**
`pipeline_auto.build_learning_run_payload()` reads `session.metadata` and writes
the full metadata dict to `learning_runs.json`.  Fields preserved:
`provider_used`, `model_used`, `fallback_used`, `provider_status`, `mission_type`,
`agent_used`, `agents_used`.

**Why this matters for the model router:**
`fallback_used=True` in a learning run means the primary provider failed and
Ollama answered.  The router can use this signal to temporarily lower reliability
for a given provider.  `model_used` lets the router correlate quality outcomes
with specific model versions — critical when free-tier models (e.g.
`openai/gpt-oss-20b:free`) are swapped out by the provider.

The smoke also runs `python scripts/bea_eval.py --json` by default. A non-zero
exit code or a JSON summary with failures fails the smoke.

## Code Mission Artifacts

A code mission is not complete just because an agent returned useful text. The
cycle now separates:

- text response: prose or a code block in an agent answer
- action: a file, command, or patch action selected by the execution pipeline
- verifiable artifact: existing file path, non-empty diff, successful tool
  action, or structured action report
- completed code mission: verifiable artifact plus syntax validation plus test
  evidence

For any mission with `needs_actions=True`, `COMPLETED` is only valid when at
least one artifact is present. If the report or session only contains text, the
status must remain `NEEDS_ACTION_OUTPUT` or `NEEDS_REVIEW`.

For `mission_type=coding_agent` or another explicit code mission, a completed
report also needs test evidence through `tests_run`, `tests`,
`test_command`, or `test_commands`, and the Python source must compile. Declared
file paths in `files_created`, `files_changed`, or `expected_artifact` must
exist under `artifact_root` or the report directory, unless the mission proves
itself through a non-empty diff.

The SHA256 fixture exercises this rule:

```bash
python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json
```

It creates `src/sha256_file.py`, `tests/test_sha256_file.py`, a compatible
mission report, validates the artifact metadata, runs `py_compile`, runs
`pytest`, ingests the report, and requires a `test_map` memory.

## Model-Role Benchmark

The benchmark sits **outside** the E2E cycle — it does not flow through the
meta-orchestrator or crew.  Run it when you need to verify that a specific
provider/model can fulfill a role's quality bar before committing to routing
changes.

```bash
# After the smoke cycle passes, optionally run:
# Single role:
python scripts/benchmark_model_roles.py --role forge-builder --real \
    --providers openrouter,ollama --json \
    --output workspace/model_role_benchmark_forge_builder.json

# Multi-role (forge-builder, scout-research, shadow-advisor):
python scripts/benchmark_model_roles.py --real \
    --roles forge-builder,scout-research,shadow-advisor \
    --providers openrouter,ollama --json \
    --output workspace/model_role_benchmark_multi_role.json
```

The benchmark sits between the smoke cycle (fixture-only, no real LLM) and a
full mission (meta-orchestrator + crew + memory).  It evaluates raw LLM output
for role-specific quality criteria:

```
mission → provider/model decision → LLM output → role scorer → score/passed
                                                              → report.json
                                                              → future routing policy (manual)
```

A `passed=true` result for a role/provider pair means the model met the
role's quality bar in one shot (score ≥ 0.7).  Results are logged to
`workspace/model_role_benchmark_*.json` and summarised in `best_by_role`.
No routing policy is applied automatically — the benchmark is read-only
relative to the router.

## Advisory Mode

After running the multi-role benchmark, generate non-prescriptive routing
recommendations with:

```bash
python scripts/model_routing_advice.py \
    --input workspace/model_role_benchmark_multi_role.json --json
```

The advisory step extends the cycle:

```
benchmark results → advisory report → human review → (optional) future routing policy
```

The advisory output sets `runtime_enforced=false` and `confidence="low"` for
every recommendation.  It distinguishes between:
- providers that **failed** (response below quality bar)
- providers that were **skipped** (unavailable — not a model quality signal)

No routing change is applied automatically at any step.

## Dogfood Runtime Evidence

`scripts/dogfood_runtime_evidence.py` is the controlled runtime evidence pack
used to prove the dogfood loop without modifying the router.

```bash
python scripts/dogfood_runtime_evidence.py --mode fixture --json --output workspace/dogfood_runtime_fixture.json
python scripts/dogfood_runtime_evidence.py --mode real --json --output workspace/dogfood_runtime_real.json
```

Key points:

- `mode=fixture` never claims to be real.
- `mode=real` uses benchmark evidence when available and surfaces
  `provider_unavailable` explicitly when it is not.
- Every mission report keeps `runtime_enforced=false`.
- The top-level summary includes `matched_advice_count`, `provider_breakdown`,
  and `role_breakdown`.
- The pack is safe to ingest through `scripts/ingest_mission_report.py`.

## Flutter v1 Regression Gate

`tests/test_client_v1_allowlist.py` keeps the client `/api/v1` allowlist empty
after the Flutter v3 migration. New Flutter runtime calls to `/api/v1` fail
with a direct message. A v1 client call can only return through an explicit
allowlist entry plus documented justification.

## Out Of Scope

The smoke does not:

- call a real LLM
- require OpenRouter credentials
- require a running Ollama daemon
- start the API server
- rebuild the Flutter APK
- remove server-side v1 endpoints
- validate deep memory ranking behavior beyond created memory types

## Interpreting Results

Success prints:

```text
[OK] Bea E2E cycle smoke passed
```

The summary includes reports read, memory counts, memory types, and the
`bea_eval` summary. A failure message identifies the failing gate: report
contract, artifact validation, ingestion, missing memory type, or `bea_eval`.

## Adding A Fixture

Add new fixture data by extending `_fixture_payload()` in
`scripts/smoke_e2e_cycle.py` or by creating a standalone `report.json` and
running:

```bash
python scripts/smoke_e2e_cycle.py --report path/to/report.json
```

For a new fixture to exercise the learning loop, include `task_type`,
`files_changed`, `tests_run`, and either `lessons_learned` for success or
`failure_reason` for failure. Keep fixture reports deterministic and free of
external service dependencies.

For a new code fixture with `needs_actions=True`, also include `artifact_root`
when file paths are relative to a temporary artifact directory, plus
`files_created` or `expected_artifact` for the source file, `tests_run` for the
validation command, and `provider_used` / `model_used` / `test_result` in the
final report.

## Local Validation Note

`scripts/validate_local.py` currently runs the broader local gate even when
called with `--quick`; it does not implement a dedicated quick parser yet. For
this PR, use the independent smoke command above for the cheap E2E cycle gate.
