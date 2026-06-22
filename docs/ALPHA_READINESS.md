# Bea Alpha Readiness

## Current Gate Status

- `smoke_e2e_cycle`: local fixture gate, no LLM required.
- `bea_eval`: expected to remain green after mission report ingestion.
- Provider runtime: outside this PR; this change does not touch providers.
- Code mission artifact gate: added for `needs_actions=True` missions.
- Code execution loop: helper added to strip markdown from Python blocks and
  validate syntax before accepting a materialized artifact.

## SHA256 Mission Review

Observed mission:

- `mission_id`: `6ae60964-bae`
- goal: `Ecris une fonction Python sha256_file(path) qui lit par chunks de 8192 bytes. Retourne le digest hex.`
- agent: `forge-builder` with memory/research support
- status recorded by mission state: `DONE`
- learning run status: `SUCCESS`
- duration evidence: latest completed goal entry reports about `71.8s`
- created artifact announced: `sha256_file.py`
- report JSON: not found in the local workspace inspection
- tests: not found

Actual artifact result:

- `C:\Users\maxen\Documents\Béa\workspace\sha256_file.py` exists.
- The original generated file contained Python followed by Markdown sections
  and a closing code fence.
- Running it with Python fails with `SyntaxError`.

Classification: `D. FAILED` as an exploitable code mission. If the UI or
mission state presents it as completed, that completion is weak because the
artifact is not executable and no test or ingestion-compatible report was
found.

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

## Model-Role Benchmark

**Available (2026-06-22).** `scripts/benchmark_model_roles.py` provides a
real-limited benchmark for the forge-builder role against live providers.

**Results:**
- `openai/gpt-oss-120b:free` via OpenRouter: score 1.0 — **PASS** (19 s avg)
  — artifact_ok, syntax_valid, test_proof all True.
- `gemma4:12b` via Ollama: score 0.67 — **near-pass** (32 s avg)
  — artifact_ok, syntax_valid True; test_proof False (model fills sha256_file
  but omits the test file in one-shot generation).

**Routing recommendation:** prefer OpenRouter (`gpt-oss-120b:free`) for
forge-builder missions with `needs_actions=True` and explicit test requirements.
Ollama is acceptable as a latency fallback for simple artifact-only tasks.

**No auto-integration:** benchmark results are informational only.  The router
is not updated automatically.  See `docs/MODEL_ROUTING.md` for the routing
guidance derived from these results.

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
