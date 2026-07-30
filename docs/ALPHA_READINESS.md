# Bea Alpha Readiness

This page records the runtime alpha gate for Bea. It complements the fixture
smoke in `docs/E2E_CYCLE.md` with a real provider-backed cycle.

## Current Status

Alpha runtime cycle is proven locally when at least one LLM provider is
available:

- OpenRouter: accepted when `OPENROUTER_API_KEY` is present and usable.
- Ollama: accepted as local fallback when OpenRouter is absent.
- No provider: the cycle fails with a clear configuration message.

Latest verified run:

- Command: `python scripts/run_alpha_cycle.py --isolated-memory --json`
- Provider used: `ollama`
- Health status: `DEGRADED`
- Local model detected: `gemma4:12b`
- OpenRouter key: absent
- Report generated: `workspace/alpha_cycle/<mission_id>/report.json`
- Ingestion: succeeded, 1 report read, 6 memories created
- Memory types: `eval_result`, `model_result`, `skill`, `test_map`, `risk`
- `bea_eval`: 25 total, 25 passed, 0 failed

`DEGRADED` is expected for local alpha when OpenRouter is absent and Ollama is
available. It is mergeable for this gate because the LLM response came from a
real local provider.

## Runtime Cycle

`scripts/run_alpha_cycle.py` performs these checks:

1. Load local `.env` values without printing secrets.
2. Normalize a local CLI `OLLAMA_HOST=0.0.0.0:11434` value to
   `http://127.0.0.1:11434`.
3. Run `ollama list` and `core.providers.runtime_health`.
4. Select OpenRouter when usable, otherwise Ollama when reachable.
5. Retrieve mission-learning memories for the alpha goal.
6. Execute `MetaOrchestrator.run_mission()` with a read-only, force-approved
   alpha mission.
7. Invoke the selected LLM provider through `LLMFactory.safe_invoke()`.
8. Write an ingestion-compatible mission report.
9. Ingest the report with `scripts/ingest_mission_report.py --json`.
10. Run `scripts/bea_eval.py --json`.

## How To Run

Use the default command to write into the configured operational memory store:

```bash
python scripts/run_alpha_cycle.py
```

Use isolated memory when validating a branch without writing to the default
store:

```bash
python scripts/run_alpha_cycle.py --isolated-memory --json
```

Expected success output includes:

- provider `openrouter` or `ollama`
- health `READY` or `DEGRADED`
- all runtime checks true
- ingestion with no errors
- `bea_eval` summary with zero failures

## Remaining Alpha Risks

- Local alpha requires a running Ollama daemon when no OpenRouter key is
  available.
- The current `MetaOrchestrator` runtime still attempts some Codex/Hermes paths
  before local fallback; this can add latency and 401 warnings when Hermes auth
  is unavailable.
- Qdrant/Postgres-backed legacy memory warnings can appear in local runs, but
  the operational memory ingestion gate remains green.
- `provider_healthcheck.py` treats `DEGRADED` as a usable local fallback state;
  only `UNAVAILABLE` is a hard failure for this CLI gate.

## Blocking Conditions

Alpha is blocked only when both are true:

- OpenRouter is absent or unusable.
- Ollama is not reachable or has no usable local model.

In that case `scripts/run_alpha_cycle.py` exits non-zero with:

```text
No LLM provider available. Start Ollama with `ollama serve` or set OPENROUTER_API_KEY.
```
