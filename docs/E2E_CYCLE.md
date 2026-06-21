# Bea E2E Mission Learning Cycle

This document describes the local smoke gate that proves the full Bea mission
learning cycle without requiring OpenRouter, Ollama, or a live LLM.

## Cycle

The smoke cycle is:

1. Generate or read a coding-agent `report.json`.
2. Validate the report contract required by the coding-agent handoff.
3. Run `scripts/ingest_mission_report.py --json` against the report.
4. Store mission-learning memories in an isolated operational memory DB.
5. Verify expected memory types were created.
6. Run `scripts/bea_eval.py --json` and require a green result.

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
- `report_path`

After ingestion, the smoke requires:

- `eval_result` for every report
- `model_result` when `model_used` is present
- `skill` for successful reports with lessons
- `bug_memory` for failing reports
- `test_map` when tests are present

The smoke also runs `python scripts/bea_eval.py --json` by default. A non-zero
exit code or a JSON summary with failures fails the smoke.

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
contract, ingestion, missing memory type, or `bea_eval`.

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

## Local Validation Note

`scripts/validate_local.py` currently runs the broader local gate even when
called with `--quick`; it does not implement a dedicated quick parser yet. For
this PR, use the independent smoke command above for the cheap E2E cycle gate.
